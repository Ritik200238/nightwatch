"""The world the token is trading in.

Everything else in the feature set describes one token: its volatility, its gap to fair
value, its liquidity. None of it knows whether the whole market was calm or falling
apart. These columns add that: the level of implied volatility, the shape of the yield
curve and the direction of the dollar, each as a position within its own recent range so
that a number is comparable across years.

Two rules of discipline:

* **Published, not observed.** A FRED series dated a given day is not usable during that
  day. Every value is held back until the following midnight UTC, which is later than
  the real publication time and therefore never optimistic.
* **Percentiles, not levels.** A VIX of 20 meant something different in 2021 and 2026,
  and a level would let the distance metric match on the year rather than the weather.
  Each column is the value's rank within a trailing window, expanding until the window
  is full so early history is usable rather than blank.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.data.store import Store

# Series that exist daily back to 2015, which is what the analog search needs.
VIX = "VIXCLS"
CURVE = "T10Y2Y"
DOLLAR = "DTWEXBGS"
TEN_YEAR = "DGS10"

MACRO_COLUMNS: tuple[str, ...] = ("vix_pctl_1y", "curve_pctl_1y", "dollar_20d_chg_pct", "ten_year_20d_chg_bps")
PUBLICATION_LAG = timedelta(days=1)  # a value dated D is used from D+1 00:00 UTC
RANK_WINDOW_D = 365
MIN_RANK_OBS = 60


def _series(store: Store, series_id: str, start: datetime, end: datetime) -> pd.Series:
    """One FRED series as a daily series indexed by the instant it becomes usable."""
    rows = store.get_macro(start - timedelta(days=RANK_WINDOW_D + 30), end, series=[series_id])
    pairs = [(r.release_ts, r.value) for r in rows if r.series_id == series_id and r.value is not None]
    if not pairs:
        return pd.Series(dtype="float64")
    s = pd.Series({pd.Timestamp(ts).tz_convert("UTC") + PUBLICATION_LAG: v for ts, v in pairs}).sort_index()
    return s[~s.index.duplicated(keep="last")]


def _rolling_rank(s: pd.Series, window_days: int = RANK_WINDOW_D, min_obs: int = MIN_RANK_OBS) -> pd.Series:
    """Where each value sits in its own trailing window, 0 to 100.

    Expanding until the window has enough observations, so the first year of history is
    scored against what was known then rather than thrown away.
    """
    if s.empty:
        return s
    out = s.rolling(f"{window_days}D", min_periods=min_obs).apply(lambda w: (w[-1] >= w).mean() * 100.0, raw=True)
    return out


def build_macro_frame(store: Store, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Macro columns aligned onto an hourly index, forward-filled from the last usable value."""
    if len(index) == 0:
        return pd.DataFrame(index=index, columns=list(MACRO_COLUMNS), dtype="float64")
    start = index[0].to_pydatetime()
    end = index[-1].to_pydatetime() + timedelta(days=1)

    vix, curve, dollar, ten = (_series(store, sid, start, end) for sid in (VIX, CURVE, DOLLAR, TEN_YEAR))
    out = pd.DataFrame(index=index, dtype="float64")

    def align(s: pd.Series) -> pd.Series:
        return s.reindex(s.index.union(index)).ffill().reindex(index) if not s.empty else pd.Series(np.nan, index=index)

    out["vix_pctl_1y"] = align(_rolling_rank(vix))
    out["curve_pctl_1y"] = align(_rolling_rank(curve))
    # Momentum, not level: a rising dollar and rising yields are the risk-off combination.
    out["dollar_20d_chg_pct"] = align(dollar.pct_change(20) * 100.0 if not dollar.empty else dollar)
    out["ten_year_20d_chg_bps"] = align(ten.diff(20) * 100.0 if not ten.empty else ten)
    return out[list(MACRO_COLUMNS)]


def macro_label(row: pd.Series) -> str:
    """A word for the macro weather, for the report to show. Never used as a feature."""
    vix = row.get("vix_pctl_1y")
    dollar = row.get("dollar_20d_chg_pct")
    ten = row.get("ten_year_20d_chg_bps")
    if vix is None or pd.isna(vix):
        return "unknown"
    tightening = (dollar is not None and not pd.isna(dollar) and dollar > 1.0) or (ten is not None and not pd.isna(ten) and ten > 25)
    if vix >= 80:
        return "stressed"
    if vix >= 60 or tightening:
        return "tightening"
    if vix <= 25:
        return "calm"
    return "ordinary"
