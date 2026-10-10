"""A lock that lets people go before the background warm-up.

Every analysis shares one frame cache, so they run one at a time under a single lock.
The warm-up loop takes that lock too, once per token, to build all twenty-four frames
after a restart and again at the top of every hour. A plain lock is not fair: the warm
loop releases it and takes it straight back, so a chat that arrived meanwhile waited for
the whole pass. Measured on the box after a restart, a weekend NVDA question sent while
the warm-up was at 14 of 24 tokens took 26 s; it needs one frame and builds it in about one.

Requests use it exactly like ``threading.Lock`` (``with lock:``). The warm-up uses
``with lock.background():``, which first waits until no request holds or wants the lock.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from nightwatch.api import timing


class DeskBusy(TimeoutError):
    """The analysis lock was not free within the wait the caller allowed."""


class RequestFirstLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cv = threading.Condition()
        self._wanted = 0  # requests that hold the lock or are waiting for it
        # Who holds it and since when, so a request that had to queue can say behind whom
        # (see nightwatch.api.timing). Only the holder writes these, and there is one holder.
        self._holder = ""
        self._held_since = 0.0

    def _ask(self) -> tuple[float, int, str, float]:
        """Count a caller in and note who holds the lock at this moment, for the timing line."""
        with self._cv:
            ahead = self._wanted
            self._wanted += 1
        now = time.monotonic()
        holder = self._holder
        return now, ahead, holder, (now - self._held_since) if holder else 0.0

    def _took(self, asked: tuple[float, int, str, float]) -> float:
        got = time.monotonic()
        self._holder, self._held_since = timing.who(), got
        self._note(lambda t: t.lock_taken(asked[0], got, asked[1], asked[2], asked[3]))
        return got

    def _gave_up(self, asked: tuple[float, int, str, float]) -> None:
        self._note(lambda t: t.lock_gave_up(asked[0], time.monotonic(), asked[1], asked[2], asked[3]))

    def _let_go(self) -> float:
        """Mark the lock free (before it is released, so the next holder's mark is not erased)."""
        self._holder = ""
        return time.monotonic()

    @staticmethod
    def _note(record: Callable[[timing.RequestTiming], None]) -> None:
        # Timing is a report on the lock, never a part of it: nothing it does may fail a request.
        try:
            t = timing.current()
            if t is not None:
                record(t)
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> RequestFirstLock:
        asked = self._ask()
        try:
            self._lock.acquire()
        except BaseException:
            self._done()
            raise
        self._took(asked)
        return self

    def __exit__(self, *exc: object) -> None:
        got = self._held_since
        released = self._let_go()
        self._lock.release()
        self._done()
        self._note(lambda t: t.lock_released(got, released))

    def _done(self) -> None:
        with self._cv:
            self._wanted -= 1
            self._cv.notify_all()

    @contextmanager
    def request(self, timeout_s: float) -> Iterator[None]:
        """Like ``with lock:`` but gives up with ``DeskBusy`` after ``timeout_s`` seconds, so a
        caller with its own deadline never queues past it (and never runs late, unseen)."""
        asked = self._ask()
        if not self._lock.acquire(timeout=max(0.0, timeout_s)):
            self._done()
            self._gave_up(asked)
            raise DeskBusy(f"the analysis lock was not free within {timeout_s:.0f} s")
        got = self._took(asked)
        try:
            yield
        finally:
            released = self._let_go()
            self._lock.release()
            self._done()
            self._note(lambda t: t.lock_released(got, released))

    @property
    def wanted(self) -> int:
        return self._wanted

    def snapshot(self) -> dict[str, object]:
        """Who holds the lock right now, for how long, and how many are in line (a diagnostic)."""
        holder = self._holder
        held = round((time.monotonic() - self._held_since) * 1000) if holder else 0
        return {"wanted": self._wanted, "holder": holder, "held_ms": held}

    @contextmanager
    def background(self, max_wait_s: float | None = None) -> Iterator[None]:
        """Hold the lock for background work, once no request wants it.

        A request that arrives after this has started still waits for this one step, so
        background steps must stay short (one token's frame, about a second)."""
        with self._cv:
            self._cv.wait_for(lambda: self._wanted == 0, timeout=max_wait_s)
        with self._lock:
            self._holder, self._held_since = timing.who(), time.monotonic()
            try:
                yield
            finally:
                self._holder = ""
