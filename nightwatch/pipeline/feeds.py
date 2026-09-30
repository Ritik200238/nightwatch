"""Every data feed that fed a report, with how fresh it was.

A report's ``sources`` used to name three things (features, the order book, the stock
MCP). A reader could not tell whether the FRED calendar or the SEC filings had been
consulted, or how stale they were. Each row here is ``{kind, label, last_ts, rows_used}``:
``last_ts`` is the newest thing that feed held as of the analysis (never after it), and
``rows_used`` how many rows in the window the features read from it. A feed with nothing
in it is still listed, with ``rows_used`` 0 and no ``last_ts``, so a gap is visible.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from nightwatch.data.models import Interval, Venue
from nightwatch.data.store import Store
from nightwatch.time_utils import ensure_utc, from_epoch_ms, to_epoch_ms

log = logging.getLogger(__name__)

WINDOW_DAYS = 30


def _row(kind: str, label: str, last_ms: int | None, rows: int, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"kind": kind, "label": label, "last_ts": from_epoch_ms(last_ms).isoformat() if last_ms else None, "rows_used": int(rows or 0), **extra}


def _q(store: Store, sql: str, args: tuple) -> tuple:
    row = store._conn.execute(sql, args).fetchone()  # noqa: SLF001
    return row if row is not None else (0, None)


def _bars(store: Store, venue: Venue, symbol: str, kind: str | None, at_ms: int, lo_ms: int) -> tuple[int, int | None]:
    sql = "SELECT COUNT(*), MAX(ts) FROM bars WHERE venue=? AND symbol=? AND interval=? AND ts<=? AND observed_at<=? "
    args: list[Any] = [venue.value, symbol, Interval.H1.value, at_ms, at_ms]
    if kind:
        sql += "AND kind=? "
        args.append(kind)
    n, last = _q(store, sql + "AND ts>=?", (*args, lo_ms))
    if last is None:  # nothing in the window: still report how old the newest bar is
        _, last = _q(store, sql, tuple(args))
    return int(n or 0), last


def feed_sources(store: Store, *, ticker: str, spot_symbol: str, perp_symbol: str | None, yahoo_ticker: str, as_of: datetime,
                 margin_tier_rows: int | None = None) -> list[dict[str, Any]]:
    """One row per feed, in the order a reader thinks of them."""
    at = ensure_utc(as_of)
    at_ms, lo_ms = to_epoch_ms(at), to_epoch_ms(at - timedelta(days=WINDOW_DAYS))
    out: list[dict[str, Any]] = []
    try:
        n, last = _bars(store, Venue.BITGET_SPOT, spot_symbol, "trade", at_ms, lo_ms)
        out.append(_row("bitget_candles", "Bitget token candles", last, n, symbol=spot_symbol))
        if perp_symbol:
            n, last = _bars(store, Venue.BITGET_UMCBL, perp_symbol, "trade", at_ms, lo_ms)
            fn, flast = _q(store, "SELECT COUNT(*), MAX(ts) FROM funding WHERE venue=? AND symbol=? AND ts<=? AND observed_at<=? AND ts>=?",
                           (Venue.BITGET_UMCBL.value, perp_symbol, at_ms, at_ms, lo_ms))
            newest = max((x for x in (last, flast) if x), default=None)
            out.append(_row("bitget_perp", "Bitget perp candles and funding", newest, n + int(fn or 0), symbol=perp_symbol))
        if margin_tier_rows:
            out.append({"kind": "bitget_margin_tiers", "label": "Bitget margin tiers", "last_ts": None, "rows_used": int(margin_tier_rows), "symbol": perp_symbol})
        n, last = _bars(store, Venue.YAHOO, yahoo_ticker, None, at_ms, lo_ms)
        out.append(_row("yahoo_bars", "Yahoo Finance stock bars", last, n, symbol=yahoo_ticker))
        n, last = _q(store, "SELECT COUNT(*), MAX(observed_at) FROM earnings WHERE ticker=? AND observed_at<=?", (ticker, at_ms))
        out.append(_row("nasdaq_earnings", "Nasdaq earnings calendar", last, n))
        n, _ = _q(store, "SELECT COUNT(*), NULL FROM macro WHERE release_ts BETWEEN ? AND ? AND observed_at<=?",
                  (lo_ms, to_epoch_ms(at + timedelta(days=WINDOW_DAYS)), at_ms))
        _, last = _q(store, "SELECT COUNT(*), MAX(release_ts) FROM macro WHERE release_ts<=? AND observed_at<=?", (at_ms, at_ms))
        out.append(_row("fred_macro", "FRED macro calendar", last, n))
        news = store.get_news(at - timedelta(days=7), at, ticker=ticker, as_of=at)
        out.append(_row("rss_news", "RSS news", to_epoch_ms(max(x.published_at for x in news)) if news else None, len(news)))
        n, _ = _q(store, "SELECT COUNT(*), NULL FROM filings WHERE ticker=? AND accepted_at>=? AND accepted_at<? AND observed_at<=?",
                  (ticker, to_epoch_ms(at - timedelta(hours=72)), at_ms, at_ms))
        _, last = _q(store, "SELECT COUNT(*), MAX(accepted_at) FROM filings WHERE ticker=? AND accepted_at<? AND observed_at<=?", (ticker, at_ms, at_ms))
        out.append(_row("sec_edgar", "SEC EDGAR filings", last, n))
    except Exception:  # noqa: BLE001 - provenance must never fail an analysis
        log.exception("feed provenance failed for %s", ticker)
    return out
