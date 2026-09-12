"""Native US-stock prices from Yahoo Finance's chart endpoint.

Verified 2026-09-12: ``https://query1.finance.yahoo.com/v8/finance/chart/{ticker}``
works without an API key when a browser-like User-Agent is sent. Hourly bars are
available for ~2 years (regular session only unless ``includePrePost``), daily bars
for decades, and the response carries the exchange timezone and trading periods.
The quoteSummary/quote endpoints are *not* usable (crumb auth), so earnings dates
come from Nasdaq instead (see ``nasdaq.py``).

Implementation notes
--------------------
* Timestamps are bar *start* epochs (UTC).
* Arrays contain ``null`` for missing bars; those rows are skipped.
* Requests are chunked to stay inside Yahoo's per-interval range limits.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from nightwatch.data.http import HttpClient, UpstreamError
from nightwatch.data.models import Bar, Interval, PriceKind, Venue
from nightwatch.time_utils import UTC, ensure_utc, utc_now

log = logging.getLogger(__name__)

BASE_URL = "https://query1.finance.yahoo.com"
_INTERVAL = {Interval.M1: "1m", Interval.M5: "5m", Interval.M15: "15m", Interval.H1: "1h", Interval.D1: "1d"}
# Maximum lookback Yahoo serves per interval (conservative) and chunk size per request.
_MAX_LOOKBACK = {
    Interval.M1: timedelta(days=30),
    Interval.M5: timedelta(days=60),
    Interval.M15: timedelta(days=60),
    Interval.H1: timedelta(days=730),
    Interval.D1: timedelta(days=365 * 40),
}
_CHUNK = {
    Interval.M1: timedelta(days=7),
    Interval.M5: timedelta(days=60),
    Interval.M15: timedelta(days=60),
    Interval.H1: timedelta(days=365),
    Interval.D1: timedelta(days=365 * 10),
}
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


class YahooChartClient:
    """Implements ``EquityDataSource``."""

    def __init__(self, http: HttpClient | None = None, *, rate_per_sec: float = 2.0):
        self._http = http or HttpClient(BASE_URL, headers=_HEADERS, rate_per_sec=rate_per_sec, burst=2)

    def close(self) -> None:
        self._http.close()

    def get_bars(
        self,
        ticker: str,
        interval: Interval,
        start: datetime,
        end: datetime,
        *,
        include_pre_post: bool = False,
    ) -> list[Bar]:
        """Bars with ``start <= ts < end``, ascending, de-duplicated."""
        if interval not in _INTERVAL:
            raise ValueError(f"unsupported Yahoo interval {interval}")
        start, end = ensure_utc(start), ensure_utc(end)
        if end <= start:
            return []
        earliest = utc_now() - _MAX_LOOKBACK[interval]
        if start < earliest:
            log.info("yahoo %s %s: clamping start %s -> %s (provider lookback limit)", ticker, interval.value, start, earliest)
            start = earliest
            if end <= start:
                return []

        observed = utc_now()
        by_ts: dict[int, Bar] = {}
        chunk = _CHUNK[interval]
        cursor = start
        while cursor < end:
            chunk_end = min(end, cursor + chunk)
            params = {
                "period1": int(cursor.timestamp()),
                "period2": int(chunk_end.timestamp()),
                "interval": _INTERVAL[interval],
                "includePrePost": "true" if include_pre_post else "false",
                "events": "div,splits",
            }
            try:
                payload = self._http.get_json(f"/v8/finance/chart/{ticker}", params)
            except UpstreamError as exc:
                if exc.status == 400 and "Data doesn't exist" in str(exc):
                    # The window is entirely before the listing date (recent IPOs such as
                    # CRCL). Nothing to fetch here; later chunks may have data.
                    log.info("yahoo %s: no data for %s -> %s (before listing)", ticker, cursor.date(), chunk_end.date())
                    cursor = chunk_end
                    continue
                raise
            for bar in self._parse(payload, ticker, interval, observed):
                if start <= bar.ts < end:
                    by_ts[int(bar.ts.timestamp())] = bar
            cursor = chunk_end
        return [by_ts[k] for k in sorted(by_ts)]

    @staticmethod
    def _parse(payload: Any, ticker: str, interval: Interval, observed: datetime) -> list[Bar]:
        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            raise UpstreamError(f"yahoo {ticker}: {chart['error']}", payload=payload)
        results = chart.get("result") or []
        if not results:
            return []
        r = results[0]
        stamps = r.get("timestamp") or []
        quote = ((r.get("indicators") or {}).get("quote") or [{}])[0]
        opens, highs, lows, closes, vols = (quote.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
        out: list[Bar] = []
        for i, ts in enumerate(stamps):
            try:
                o, h, lo, c = opens[i], highs[i], lows[i], closes[i]
            except IndexError:
                break
            if None in (o, h, lo, c):
                continue
            vol = vols[i] if i < len(vols) else None
            out.append(
                Bar(
                    venue=Venue.YAHOO,
                    symbol=ticker,
                    interval=interval,
                    kind=PriceKind.TRADE,
                    ts=datetime.fromtimestamp(int(ts), tz=UTC),
                    open=float(o),
                    high=float(h),
                    low=float(lo),
                    close=float(c),
                    volume_base=float(vol) if vol is not None else None,
                    volume_quote=None,
                    observed_at=observed,
                )
            )
        return out
