"""Scheduled-event context: earnings proximity, macro density, news flow.

These are the "why might this window be different" features. Earnings and macro
releases are *scheduled*, so their instants were known in advance in reality; for
analog features we treat the whole calendar as known (documented assumption). News
counts are point-in-time through the store's ``as_of`` filter.

Earnings instants: Nasdaq gives a date plus before-open / after-close. We place
before-open at 08:00 ET, after-close at 16:30 ET, unknown at 16:30 ET (the common
case for large caps and the conservative choice: the surprise lands while the US
market is shut, exactly the window this product is about).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.data.models import EarningsEvent, MacroRelease
from nightwatch.data.store import Store
from nightwatch.time_utils import ET, UTC

EARNINGS_TIME_ET = {"bmo": (8, 0), "amc": (16, 30), "unknown": (16, 30), None: (16, 30)}
MACRO_WINDOW_H = 72
NEWS_WINDOW_H = 24
EARNINGS_CAP_H = 24 * 30


def earnings_instant(ev: EarningsEvent) -> datetime:
    d = ev.report_date.astimezone(ET).date()
    hh, mm = EARNINGS_TIME_ET.get(ev.timing, (16, 30))
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET).astimezone(UTC)


def _dedupe_earnings(events: list[EarningsEvent]) -> list[datetime]:
    """One instant per report date; prefer rows that carry a timing."""
    by_date: dict[str, EarningsEvent] = {}
    for ev in events:
        key = ev.report_date.astimezone(ET).date().isoformat()
        cur = by_date.get(key)
        if cur is None or (cur.timing in (None, "unknown") and ev.timing not in (None, "unknown")):
            by_date[key] = ev
    return sorted(earnings_instant(ev) for ev in by_date.values())


def _hours_to_next(index: pd.DatetimeIndex, instants: list[datetime]) -> np.ndarray:
    if not instants:
        return np.full(len(index), np.nan)
    inst = pd.DatetimeIndex(instants).tz_convert("UTC")
    pos = inst.searchsorted(index, side="left")
    out = np.full(len(index), np.nan)
    ok = pos < len(inst)
    out[ok] = (inst[pos[ok]] - index[ok]).total_seconds() / 3600.0
    return out


def _hours_since_last(index: pd.DatetimeIndex, instants: list[datetime]) -> np.ndarray:
    if not instants:
        return np.full(len(index), np.nan)
    inst = pd.DatetimeIndex(instants).tz_convert("UTC")
    pos = inst.searchsorted(index, side="right") - 1
    out = np.full(len(index), np.nan)
    ok = pos >= 0
    out[ok] = (index[ok] - inst[pos[ok]]).total_seconds() / 3600.0
    return out


def _count_within(index: pd.DatetimeIndex, instants: list[datetime], hours: float) -> np.ndarray:
    if not instants:
        return np.zeros(len(index))
    inst = pd.DatetimeIndex(instants).tz_convert("UTC")
    lo = inst.searchsorted(index, side="left")
    hi = inst.searchsorted(index + pd.Timedelta(hours=hours), side="left")
    return (hi - lo).astype(float)


def add_event_columns(
    frame: pd.DataFrame,
    store: Store,
    ticker: str,
    *,
    as_of: datetime | None = None,
    macro_series: tuple[str, ...] = ("FOMC", "CPI", "NFP", "PCE", "GDP", "PPI", "RETAIL"),
) -> pd.DataFrame:
    f = frame.copy()
    index = f.index
    earnings = _dedupe_earnings(store.get_earnings(ticker))
    # Proximity matters inside a month; beyond that the exact number of hours is noise
    # that would dominate a distance metric, so both are capped at 30 days.
    f["hours_to_earnings"] = np.minimum(_hours_to_next(index, earnings), EARNINGS_CAP_H)
    f["hours_since_earnings"] = np.minimum(_hours_since_last(index, earnings), EARNINGS_CAP_H)
    f["earnings_within_72h"] = (f["hours_to_earnings"] <= 72).astype(float)

    lo = index[0].to_pydatetime() - timedelta(days=30)
    hi = index[-1].to_pydatetime() + timedelta(days=30)
    macro: list[MacroRelease] = store.get_macro(lo, hi, series=list(macro_series))
    macro_instants = sorted(m.release_ts for m in macro)
    fomc_instants = sorted(m.release_ts for m in macro if m.series_id == "FOMC")
    f["macro_events_72h"] = _count_within(index, macro_instants, MACRO_WINDOW_H)
    f["hours_to_fomc"] = _hours_to_next(index, fomc_instants)

    news = store.get_news(index[0].to_pydatetime() - timedelta(hours=NEWS_WINDOW_H), index[-1].to_pydatetime() + timedelta(hours=1), ticker=ticker, as_of=as_of)
    news_instants = sorted(n.published_at for n in news)
    # Count of tagged headlines in the trailing 24h: count(<= t) - count(<= t-24h).
    if news_instants:
        inst = pd.DatetimeIndex(news_instants).tz_convert("UTC")
        upto = inst.searchsorted(index, side="right")
        before = inst.searchsorted(index - pd.Timedelta(hours=NEWS_WINDOW_H), side="right")
        f["news_count_24h"] = (upto - before).astype(float)
    else:
        f["news_count_24h"] = 0.0
    return f
