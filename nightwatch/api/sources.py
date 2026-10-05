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


def open_interest_row(cache: dict[str, tuple[datetime, dict | None]]) -> dict[str, Any]:
    """Perp open interest: fetched on demand per token (cached 5 min), so ``last_update``
    is the newest pull and an idle desk legitimately shows an old one."""
    good = {k: (ts, v) for k, (ts, v) in cache.items() if v}
    newest = max((ts for ts, _ in good.values()), default=None)
    failing = sorted(k for k, (_, v) in cache.items() if not v)
    return {
        "key": "bitget_oi", "label": "Bitget perp open interest",
        "what": "Open interest on each token's USDT perpetual, and its change over 24 hours against the desk's own recorded readings",
        "cadence": "on demand, cached 5 min per token", "last_update": newest.isoformat() if newest else None,
        "rows": len(good), "latest": newest.isoformat() if newest else None,
        "latest_label": (f"{len(good)} tokens read" + (f"; {len(failing)} not answering ({', '.join(failing[:3])})" if failing else "")) if cache else "none read yet",
        "url": "https://www.bitget.com/api-doc/contract/market/Get-Open-Interest",
    }


def options_row(cache: dict[str, tuple[datetime, Any]], failed: dict[str, datetime]) -> dict[str, Any]:
    """Cboe option quotes: how many tokens have a chain cached, how many have no listed
    options (an ETF of ETFs, say), and how many pulls are failing."""
    chains = {k: ts for k, (ts, v) in cache.items() if v not in (None, "none")}
    none = sorted(k for k, (_, v) in cache.items() if v == "none")
    newest = max(chains.values(), default=None)
    parts = [f"{len(chains)} tokens with an options chain"]
    if none:
        parts.append(f"{len(none)} with no listed options")
    if failed:
        parts.append(f"{len(failed)} not answering")
    return {
        "key": "cboe_options", "label": "Cboe options quotes",
        "what": "Delayed (about 15 min) option chains for each token's underlying: the at-the-money implied volatility gives the market's expected move over a hold, shown beside the desk's own 1-in-20 loss",
        "cadence": "hourly in the background, cached 30 min per ticker", "last_update": newest.isoformat() if newest else None,
        "rows": len(chains), "latest": newest.isoformat() if newest else None,
        "latest_label": "; ".join(parts) if cache else "none fetched yet",
        "url": "https://www.cboe.com/delayed_quotes/",
    }


def street_row(cached: list[tuple[datetime, Any]], status: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    """The Bitget US-stock data row, honest about an outage.

    Counts only views that hold something (a blank view is a failed or empty pull, not a
    token "with current street data"), and when the service is failing says so, with when
    it started and the HTTP status, instead of calling the cache current.
    """
    from nightwatch.features.street import last_good_label, outage_clause

    held = [(ts, v) for ts, v in cached if v is not None and not v.empty]
    newest = max((ts for ts, _ in held), default=None)
    down = bool(status) and status.get("ok") is False
    if down:
        label = f"Bitget US-stock data: unavailable{outage_clause(status)}"
        if newest:
            label += f"; {len(held)} tokens serve data that is {last_good_label(int((now - newest).total_seconds())).replace('last good ', '')}"
    else:
        label = f"{len(held)} tokens with current street data"
    return {
        "key": "bitget_mcp", "label": "Bitget US-stock data",
        "what": "Live quote for the underlying, analyst ratings and targets, insider trades, market fear & greed (bitget-mcp-server)",
        "cadence": "hourly per token, in memory only", "last_update": newest.isoformat() if newest else None,
        "rows": len(held), "latest": newest.isoformat() if newest else None,
        "latest_label": label, "url": "https://agent.bitget.com/mcp",
        "status": "unavailable" if down else ("ok" if held else "no data yet"),
        "down_since": status.get("down_since") if down else None, "http_status": status.get("http_status") if down else None,
    }


def data_sources(store: Store) -> list[dict[str, Any]]:
    c = store._conn
    last = {task: ms for task, ms in c.execute("SELECT task, MAX(finished_at) FROM sync_log GROUP BY task").fetchall()}
    last_yahoo = _one(store, "SELECT MAX(finished_at) FROM sync_log WHERE task IN ('bars','equity_refresh') AND (venue=? OR task='equity_refresh')", (Venue.YAHOO.value,))
    last_bitget = _one(store, "SELECT MAX(finished_at) FROM sync_log WHERE task IN ('bars','refresh') AND venue<>?", (Venue.YAHOO.value,))

    bars_bitget = _one(store, "SELECT COUNT(*), MAX(ts) FROM bars WHERE venue<>?", (Venue.YAHOO.value,))
    bars_yahoo = _one(store, "SELECT COUNT(*), MAX(ts) FROM bars WHERE venue=?", (Venue.YAHOO.value,))
    # By id, not MAX(ts): the newest snapshot is the last inserted, and MAX(ts) has no index.
    books = _one(store, "SELECT (SELECT COUNT(*) FROM orderbook_snapshots), (SELECT ts FROM orderbook_snapshots ORDER BY id DESC LIMIT 1)")
    earnings = _one(store, "SELECT COUNT(*), MAX(observed_at), MIN(report_date), MAX(report_date) FROM earnings")
    corporate = _one(store, "SELECT COUNT(*), MAX(observed_at), MAX(event_date) FROM corporate_events")
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
        row("corporate", "Dividends and splits", "Ex-dividend dates and splits (Nasdaq, Yahoo Finance) and Bitget exchange notices",
            cadence="every 12 h", last_update=last.get("corporate_events"), rows=int(corporate[0] or 0),
            latest=_iso(corporate[2]) if corporate else None, latest_label="furthest dated event", url="https://www.nasdaq.com/market-activity/dividends"),
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
