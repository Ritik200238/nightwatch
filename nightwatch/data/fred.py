"""Macro data: FRED series (no key) and a scheduled-events calendar.

Two things the product needs from macro data:

1. **Level series** (10-year yield, fed funds, CPI…) for regime features. The
   ``fredgraph.csv`` export works with no API key (verified 2026-09-12).
2. **Scheduled event instants** — when the next CPI / jobs report / FOMC decision
   lands — because event density inside a closed-market window is a core analog feature.
   FRED's release-date API needs a free key; FOMC decisions are not a FRED release at
   all. So this module combines: the FRED releases API when a key is configured, plus
   a built-in schedule of FOMC decision instants (14:00 ET on the second meeting day)
   that must be kept current from the Federal Reserve's published calendar.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta

from nightwatch.data.http import HttpClient, UpstreamError
from nightwatch.data.models import MacroRelease
from nightwatch.time_utils import ET, UTC, ensure_utc, utc_now

log = logging.getLogger(__name__)

GRAPH_URL = "https://fred.stlouisfed.org"
API_URL = "https://api.stlouisfed.org"

# Series we keep for features. Names are ours.
CORE_SERIES: dict[str, str] = {
    "DGS10": "10-year Treasury yield",
    "DGS2": "2-year Treasury yield",
    "DFF": "Effective federal funds rate",
    "T10Y2Y": "10y-2y spread",
    "VIXCLS": "VIX close",
    "DTWEXBGS": "Broad dollar index",
    "CPIAUCSL": "CPI (all urban, SA)",
    "UNRATE": "Unemployment rate",
    "PAYEMS": "Nonfarm payrolls",
}

# FRED release names that move US equities. Used to filter the releases calendar.
KEY_RELEASES: dict[str, str] = {
    "Consumer Price Index": "CPI",
    "Employment Situation": "NFP",
    "Producer Price Index": "PPI",
    "Gross Domestic Product": "GDP",
    "Personal Income and Outlays": "PCE",
    "Advance Monthly Sales for Retail and Food Services": "RETAIL",
    "Advance Retail Sales": "RETAIL",
}

# FOMC decision instants: statement released 14:00 ET on the second meeting day.
# Source: Federal Reserve published meeting calendars. Verify each year when it is
# released and extend here; unknown future years simply yield no events.
FOMC_DECISION_DATES: dict[int, tuple[date, ...]] = {
    2025: (
        date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7), date(2025, 6, 18),
        date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10),
    ),
    2026: (
        date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
        date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
    ),
}
FOMC_STATEMENT_ET_HOUR = 14


def fomc_decisions(start: datetime, end: datetime, observed: datetime | None = None) -> list[MacroRelease]:
    start, end = ensure_utc(start), ensure_utc(end)
    observed = observed or utc_now()
    out: list[MacroRelease] = []
    for year in range(start.year, end.year + 1):
        for d in FOMC_DECISION_DATES.get(year, ()):
            ts = datetime(d.year, d.month, d.day, FOMC_STATEMENT_ET_HOUR, 0, tzinfo=ET).astimezone(UTC)
            if start <= ts < end:
                out.append(
                    MacroRelease(series_id="FOMC", name="FOMC rate decision", release_ts=ts, source="fed_calendar", observed_at=observed)
                )
    return out


class FredClient:
    """Implements ``MacroSource``."""

    def __init__(self, api_key: str | None = None, *, http_graph: HttpClient | None = None, http_api: HttpClient | None = None):
        self.api_key = api_key
        # No custom User-Agent on purpose: FRED's edge silently hangs requests carrying
        # our product UA string (verified 2026-09-12); the client library default works.
        self._graph = http_graph or HttpClient(GRAPH_URL, rate_per_sec=2.0, burst=2, timeout=40.0)
        self._api = http_api or HttpClient(API_URL, rate_per_sec=2.0, burst=2, timeout=40.0)

    def close(self) -> None:
        self._graph.close()
        self._api.close()

    # ------------------------------------------------------------------ series

    def get_series(self, series_id: str, start: datetime, end: datetime) -> list[MacroRelease]:
        """Observations as MacroRelease rows (``release_ts`` = observation date 00:00 UTC).

        Observation dates are *not* publication dates; use ``get_release_calendar`` for
        when the market learned a number. Level series are used for regime features only.
        """
        start, end = ensure_utc(start), ensure_utc(end)
        text = self._graph.get_text("/graph/fredgraph.csv", {"id": series_id})
        observed = utc_now()
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header or len(header) < 2:
            raise UpstreamError(f"fred {series_id}: unexpected CSV header {header!r}")
        name = CORE_SERIES.get(series_id, series_id)
        out: list[MacroRelease] = []
        for row in reader:
            if len(row) < 2:
                continue
            try:
                d = datetime.strptime(row[0], "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                continue
            if not (start <= d < end):
                continue
            value = None if row[1].strip() in ("", ".") else float(row[1])
            out.append(MacroRelease(series_id=series_id, name=name, release_ts=d, value=value, period=row[0], source="fred_csv", observed_at=observed))
        return out

    # ---------------------------------------------------------------- calendar

    def get_release_calendar(self, start: datetime, end: datetime) -> list[MacroRelease]:
        """Scheduled release instants in ``[start, end)``: FOMC (built-in) plus key FRED
        releases when an API key is configured. Release times are 08:30 ET for the
        statistical releases (BLS/BEA/Census standard)."""
        start, end = ensure_utc(start), ensure_utc(end)
        out = fomc_decisions(start, end)
        if not self.api_key:
            log.info("FRED_API_KEY not set: release calendar limited to FOMC decisions")
            return sorted(out, key=lambda m: m.release_ts)

        observed = utc_now()
        payload = self._api.get_json(
            "/fred/releases/dates",
            {
                "api_key": self.api_key,
                "file_type": "json",
                "realtime_start": start.date().isoformat(),
                "realtime_end": (end.date() + timedelta(days=1)).isoformat(),
                "include_release_dates_with_no_data": "true",
                "limit": 1000,
                "sort_order": "asc",
            },
        )
        for r in payload.get("release_dates", []):
            name = str(r.get("release_name", ""))
            code = next((c for key, c in KEY_RELEASES.items() if key.lower() in name.lower()), None)
            if code is None:
                continue
            try:
                d = datetime.strptime(str(r["date"]), "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            ts = datetime(d.year, d.month, d.day, 8, 30, tzinfo=ET).astimezone(UTC)
            if start <= ts < end:
                out.append(MacroRelease(series_id=code, name=name, release_ts=ts, source="fred_releases", observed_at=observed))
        out.sort(key=lambda m: m.release_ts)
        return out
