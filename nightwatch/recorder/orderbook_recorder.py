"""Order-book and ticker recorder.

Why it exists: Bitget publishes only the *current* book. Liquidity history — how deep
the book is at 3 a.m. on a Sunday versus 10 a.m. on a Tuesday — does not exist
anywhere unless someone records it. This process snapshots every tracked book on a
fixed cadence and stores depth metrics, so exit-cost analysis has real history.

Design
------
* Wall-clock aligned ticks (``interval_sec``); a slow tick never drifts the schedule.
* One request per book, one request for *all* spot tickers, one for all perp tickers.
* Per-symbol failures are logged and skipped; the loop never dies on one bad call.
* Graceful shutdown on SIGINT/SIGTERM; the current tick finishes, then we exit.
* Optional periodic bar refresh so the stored candles stay current without a cron.
* Arbitrary periodic jobs (calendars, news, forecast maturation) ride the same loop, each
  with its own cadence and error isolation, so one always-on process keeps every input
  current.
* Old snapshots are pruned daily to a retention window (metrics rows are small, but
  raw level JSON adds up over months).
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from nightwatch.data.bitget import BitgetPublicClient
from nightwatch.data.models import Interval, Venue
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry, refresh_universe
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)


@dataclass
class RecorderStats:
    ticks: int = 0
    snapshots: int = 0
    ticker_rows: int = 0
    errors: int = 0
    last_tick_seconds: float = 0.0
    started_at: float = field(default_factory=time.time)


@dataclass
class PeriodicJob:
    """A named callable run at most once per ``every_sec`` inside the recorder loop."""

    name: str
    every_sec: float
    fn: Callable[[], object]
    run_at_start: bool = True
    last_run: float = field(default=0.0, init=False)
    runs: int = field(default=0, init=False)
    failures: int = field(default=0, init=False)

    def due(self, now: float) -> bool:
        if self.runs == 0 and not self.run_at_start and self.last_run == 0.0:
            self.last_run = now  # first run happens one full period from now
            return False
        return now - self.last_run >= self.every_sec


class OrderBookRecorder:
    def __init__(
        self,
        store: Store,
        *,
        spot: BitgetPublicClient,
        perp: BitgetPublicClient,
        entries: Sequence[UniverseEntry],
        interval_sec: int = 60,
        record_perp_books: bool = True,
        refresh_bars_every_sec: int | None = 900,
        retention_days: int = 120,
        jobs: Sequence[PeriodicJob] = (),
    ):
        if interval_sec < 5:
            raise ValueError("interval_sec must be >= 5")
        self.store = store
        self.spot = spot
        self.perp = perp
        self.entries = list(entries)
        self.interval_sec = interval_sec
        self.record_perp_books = record_perp_books
        self.refresh_every = refresh_bars_every_sec
        self.retention = timedelta(days=retention_days)
        self.jobs = list(jobs)
        self.stats = RecorderStats()
        self._stop = threading.Event()
        self._last_refresh = 0.0
        self._last_prune = 0.0

    # ----------------------------------------------------------------- control

    def request_stop(self, *_: object) -> None:
        log.info("stop requested; finishing current tick")
        self._stop.set()

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self.request_stop)
            except (ValueError, OSError):  # not main thread / unsupported platform
                pass

    # -------------------------------------------------------------------- loop

    def run_forever(self) -> None:
        log.info("recorder: %d entries, every %ds, perp books=%s", len(self.entries), self.interval_sec, self.record_perp_books)
        next_tick = time.time()
        while not self._stop.is_set():
            now = time.time()
            if now < next_tick:
                self._stop.wait(next_tick - now)
                if self._stop.is_set():
                    break
            began = time.time()
            self.tick()
            self.stats.last_tick_seconds = time.time() - began
            # Align to the schedule; skip missed slots rather than bunching them up.
            next_tick += self.interval_sec
            while next_tick < time.time():
                next_tick += self.interval_sec
        log.info("recorder stopped: %s", self.stats)

    def tick(self) -> None:
        self.stats.ticks += 1
        self._record_tickers()
        for e in self.entries:
            self._record_book(self.spot, e.spot_symbol)
            if self.record_perp_books and e.perp_symbol:
                self._record_book(self.perp, e.perp_symbol)
        self._maybe_refresh_bars()
        self._run_due_jobs()
        self._maybe_prune()
        if self.stats.ticks % 10 == 0:
            log.info("recorder heartbeat: %s", self.stats)

    # ------------------------------------------------------------------- steps

    def _record_book(self, client: BitgetPublicClient, symbol: str) -> None:
        try:
            snap = client.get_orderbook(symbol)
            self.store.insert_orderbook(snap)
            self.stats.snapshots += 1
        except Exception as exc:  # noqa: BLE001
            self.stats.errors += 1
            log.warning("book %s %s failed: %s", client.venue.value, symbol, exc)

    def _record_tickers(self) -> None:
        wanted_spot = {e.spot_symbol for e in self.entries}
        wanted_perp = {e.perp_symbol for e in self.entries if e.perp_symbol}
        for client, wanted in ((self.spot, wanted_spot), (self.perp, wanted_perp)):
            if not wanted:
                continue
            try:
                rows = [t for t in client.list_tickers() if t.symbol in wanted]
                self.stats.ticker_rows += self.store.insert_tickers(rows)
            except Exception as exc:  # noqa: BLE001
                self.stats.errors += 1
                log.warning("tickers %s failed: %s", client.venue.value, exc)

    def _maybe_refresh_bars(self) -> None:
        if not self.refresh_every:
            return
        if time.time() - self._last_refresh < self.refresh_every:
            return
        self._last_refresh = time.time()
        try:
            n = refresh_universe(self.store, self.entries, spot=self.spot, perp=self.perp, intervals=(Interval.H1,))
            log.info("bar refresh: %d rows", n)
        except Exception:  # noqa: BLE001
            self.stats.errors += 1
            log.exception("bar refresh failed")

    def _run_due_jobs(self) -> None:
        now = time.time()
        for job in self.jobs:
            if not job.due(now):
                continue
            job.last_run = now
            job.runs += 1
            try:
                result = job.fn()
                log.info("job %s: %s", job.name, result)
            except Exception:  # noqa: BLE001
                job.failures += 1
                self.stats.errors += 1
                log.exception("job %s failed", job.name)

    def _maybe_prune(self) -> None:
        if time.time() - self._last_prune < 86400:
            return
        self._last_prune = time.time()
        try:
            n = self.store.prune_orderbooks_older_than(utc_now() - self.retention)
            if n:
                log.info("pruned %d old order-book snapshots", n)
        except Exception:  # noqa: BLE001
            log.exception("prune failed")

    # ------------------------------------------------------------------ helpers

    @property
    def venues(self) -> tuple[Venue, ...]:
        return (Venue.BITGET_SPOT, Venue.BITGET_UMCBL) if self.record_perp_books else (Venue.BITGET_SPOT,)
