"""Aligned hourly series for one underlying ticker.

The analog engine and the stress presets need every price stream for a ticker on one
complete hourly UTC grid: token spot, perpetual (trade / index / mark) and the native
stock. Each stream has its own irregularities, all handled here explicitly:

* **Bitget omits hours with no trades.** Missing spot/perp hours are forward-filled
  from the previous close and flagged (``spot_filled`` / ``perp_filled``), with quote
  volume set to zero, so downstream code can weight or exclude them.
* **The native stock only trades in the US regular session.** Its last regular-session
  close is carried forward through the closed window, with the age of that close in
  hours (``native_close_age_h``) so features can express "how stale is fair value".
* **Bar timestamps are open times.** A bar is only known once it has *closed*; all
  as-of logic elsewhere uses ``ts + 1h <= as_of``.

Nothing here looks into the future: forward-fills only use earlier bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.data.models import Interval, PriceKind, Venue
from nightwatch.data.store import Store
from nightwatch.time_utils import UTC, Session, classify_session, ensure_utc, hour_of_week_bucket, index_epoch_ns

HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class SeriesSpec:
    ticker: str
    spot_symbol: str
    perp_symbol: str | None
    yahoo_ticker: str


def _hourly_index(start: datetime, end: datetime) -> pd.DatetimeIndex:
    start = ensure_utc(start).replace(minute=0, second=0, microsecond=0)
    end = ensure_utc(end).replace(minute=0, second=0, microsecond=0)
    return pd.date_range(start, end, freq="1h", tz="UTC", inclusive="left", name="ts")


def _reindex_ffill(df: pd.DataFrame, index: pd.DatetimeIndex, prefix: str) -> pd.DataFrame:
    """Reindex a bar frame onto ``index``; forward-fill close, flag filled rows."""
    out = pd.DataFrame(index=index)
    if df.empty:
        out[f"{prefix}_close"] = np.nan
        out[f"{prefix}_high"] = np.nan
        out[f"{prefix}_low"] = np.nan
        out[f"{prefix}_vol_quote"] = 0.0
        out[f"{prefix}_filled"] = True
        return out
    present = df.index.intersection(index)
    aligned = df.reindex(index)
    close = aligned["close"].ffill()
    out[f"{prefix}_close"] = close
    # For filled hours high/low collapse to the carried close (no trading range).
    out[f"{prefix}_high"] = aligned["high"].where(aligned["high"].notna(), close)
    out[f"{prefix}_low"] = aligned["low"].where(aligned["low"].notna(), close)
    out[f"{prefix}_vol_quote"] = aligned["volume_quote"].fillna(0.0) if "volume_quote" in aligned else 0.0
    out[f"{prefix}_filled"] = ~index.isin(present)
    return out


def load_aligned_hourly(
    store: Store,
    spec: SeriesSpec,
    start: datetime,
    end: datetime,
    *,
    as_of: datetime | None = None,
) -> pd.DataFrame:
    """One row per hour in ``[start, end)`` with all streams aligned.

    Columns
    -------
    spot_close/high/low/vol_quote/filled, perp_close/high/low/vol_quote/filled,
    index_close, mark_close, native_close (last completed regular-session bar close,
    carried), native_close_age_h, native_bar_present (a Yahoo bar starts this hour),
    session (Session value), bucket (HourOfWeekBucket value), is_closed (bool).
    """
    index = _hourly_index(start, end)
    frame = pd.DataFrame(index=index)

    spot = store.get_bars(Venue.BITGET_SPOT, spec.spot_symbol, Interval.H1, start, end, as_of=as_of)
    frame = frame.join(_reindex_ffill(spot, index, "spot"))

    if spec.perp_symbol:
        perp = store.get_bars(Venue.BITGET_UMCBL, spec.perp_symbol, Interval.H1, start, end, as_of=as_of)
        frame = frame.join(_reindex_ffill(perp, index, "perp"))
        for kind, col in ((PriceKind.INDEX, "index_close"), (PriceKind.MARK, "mark_close")):
            k = store.get_bars(Venue.BITGET_UMCBL, spec.perp_symbol, Interval.H1, start, end, kind=kind, as_of=as_of)
            frame[col] = k["close"].reindex(index).ffill() if not k.empty else np.nan
    else:
        for col in ("perp_close", "perp_high", "perp_low"):
            frame[col] = np.nan
        frame["perp_vol_quote"] = 0.0
        frame["perp_filled"] = True
        frame["index_close"] = np.nan
        frame["mark_close"] = np.nan

    # Native stock: Yahoo hourly bars start at 13:30/14:30 UTC etc. (not on the hour).
    # A bar that *starts* inside hour h has closed by h+1, so it becomes known at the
    # next grid point. We therefore shift the native series forward by one hour before
    # carrying it, which keeps "native_close" strictly non-anticipative.
    native = store.get_bars(Venue.YAHOO, spec.yahoo_ticker, Interval.H1, start - timedelta(days=7), end, as_of=as_of)
    if native.empty:
        frame["native_close"] = np.nan
        frame["native_close_age_h"] = np.nan
        frame["native_bar_present"] = False
    else:
        # A bar starting 13:30 closes 14:30 and is first usable at the 15:00 grid point.
        known_at = (native.index + HOUR).ceil("1h")
        native_known = pd.Series(native["close"].to_numpy(), index=known_at)
        native_known = native_known[~native_known.index.duplicated(keep="last")].sort_index()
        carried = native_known.reindex(index.union(native_known.index)).ffill().reindex(index)
        frame["native_close"] = carried
        last_known = pd.Series(native_known.index, index=native_known.index)
        last_known = last_known.reindex(index.union(native_known.index)).ffill().reindex(index)
        age = (index - pd.DatetimeIndex(last_known)).total_seconds() / 3600.0
        frame["native_close_age_h"] = age
        frame["native_bar_present"] = index.isin(known_at)

    # Session labelling for every grid point (cached per hour across tickers).
    labels = _session_labels(index)
    frame["session"] = labels["session"].to_numpy()
    frame["bucket"] = labels["bucket"].to_numpy()
    frame["is_closed"] = labels["is_closed"].to_numpy()
    return frame


_LABEL_CACHE: dict[int, tuple[str, str, bool]] = {}


def _session_labels(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Session / bucket / is_closed for each hour, memoised on the epoch-hour so the
    calendar is evaluated once per hour no matter how many tickers are processed."""
    keys = index_epoch_ns(index) // 3_600_000_000_000
    missing = [int(k) for k in np.unique(keys) if int(k) not in _LABEL_CACHE]
    for k in missing:
        ts = datetime.fromtimestamp(k * 3600, tz=UTC)
        info = classify_session(ts)
        _LABEL_CACHE[k] = (info.session.value, hour_of_week_bucket(ts).value, info.is_closed)
    rows = [_LABEL_CACHE[int(k)] for k in keys]
    return pd.DataFrame(rows, columns=["session", "bucket", "is_closed"], index=index)


def completed_before(frame: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    """Rows whose bar had closed by ``as_of`` (ts + 1h <= as_of)."""
    cutoff = ensure_utc(as_of) - HOUR
    return frame.loc[frame.index <= cutoff]


def regular_session_mask(frame: pd.DataFrame) -> pd.Series:
    return frame["session"] == Session.REGULAR.value
