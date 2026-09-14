"""What the desk reads, and how fresh each feed is right now.

One row per upstream source. ``last_update`` is when we last pulled it (the sync log);
``latest`` is the newest thing in it, which is the number a person actually wants:
"is the news feed an hour behind, or a week?"
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nightwatch.data.models import Venue
from nightwatch.data.store import Store


def _iso(ms: int | float | None) -> str | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _one(store: Store, sql: str, args: tuple = ()) -> tuple:
    row = store._conn.execute(sql, args).fetchone()
    return row if row is not None else ()


def data_sources(store: Store) -> list[dict[str, Any]]:
    c = store._conn
    last = {task: ms for task, ms in c.execute("SELECT task, MAX(finished_at) FROM sync_log GROUP BY task").fetchall()}
    last_yahoo = _one(store, "SELECT MAX(finished_at) FROM sync_log WHERE task IN ('bars','equity_refresh') AND (venue=? OR task='equity_refresh')", (Venue.YAHOO.value,))
    last_bitget = _one(store, "SELECT MAX(finished_at) FROM sync_log WHERE task IN ('bars','refresh') AND venue<>?", (Venue.YAHOO.value,))

    bars_bitget = _one(store, "SELECT COUNT(*), MAX(ts) FROM bars WHERE venue<>?", (Venue.YAHOO.value,))
    bars_yahoo = _one(store, "SELECT COUNT(*), MAX(ts) FROM bars WHERE venue=?", (Venue.YAHOO.value,))
    books = _one(store, "SELECT COUNT(*), MAX(ts) FROM orderbook_snapshots")
    earnings = _one(store, "SELECT COUNT(*), MAX(observed_at), MIN(report_date), MAX(report_date) FROM earnings")
    macro = _one(store, "SELECT COUNT(*), MAX(observed_at), MAX(release_ts) FROM macro")
    news = _one(store, "SELECT COUNT(*), MAX(published_at) FROM news")
    filings = _one(store, "SELECT COUNT(*), MAX(accepted_at), COUNT(DISTINCT ticker) FROM filings")
    latest_filing = _one(store, "SELECT ticker, form, accepted_at, items FROM filings ORDER BY accepted_at DESC LIMIT 1")
    latest_news = _one(store, "SELECT title, published_at FROM news ORDER BY published_at DESC LIMIT 1")

    def row(key: str, label: str, what: str, *, cadence: str, last_update: int | None, rows: int, latest: str | None, latest_label: str | None = None, url: str) -> dict[str, Any]:
        return {"key": key, "label": label, "what": what, "cadence": cadence, "last_update": _iso(last_update), "rows": rows, "latest": latest, "latest_label": latest_label, "url": url}

    return [
        row("bitget_bars", "Bitget", "Token and perp candles, order books, funding",
            cadence="books every 30 s, candles every 5 min", last_update=last_bitget[0] if last_bitget else None, rows=int(bars_bitget[0] or 0),
            latest=_iso(max(x for x in (bars_bitget[1], books[1]) if x) if (bars_bitget[1] or books[1]) else None), latest_label=f"{int(books[0] or 0):,} order-book snapshots", url="https://www.bitget.com"),
        row("yahoo", "Yahoo Finance", "The native US stock's own hourly bars, for fair value and basis",
            cadence="hourly while the US market is open", last_update=last_yahoo[0] if last_yahoo else None, rows=int(bars_yahoo[0] or 0), latest=_iso(bars_yahoo[1]), url="https://finance.yahoo.com"),
        row("nasdaq", "Nasdaq", "Earnings calendar: dates, before/after the bell, estimates and actuals",
            cadence="every 6 h", last_update=last.get("earnings_calendar"), rows=int(earnings[0] or 0),
            latest=_iso(earnings[3]) if earnings else None, latest_label="furthest scheduled report", url="https://www.nasdaq.com/market-activity/earnings"),
        row("fred", "FRED", "FOMC, CPI, jobs and other release times; VIX, curve, dollar, 10-year",
            cadence="every 6 h", last_update=max(x for x in (last.get("macro_calendar"), last.get("macro_series")) if x) if (last.get("macro_calendar") or last.get("macro_series")) else None,
            rows=int(macro[0] or 0), latest=_iso(macro[2]) if macro else None, latest_label="furthest scheduled release", url="https://fred.stlouisfed.org"),
        row("rss", "News (RSS)", "Headlines tagged by ticker, for the second opinion",
            cadence="every 30 min", last_update=last.get("news"), rows=int(news[0] or 0), latest=_iso(news[1]) if news else None,
            latest_label=(latest_news[0][:90] if latest_news else None), url="https://feeds.a.dj.com"),
        row("sec_edgar", "SEC EDGAR", "8-K, 6-K, 10-Q and 10-K filings, timed to the second they were accepted",
            cadence="every 4 h", last_update=last.get("filings"), rows=int(filings[0] or 0), latest=_iso(filings[1]) if filings else None,
            latest_label=(f"{latest_filing[0]} {latest_filing[1]}" + (f" items {latest_filing[3]}" if latest_filing[3] else "")) if latest_filing else None,
            url="https://www.sec.gov/edgar"),
    ]
