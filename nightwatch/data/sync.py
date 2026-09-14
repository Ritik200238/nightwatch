"""Universe resolution and data synchronisation.

Responsibilities
----------------
* Build the **universe**: every tokenized US stock on Bitget spot (``rTICKER``), its
  matching USDT perpetual when one exists, and the native ticker for Yahoo/Nasdaq.
  Perps are matched by cross-referencing the spot list — Bitget's own ``isRwa`` flag
  also covers FX, metals, indices and non-US listings, so it is not used alone.
* **Backfill** bars for a symbol/interval/kind over a date range, persisting in
  chunks so a crash loses at most one chunk, and skipping ranges already stored.
* **Refresh** the tail of a series cheaply through the 1000-bar recent endpoint.
* Sync calendars (earnings, macro), funding and news.
* Produce a **coverage report** so anyone can see exactly what data exists.

Everything is idempotent: re-running a sync only fetches what is missing.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from nightwatch.config import Settings
from nightwatch.data.bitget import BitgetPublicClient
from nightwatch.data.fred import FredClient
from nightwatch.data.models import Instrument, Interval, PriceKind, Venue
from nightwatch.data.nasdaq import NasdaqEarningsClient
from nightwatch.data.rss import RssNewsClient
from nightwatch.data.store import Store
from nightwatch.data.yahoo import YahooChartClient
from nightwatch.time_utils import UTC, ensure_utc, utc_now

log = logging.getLogger(__name__)

HISTORY_START = datetime(2025, 1, 1, tzinfo=UTC)
BACKFILL_CHUNK = timedelta(days=45)

# rToken base symbols that differ from Yahoo's ticker spelling.
YAHOO_TICKER_OVERRIDES: dict[str, str] = {
    "BRKB": "BRK-B",
    "BFB": "BF-B",
}


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str  # native US ticker, e.g. TSLA
    spot_symbol: str  # RTSLAUSDT
    perp_symbol: str | None  # TSLAUSDT or None
    yahoo_ticker: str
    is_core: bool


def resolve_universe(store: Store, spot: BitgetPublicClient, perp: BitgetPublicClient, settings: Settings) -> list[UniverseEntry]:
    """Fetch instrument lists, persist them, and return the resolved universe (core first)."""
    spot_ins = list(spot.list_instruments())
    perp_ins = list(perp.list_instruments())
    store.upsert_instruments(spot_ins)
    store.upsert_instruments(perp_ins)
    return build_universe(spot_ins, perp_ins, settings.core_tickers)


def build_universe(spot_ins: Sequence[Instrument], perp_ins: Sequence[Instrument], core: Iterable[str]) -> list[UniverseEntry]:
    core_set = {c.upper() for c in core}
    perps_by_base: dict[str, Instrument] = {}
    for p in perp_ins:
        if p.is_tokenized_stock and p.status.lower() in ("normal", "online"):
            perps_by_base.setdefault(p.base.upper(), p)
    out: list[UniverseEntry] = []
    for s in spot_ins:
        if not s.is_tokenized_stock or s.status.lower() != "online" or not s.underlying_ticker:
            continue
        ticker = s.underlying_ticker.upper()
        perp = perps_by_base.get(ticker)
        out.append(
            UniverseEntry(
                ticker=ticker,
                spot_symbol=s.symbol,
                perp_symbol=perp.symbol if perp else None,
                yahoo_ticker=YAHOO_TICKER_OVERRIDES.get(ticker, ticker),
                is_core=ticker in core_set,
            )
        )
    out.sort(key=lambda e: (not e.is_core, e.ticker))
    return out


# ------------------------------------------------------------------------ bars


def _missing_ranges(store: Store, venue: Venue, symbol: str, interval: Interval, kind: PriceKind, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    cov = store.bar_coverage(venue, symbol, interval, kind=kind)
    if cov is None:
        return [(start, end)]
    cov_min, cov_max, _ = cov
    step = timedelta(seconds=interval.seconds)
    ranges = []
    if start < cov_min:
        ranges.append((start, cov_min))
    if cov_max + step < end:
        ranges.append((cov_max + step, end))
    return ranges


def backfill_bars(
    store: Store,
    client: BitgetPublicClient,
    symbol: str,
    interval: Interval,
    *,
    start: datetime = HISTORY_START,
    end: datetime | None = None,
    kind: PriceKind = PriceKind.TRADE,
    chunk: timedelta = BACKFILL_CHUNK,
) -> int:
    """Fetch and store every bar in ``[start, end)`` not already present. Returns rows stored."""
    end = ensure_utc(end or utc_now())
    start = ensure_utc(start)
    total = 0
    for r_start, r_end in _missing_ranges(store, client.venue, symbol, interval, kind, start, end):
        cursor_end = r_end
        while cursor_end > r_start:
            cursor_start = max(r_start, cursor_end - chunk)
            began = utc_now()
            bars = client.get_bars(symbol, interval, cursor_start, cursor_end, kind=kind)
            n = store.upsert_bars(bars)
            store.log_sync("bars", venue=client.venue, symbol=symbol, interval=interval, kind=kind, range_start=cursor_start, range_end=cursor_end, rows=n, started_at=began, finished_at=utc_now())
            total += n
            log.info("backfill %s %s %s %s: %s -> %s: %d bars", client.venue.value, symbol, interval.value, kind.value, cursor_start.date(), cursor_end.date(), n)
            if not bars:
                # A whole chunk with no bars on a 24/7 venue means we walked past the
                # instrument's listing date; earlier chunks would be empty too.
                log.info("backfill %s %s: history exhausted before %s", client.venue.value, symbol, cursor_end.date())
                break
            cursor_end = cursor_start
    return total


def refresh_bars(
    store: Store,
    client: BitgetPublicClient,
    symbol: str,
    interval: Interval,
    *,
    kind: PriceKind = PriceKind.TRADE,
    allow_backfill: bool = True,
) -> int:
    """Bring the tail of a series up to date. Uses the 1000-bar recent endpoint when
    that is enough, else falls back to backfilling the missing tail.

    ``allow_backfill=False`` makes this strictly a tail refresh: series with no stored
    history are skipped (the recorder uses this so it never duplicates a running sync).
    """
    cov = store.bar_coverage(client.venue, symbol, interval, kind=kind)
    now = utc_now()
    if cov is None:
        if not allow_backfill:
            return 0
        return backfill_bars(store, client, symbol, interval, kind=kind)
    _, cov_max, _ = cov
    step = timedelta(seconds=interval.seconds)
    missing = int((now - cov_max) / step)
    if missing <= 0:
        return 0
    if missing < 950:
        began = now
        bars = client.get_recent_bars(symbol, interval, limit=min(1000, missing + 5), kind=kind)
        n = store.upsert_bars(bars)
        store.log_sync("refresh", venue=client.venue, symbol=symbol, interval=interval, kind=kind, rows=n, started_at=began, finished_at=utc_now())
        return n
    if not allow_backfill:
        return 0
    return backfill_bars(store, client, symbol, interval, start=cov_max + step, kind=kind)


def sync_equity_bars(store: Store, yahoo: YahooChartClient, ticker: str, *, daily_start: datetime = datetime(2015, 1, 1, tzinfo=UTC)) -> int:
    now = utc_now()
    total = 0
    for interval, start in ((Interval.D1, daily_start), (Interval.H1, now - timedelta(days=729))):
        for r_start, r_end in _missing_ranges(store, Venue.YAHOO, ticker, interval, PriceKind.TRADE, start, now):
            began = utc_now()
            bars = yahoo.get_bars(ticker, interval, r_start, r_end)
            n = store.upsert_bars(bars)
            store.log_sync("bars", venue=Venue.YAHOO, symbol=ticker, interval=interval, range_start=r_start, range_end=r_end, rows=n, started_at=began, finished_at=utc_now())
            total += n
            log.info("yahoo %s %s: %d bars", ticker, interval.value, n)
    return total


# --------------------------------------------------------------- universe sync


@dataclass
class SyncStats:
    entries: int = 0
    spot_bars: int = 0
    perp_bars: int = 0
    equity_bars: int = 0
    funding: int = 0
    earnings: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def sync_universe(
    store: Store,
    entries: Sequence[UniverseEntry],
    *,
    spot: BitgetPublicClient,
    perp: BitgetPublicClient,
    yahoo: YahooChartClient,
    nasdaq: NasdaqEarningsClient | None = None,
    intervals: Sequence[Interval] = (Interval.H1, Interval.D1),
    perp_kinds: Sequence[PriceKind] = (PriceKind.TRADE, PriceKind.INDEX, PriceKind.MARK),
    start: datetime = HISTORY_START,
    include_equity: bool = True,
) -> SyncStats:
    """Backfill everything for each universe entry. Errors are collected, not raised,
    so one bad symbol never stops a multi-hour run."""
    stats = SyncStats(entries=len(entries))
    for i, e in enumerate(entries, 1):
        log.info("[%d/%d] %s (spot %s, perp %s)", i, len(entries), e.ticker, e.spot_symbol, e.perp_symbol)
        try:
            for interval in intervals:
                stats.spot_bars += backfill_bars(store, spot, e.spot_symbol, interval, start=start)
            if e.perp_symbol:
                for interval in intervals:
                    for kind in perp_kinds:
                        stats.perp_bars += backfill_bars(store, perp, e.perp_symbol, interval, start=start, kind=kind)
                stats.funding += store.upsert_funding(perp.get_funding_history(e.perp_symbol, start, utc_now()))
            if include_equity:
                stats.equity_bars += sync_equity_bars(store, yahoo, e.yahoo_ticker)
            if nasdaq is not None:
                stats.earnings += store.upsert_earnings(nasdaq.get_history(e.ticker))
        except Exception as exc:  # noqa: BLE001
            msg = f"{e.ticker}: {exc}"
            log.exception("sync failed for %s", e.ticker)
            stats.errors.append(msg)
    return stats


def refresh_universe(
    store: Store,
    entries: Sequence[UniverseEntry],
    *,
    spot: BitgetPublicClient,
    perp: BitgetPublicClient,
    intervals: Sequence[Interval] = (Interval.H1,),
    allow_backfill: bool = False,
) -> int:
    n = 0
    for e in entries:
        try:
            for interval in intervals:
                n += refresh_bars(store, spot, e.spot_symbol, interval, allow_backfill=allow_backfill)
                if e.perp_symbol:
                    for kind in (PriceKind.TRADE, PriceKind.INDEX, PriceKind.MARK):
                        n += refresh_bars(store, perp, e.perp_symbol, interval, kind=kind, allow_backfill=allow_backfill)
        except Exception:  # noqa: BLE001
            log.exception("refresh failed for %s", e.ticker)
    return n


# ---------------------------------------------------------------- calendars


def sync_calendars(store: Store, *, nasdaq: NasdaqEarningsClient, fred: FredClient, days_ahead: int = 120, days_back: int = 30) -> tuple[int, int]:
    now = utc_now()
    began = now
    earnings = nasdaq.get_calendar(now - timedelta(days=days_back), now + timedelta(days=days_ahead))
    n_e = store.upsert_earnings(earnings)
    store.log_sync("earnings_calendar", rows=n_e, started_at=began, finished_at=utc_now())
    began = utc_now()
    macro = fred.get_release_calendar(HISTORY_START, now + timedelta(days=days_ahead))
    n_m = store.upsert_macro(macro)
    store.log_sync("macro_calendar", rows=n_m, started_at=began, finished_at=utc_now())
    return n_e, n_m


def sync_macro_series(store: Store, fred: FredClient, series: Iterable[str], *, start: datetime = datetime(2015, 1, 1, tzinfo=UTC)) -> int:
    n = 0
    for sid in series:
        began = utc_now()
        try:
            rows = fred.get_series(sid, start, utc_now())
        except Exception:  # noqa: BLE001
            log.exception("fred series %s failed", sid)
            continue
        k = store.upsert_macro(rows)
        store.log_sync("macro_series", symbol=sid, rows=k, started_at=began, finished_at=utc_now())
        n += k
    return n


def sync_filings(store: Store, sec, tickers: Iterable[str], *, since: datetime | None = None) -> int:  # noqa: ANN001
    """Pull every news-bearing SEC filing for the given tickers. Idempotent."""
    began = utc_now()
    n = 0
    for t in tickers:
        try:
            n += store.upsert_filings(sec.get_filings(t, since=since))
        except Exception as exc:  # noqa: BLE001 - one issuer failing must not stop the rest
            log.warning("filings for %s failed: %s", t, exc)
    store.log_sync("filings", rows=n, started_at=began, finished_at=utc_now())
    return n


def sync_equity_universe(store: Store, yahoo: YahooChartClient, entries: Sequence[UniverseEntry]) -> int:
    """Bring the native US stocks' own bars up to date, one ticker at a time.

    Fair value comes from Bitget's index candle, but the basis against the stock's own
    last traded price, and how old that price is, both come from here. Left alone these
    go stale the moment nobody runs a backfill by hand, which over a two-week judging
    window means the desk quietly stops knowing what the shares did.
    """
    began = utc_now()
    n = 0
    for e in entries:
        try:
            n += sync_equity_bars(store, yahoo, e.yahoo_ticker)
        except Exception as exc:  # noqa: BLE001 - one ticker failing must not stop the rest
            log.warning("equity bars for %s failed: %s", e.yahoo_ticker, exc)
    log.info("equity bars: %d rows across %d tickers", n, len(entries))
    store.log_sync("equity_refresh", rows=n, started_at=began, finished_at=utc_now())
    return n


def sync_news(store: Store, rss: RssNewsClient) -> int:
    began = utc_now()
    n = store.upsert_news(rss.fetch())
    store.log_sync("news", rows=n, started_at=began, finished_at=utc_now())
    return n


# ------------------------------------------------------------------ reporting


def coverage_report(store: Store, entries: Sequence[UniverseEntry]) -> pd.DataFrame:
    rows = []
    for e in entries:
        targets = [(Venue.BITGET_SPOT, e.spot_symbol, PriceKind.TRADE)]
        if e.perp_symbol:
            targets += [(Venue.BITGET_UMCBL, e.perp_symbol, k) for k in (PriceKind.TRADE, PriceKind.INDEX, PriceKind.MARK)]
        targets.append((Venue.YAHOO, e.yahoo_ticker, PriceKind.TRADE))
        for venue, symbol, kind in targets:
            for interval in (Interval.H1, Interval.D1):
                cov = store.bar_coverage(venue, symbol, interval, kind=kind)
                gaps = store.bar_gaps(venue, symbol, interval, kind=kind) if (cov and venue != Venue.YAHOO) else []
                rows.append(
                    {
                        "ticker": e.ticker, "venue": venue.value, "symbol": symbol, "kind": kind.value, "interval": interval.value,
                        "first": cov[0] if cov else None, "last": cov[1] if cov else None, "bars": cov[2] if cov else 0,
                        "gaps": len(gaps), "missing_bars": sum(g[2] for g in gaps),
                    }
                )
    return pd.DataFrame(rows)
