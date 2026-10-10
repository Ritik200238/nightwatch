"""Where a request's time goes: waiting for the analysis lock, or doing the work.

Why this exists: a chat answer was seen to take 30-50 s while the analysis itself takes
about 3 s, and nothing on the box could say whether the rest was a queue (another analysis,
the warm-up, a cache refill holding the one lock), work done before the lock was asked for,
or work done after it was let go. The container starts ``uvicorn`` with no logging
configuration, so the ``log.info`` calls in this package never reach ``docker logs`` and
uvicorn's own access line carries no duration.

What it records, per request, one line (see ``RequestTiming.line``):

* ``total_ms``      arrival to the last byte sent (for a stream: until the stream ends)
* ``to_lock_ms``    arrival to the first time the request asked for the analysis lock
* ``lock_wait_ms``  time spent waiting for it, summed over the request's acquisitions
* ``lock_hold_ms``  time spent holding it - the analysis itself, plus whatever the holder
                    does inside the ``with`` block (storing the report)
* ``after_lock_ms`` last release to the end (writing the briefing, building the card)
* ``queued_ahead``  how many requests held or waited for the lock when it asked (a warm-up
                    step is not a request: it is named in ``holder``, not counted here)
* ``holder``        who held the lock at that moment, and for how long already
* ``marks``         named points on the way (``work_start``, ``chat_turn``), as ms from arrival

What it never records: the request body, the query string (it carries the anonymous visitor
id), headers, client addresses, or anything the visitor typed. Only the method and the path.

Lines go to their own logger with their own stderr handler, so they appear in ``docker logs``
whatever the root logger does, and are not doubled when something else configures it.
The same records are kept in memory (the last ``RECENT_MAX``) and served by ``GET /timing``,
because the box's own log is not reachable from outside it. ``NIGHTWATCH_TIMING=0`` switches the
module off.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

SLOW_REQUEST_S = 3.0  # a request that touched no lock is logged only when it took this long

RECENT_MAX = 300  # how many requests ``/timing`` remembers

logger = logging.getLogger("nightwatch.timing")
_configured = False
_configure_mu = threading.Lock()
_recent: deque[dict[str, Any]] = deque(maxlen=RECENT_MAX)


def recent(limit: int = 100) -> list[dict[str, Any]]:
    """The most recent logged requests, newest first. Kept in memory only: a restart empties it,
    and the log line is the durable copy. Nothing in it is anything a visitor typed."""
    return list(_recent)[::-1][: max(0, limit)]


def enabled() -> bool:
    return os.environ.get("NIGHTWATCH_TIMING", "1") != "0"


def _ensure_handler() -> None:
    global _configured
    if _configured:
        return
    with _configure_mu:
        if _configured:
            return
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%dT%H:%M:%S"))
            logger.addHandler(handler)
        _configured = True


class RequestTiming:
    """The clock of one request. Written from the worker threads the request runs on."""

    def __init__(self, method: str, path: str) -> None:
        self.method = method
        self.path = path
        self.started = time.monotonic()
        self._mu = threading.Lock()
        self.locks = 0
        self.wait_s = 0.0
        self.hold_s = 0.0
        self.first_ask: float | None = None
        self.last_release: float | None = None
        self.queued_ahead = 0
        self.holder = ""
        self.gave_up = 0
        self.marks: list[tuple[str, float]] = []

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"

    def mark(self, name: str) -> None:
        with self._mu:
            self.marks.append((name, time.monotonic() - self.started))

    def lock_taken(self, asked: float, got: float, ahead: int, holder: str, holder_for_s: float) -> None:
        with self._mu:
            if self.first_ask is None:
                self.first_ask = asked
            self.locks += 1
            self.wait_s += max(0.0, got - asked)
            # Name who held the lock when the first acquisition asked: that is the one it waited for.
            self.queued_ahead = max(self.queued_ahead, ahead)
            if holder and not self.holder:
                self.holder = f"{holder} for {holder_for_s * 1000:.0f}ms"

    def lock_released(self, got: float, released: float) -> None:
        with self._mu:
            self.hold_s += max(0.0, released - got)
            self.last_release = released

    def lock_gave_up(self, asked: float, gave_up_at: float, ahead: int, holder: str, holder_for_s: float) -> None:
        with self._mu:
            if self.first_ask is None:
                self.first_ask = asked
            self.locks += 1
            self.gave_up += 1
            self.wait_s += max(0.0, gave_up_at - asked)
            self.queued_ahead = max(self.queued_ahead, ahead)
            if holder and not self.holder:
                self.holder = f"{holder} for {holder_for_s * 1000:.0f}ms"

    def record(self, status: int, outcome: str, ended: float | None = None) -> dict[str, Any]:
        """The request as numbers (milliseconds, whole), the form the log line and ``/timing`` share."""
        end = time.monotonic() if ended is None else ended
        ms = lambda s: round(max(0.0, s) * 1000)  # noqa: E731
        with self._mu:
            out: dict[str, Any] = {
                "method": self.method, "path": self.path, "status": status, "outcome": outcome,
                "total_ms": ms(end - self.started),
            }
            if self.locks:
                out.update({
                    "to_lock_ms": ms((self.first_ask or self.started) - self.started),
                    "lock_wait_ms": ms(self.wait_s),
                    "lock_hold_ms": ms(self.hold_s),
                    "after_lock_ms": ms(end - self.last_release) if self.last_release else None,
                    "locks": self.locks, "queued_ahead": self.queued_ahead,
                })
                if self.gave_up:
                    out["gave_up"] = self.gave_up
                if self.holder:
                    out["holder"] = self.holder
            if self.marks:
                out["marks"] = {n: ms(s) for n, s in self.marks}
        return out

    def line(self, status: int, outcome: str, ended: float | None = None) -> str:
        r = self.record(status, outcome, ended)
        parts = ["nw_timing"]
        for key, value in r.items():
            if key == "marks":
                parts.append("marks=" + ",".join(f"{n}:{v}" for n, v in value.items()))
            elif key == "holder":
                parts.append(f'holder="{value}"')
            else:
                parts.append(f"{key}={'-' if value is None else value}")
        return " ".join(parts)

    def worth_logging(self, total_s: float) -> bool:
        if self.method == "OPTIONS":
            return False
        return self.locks > 0 or total_s >= SLOW_REQUEST_S


_current: contextvars.ContextVar[RequestTiming | None] = contextvars.ContextVar("nightwatch_timing", default=None)


def current() -> RequestTiming | None:
    return _current.get()


@contextlib.contextmanager
def attached(timing: RequestTiming | None) -> Iterator[None]:
    """Make ``timing`` the current request inside a worker thread that did not inherit it
    (``loop.run_in_executor`` does not carry context across)."""
    token = _current.set(timing)
    try:
        yield
    finally:
        _current.reset(token)


def mark(name: str) -> None:
    """A named point on the current request's clock; nothing outside a request."""
    t = _current.get()
    if t is not None:
        t.mark(name)


def who() -> str:
    """Who is asking for the lock: the request, or the background thread that has no request."""
    t = _current.get()
    return t.label if t is not None else threading.current_thread().name


class TimingMiddleware:
    """Pure ASGI, so the clock starts when the request arrives and ends when the last byte
    of the response has been sent, and the request's context reaches every thread it uses."""

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        if scope.get("type") != "http" or not enabled():
            await self.app(scope, receive, send)
            return
        timing = RequestTiming(scope.get("method", ""), scope.get("path", ""))
        token = _current.set(timing)
        status = 0
        outcome = "ok"

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 0))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            # The visitor went away or the app raised; the line still says where the time went.
            outcome = "aborted"
            raise
        finally:
            _current.reset(token)
            ended = time.monotonic()
            if timing.worth_logging(ended - timing.started):
                try:
                    _ensure_handler()
                    entry = timing.record(status, outcome, ended)
                    _recent.append({"at": datetime.now(UTC).isoformat(timespec="seconds"), **entry})
                    logger.info(timing.line(status, outcome, ended))
                except Exception:  # noqa: BLE001 - a log line must never fail a request
                    pass
