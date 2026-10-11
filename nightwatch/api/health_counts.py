"""The row counts ``/health`` reports, counted in the background and never on a request.

Counting ``bars`` and ``orderbook_snapshots`` takes about 20 s on the box. Done inline every ten
minutes, the request that happened to find the counts expired waited all 20 s for them, and
every other caller arriving meanwhile started a scan of its own (measured: 17-22 s for two or
three callers at each 600 s boundary). Now every caller gets the last good counts at once, and
at most one background thread recounts.

What each situation answers:

* fresh process, counts saved by the previous one: those counts, marked ``stale`` with their age,
  while one recount runs;
* fresh process, nothing saved: the first callers wait (bounded) for the first count; past the
  bound they get zeros marked ``counting``, never an error;
* a recount fails: the last good counts stay, untouched; the failure is logged and counted, and
  the next try waits ``retry_s`` so a broken database is not rescanned back to back;
* it recovers: the next successful recount replaces the counts and clears the failure count.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)

TTL_S = 600.0
RETRY_S = 60.0
# The first count of a process with nothing saved. Under the web proxy's 20 s timeout, so a
# visitor gets an answer from the API rather than the proxy's saved copy.
FIRST_WAIT_S = 15.0


class HealthCounts:
    def __init__(
        self,
        count: Callable[[], tuple[int, int]],
        *,
        saved: Path | None = None,
        ttl_s: float = TTL_S,
        retry_s: float = RETRY_S,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = utc_now,
    ) -> None:
        self._count = count
        self._saved = saved
        self._ttl_s = ttl_s
        self._retry_s = retry_s
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        self._bars: int | None = None
        self._books: int | None = None
        self._counted_at: datetime | None = None
        self._counted_m: float | None = None  # monotonic time of the last good count in this process
        self._tried_m: float | None = None
        self._last_failed = False
        self._running = False
        self._settled = threading.Event()  # set once there are counts, or the first attempt has ended
        self.failures = 0
        self.refreshes = 0
        self._load()

    # --- reading -------------------------------------------------------------------------------

    def read(self, first_wait_s: float = FIRST_WAIT_S) -> dict[str, Any]:
        """The counts to report now. Starts a recount if they are due; waits only when this
        process has no counts at all, and then at most ``first_wait_s``."""
        self.refresh_if_due()
        if self._bars is None and first_wait_s > 0:
            self._settled.wait(first_wait_s)
        with self._lock:
            now = self._clock()
            have = self._bars is not None
            fresh = self._counted_m is not None and now - self._counted_m <= self._ttl_s
            if not have:
                state = "unavailable" if self._last_failed and not self._running else "counting"
            else:
                state = "fresh" if fresh else "stale"
            at = self._counted_at
            return {
                "bars": self._bars or 0,
                "books": self._books or 0,
                "state": state,
                "at": at.isoformat() if at else None,
                "age_s": max(0, int((self._wall() - at).total_seconds())) if at else None,
                "refreshing": self._running,
                "failures": self.failures,
            }

    # --- refreshing ----------------------------------------------------------------------------

    def refresh_if_due(self) -> bool:
        """Start one background recount if the counts are due and none is running. True if it
        started one. Never blocks on the count itself."""
        with self._lock:
            if self._running:
                return False
            now = self._clock()
            if self._counted_m is not None and now - self._counted_m < self._ttl_s:
                return False
            if self._last_failed and self._tried_m is not None and now - self._tried_m < self._retry_s:
                return False
            self._running = True
            self._tried_m = now
        try:
            threading.Thread(target=self._run, name="health-counts", daemon=True).start()
        except Exception as exc:  # noqa: BLE001 - no thread to spare: keep serving what we have
            with self._lock:
                self._running = False
                self._last_failed = True
                self.failures += 1
            log.warning("could not start the health count: %s", exc)
            return False
        return True

    def _run(self) -> None:
        try:
            bars, books = self._count()
            bars, books = int(bars), int(books)
            if bars < 0 or books < 0:
                raise ValueError(f"negative count ({bars}, {books})")
        except Exception as exc:  # noqa: BLE001 - a failed count must leave the last good one alone
            with self._lock:
                self._last_failed = True
                self.failures += 1
                n = self.failures
            log.warning("health count failed (%d in a row), keeping the last good counts: %s", n, exc)
        else:
            at = self._wall()
            with self._lock:
                self._bars, self._books = bars, books
                self._counted_at, self._counted_m = at, self._clock()
                self._last_failed = False
                self.failures = 0
                self.refreshes += 1
            self._save(bars, books, at)
        finally:
            with self._lock:
                self._running = False
            self._settled.set()

    # --- carried across restarts ---------------------------------------------------------------

    def _load(self) -> None:
        """The counts the previous process saved, so a restart does not begin with nothing.
        They are reported as stale and recounted straight away."""
        if self._saved is None:
            return
        try:
            d = json.loads(self._saved.read_text(encoding="utf-8"))
            bars, books, at = int(d["bars"]), int(d["books"]), datetime.fromisoformat(d["at"])
            if bars < 0 or books < 0 or at.tzinfo is None:
                raise ValueError("bad saved counts")
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001 - a damaged file is no counts, not a crash
            log.info("ignoring saved health counts: %s", exc)
            return
        self._bars, self._books, self._counted_at = bars, books, at
        self._settled.set()

    def _save(self, bars: int, books: int, at: datetime) -> None:
        if self._saved is None:
            return
        tmp = self._saved.with_name(self._saved.name + ".tmp")
        try:
            tmp.write_text(json.dumps({"bars": bars, "books": books, "at": at.isoformat()}), encoding="utf-8")
            os.replace(tmp, self._saved)
        except Exception as exc:  # noqa: BLE001 - not saving only costs the next restart its head start
            log.info("could not save health counts: %s", exc)
