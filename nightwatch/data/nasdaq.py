"""Earnings dates from Nasdaq's public calendar API.

Verified 2026-09-12 (no key, browser headers required):

* ``/api/calendar/earnings?date=YYYY-MM-DD`` — all companies reporting that day, with
  ``time`` (``time-pre-market`` / ``time-after-hours`` / ``time-not-supplied``),
  consensus EPS forecast, number of estimates, fiscal quarter ending, last year's
  report date and EPS.
* ``/api/company/{symbol}/earnings-surprise`` — historical reported dates with actual
  EPS, consensus and % surprise.

Report dates are US calendar dates; we store them as the 00:00 ET instant. Callers
combine ``timing`` with the session calendar to place the event before or after the
regular session.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from nightwatch.data.http import HttpClient
from nightwatch.data.models import EarningsEvent
from nightwatch.time_utils import ET, UTC, ensure_utc, utc_now

log = logging.getLogger(__name__)

BASE_URL = "https://api.nasdaq.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
_TIMING = {
    "time-pre-market": "bmo",
    "time-after-hours": "amc",
    "time-not-supplied": "unknown",
}
_MONEY = re.compile(r"[^0-9.\-]")


def _money(value: Any) -> float | None:
    """Parse ``$1.20``, ``-0.5``, ``(0.05)`` (accounting negative), ``N/A`` -> float/None."""
    if value is None:
        return None
    raw = str(value).strip()
    negative = raw.startswith("(") and raw.endswith(")")
    s = _MONEY.sub("", raw)
    if s in ("", "-", "."):
        return None
    try:
        num = float(s)
    except ValueError:
        return None
    return -abs(num) if negative else num


def _et_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=ET).astimezone(UTC)


def _parse_us_date(s: str) -> date | None:
    """Accepts ``M/D/YYYY`` and ``YYYY-MM-DD``."""
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class NasdaqEarningsClient:
    """Implements ``EarningsSource``."""

    def __init__(self, http: HttpClient | None = None, *, rate_per_sec: float = 2.0):
        self._http = http or HttpClient(BASE_URL, headers=_HEADERS, rate_per_sec=rate_per_sec, burst=2)

    def close(self) -> None:
        self._http.close()

    def get_calendar(self, start: datetime, end: datetime) -> list[EarningsEvent]:
        """One request per calendar day in ``[start, end)`` (ET dates)."""
        start_d = ensure_utc(start).astimezone(ET).date()
        end_d = ensure_utc(end).astimezone(ET).date()
        observed = utc_now()
        out: list[EarningsEvent] = []
        d = start_d
        while d < end_d:
            payload = self._http.get_json("/api/calendar/earnings", {"date": d.isoformat()})
            rows = ((payload or {}).get("data") or {}).get("rows") or []
            for r in rows:
                symbol = str(r.get("symbol", "")).upper().strip()
                if not symbol:
                    continue
                out.append(
                    EarningsEvent(
                        ticker=symbol,
                        report_date=_et_midnight(d),
                        timing=_TIMING.get(str(r.get("time", "")), "unknown"),
                        eps_estimate=_money(r.get("epsForecast")),
                        fiscal_quarter_end=(r.get("fiscalQuarterEnding") or None),
                        source="nasdaq_calendar",
                        observed_at=observed,
                    )
                )
            d += timedelta(days=1)
        return out

    def get_history(self, ticker: str) -> list[EarningsEvent]:
        payload = self._http.get_json(f"/api/company/{ticker.lower()}/earnings-surprise")
        data = (payload or {}).get("data") or {}
        table = (data.get("earningsSurpriseTable") or {}).get("rows") or []
        observed = utc_now()
        out: list[EarningsEvent] = []
        for r in table:
            d = _parse_us_date(str(r.get("dateReported", "")))
            if d is None:
                continue
            out.append(
                EarningsEvent(
                    ticker=ticker.upper(),
                    report_date=_et_midnight(d),
                    timing=None,
                    eps_estimate=_money(r.get("consensusForecast")),
                    eps_actual=_money(r.get("eps")),
                    surprise_pct=_money(r.get("percentageSurprise")),
                    fiscal_quarter_end=(r.get("fiscalQtrEnd") or None),
                    source="nasdaq_history",
                    observed_at=observed,
                )
            )
        out.sort(key=lambda e: e.report_date)
        return out

    def get_next_report(self, ticker: str, *, horizon_days: int = 120) -> EarningsEvent | None:
        """Scan the forward calendar for ``ticker``. Cheap enough for a handful of names;
        ``sync`` caches the whole calendar so the engine never calls this directly."""
        today = utc_now()
        for ev in self.get_calendar(today, today + timedelta(days=horizon_days)):
            if ev.ticker == ticker.upper():
                return ev
        return None
