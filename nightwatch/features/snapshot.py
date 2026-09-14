"""Point-in-time feature snapshot and the historical feature matrix.

Both are produced by the *same* pipeline (``compute_feature_frame``) so the vector
describing "now" and the vectors describing every past hour are computed identically —
the analog search is only meaningful if that holds.

A ``FeatureSnapshot`` is:
* built strictly from bars closed by ``as_of`` (and store rows observed by then),
* explicit about data quality (flags a judge can read),
* content-addressed (``content_hash``) so a report can prove which inputs it used.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.data.store import Store
from nightwatch.features.basis import add_basis_columns
from nightwatch.features.events import add_event_columns
from nightwatch.features.macro import MACRO_COLUMNS, build_macro_frame, macro_label
from nightwatch.features.regime import add_regime_columns
from nightwatch.features.series import HOUR, SeriesSpec, completed_before, load_aligned_hourly
from nightwatch.time_utils import ensure_utc, utc_now

# Numeric features that describe a moment. Order matters: it is the vector layout the
# analog engine standardises and searches over.
FEATURE_COLUMNS: tuple[str, ...] = (
    "basis_index_bps",
    "basis_index_z",
    "basis_index_d6h_bps",
    "basis_native_bps",
    "rv_24h",
    "rv_168h",
    "vol_pctl_90d",
    "trend_sma_pct",
    "sma_slope_5d_pct",
    "liq_ratio",
    "no_trade_share_24h",
    "no_trade_excess_24h",
    "native_close_age_h",
    "hours_to_earnings",
    "hours_since_earnings",
    "macro_events_72h",
    "hours_to_fomc",
    "news_count_24h",
    "hours_since_filing",
    "filings_72h",
    *MACRO_COLUMNS,
)
LABEL_COLUMNS: tuple[str, ...] = ("session", "bucket", "vol_state", "trend_state", "liq_state", "regime_label")
# Searched by default. The macro columns earned their place: on 1,605 paired forecasts
# across 20 tokens they cut the mean pinball loss by 1.3% with an interval that excludes
# zero, mostly at the median and the upper tail. The lower tail did not improve, so the
# claim stays narrow. See docs/experiments-macro-features.txt and research/feature_ab.py.
# Filing columns and the no-trade excess are carried and shown but not searched until an
# A/B says they earn it.
SEARCH_COLUMNS: tuple[str, ...] = tuple(c for c in FEATURE_COLUMNS if c not in ("hours_since_filing", "filings_72h", "no_trade_excess_24h"))
HISTORY_DAYS_FOR_SNAPSHOT = 120  # enough for the 90-day vol percentile window


class InsufficientData(ValueError):
    """Raised when a snapshot cannot be built honestly."""


@dataclass(frozen=True)
class FeatureSnapshot:
    ticker: str
    as_of: datetime
    bar_ts: datetime  # open time of the last completed hourly bar used
    features: dict[str, float | None]
    labels: dict[str, str]
    prices: dict[str, float | None]
    quality_flags: list[str] = field(default_factory=list)
    history_hours: int = 0
    content_hash: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        d["bar_ts"] = self.bar_ts.isoformat()
        return d


def compute_feature_frame(store: Store, spec: SeriesSpec, start: datetime, end: datetime, *, as_of: datetime | None = None) -> pd.DataFrame:
    """Aligned frame + basis + regime + events for every hour in [start, end)."""
    f = load_aligned_hourly(store, spec, start, end, as_of=as_of)
    if f.empty or f["spot_close"].isna().all():
        raise InsufficientData(f"no spot bars for {spec.spot_symbol} in [{start}, {end})")
    f = add_basis_columns(f)
    f = add_regime_columns(f)
    f = add_event_columns(f, store, spec.ticker, as_of=as_of)
    # The macro weather is the same for every token at a given hour, so it is joined on
    # rather than derived from the token's own series.
    f = f.join(build_macro_frame(store, f.index))
    return f


STALE_FLAG_H = 6.0  # the token has gone quiet: say so on the report and make the gate ask
STALE_REFUSE_H = 48.0  # nothing usable left; refuse rather than price a two-day-old quote


def quality_flags_for_row(row: pd.Series, frame: pd.DataFrame) -> list[str]:
    flags: list[str] = []
    tail = frame.tail(24)
    if tail["spot_filled"].mean() > 0.25:
        flags.append("spot_no_trade_share_24h_gt_25pct")
    if pd.isna(row.get("index_close")):
        flags.append("index_price_missing")
    if pd.isna(row.get("native_close")):
        flags.append("native_close_missing")
    elif (row.get("native_close_age_h") or 0) > 72:
        flags.append("native_close_older_than_72h")
    if pd.isna(row.get("vol_pctl_90d")):
        flags.append("vol_percentile_needs_more_history")
    if pd.isna(row.get("liq_ratio")):
        flags.append("liquidity_baseline_needs_more_history")
    if pd.isna(row.get("hours_to_earnings")):
        flags.append("no_upcoming_earnings_date")
    return flags


def build_snapshot(store: Store, spec: SeriesSpec, as_of: datetime | None = None) -> FeatureSnapshot:
    as_of = ensure_utc(as_of or utc_now())
    start = as_of - timedelta(days=HISTORY_DAYS_FOR_SNAPSHOT)
    end = as_of.replace(minute=0, second=0, microsecond=0) + HOUR
    frame = compute_feature_frame(store, spec, start, end, as_of=as_of)
    done = completed_before(frame, as_of)
    done = done[done["spot_close"].notna()]
    if done.empty:
        raise InsufficientData(f"no completed bars for {spec.ticker} before {as_of.isoformat()}")
    row = done.iloc[-1]
    bar_ts = done.index[-1].to_pydatetime()
    # Forward-filled hours are not evidence of a live market. Staleness is judged on
    # the last hour that actually traded.
    traded = done[~done["spot_filled"].astype(bool)]
    if traded.empty:
        raise InsufficientData(f"no traded bars for {spec.ticker} before {as_of.isoformat()}")
    last_trade_ts = traded.index[-1].to_pydatetime()
    stale_h = (as_of - last_trade_ts).total_seconds() / 3600.0
    # A token that has not traded for two days has no usable price at all. Short of that,
    # refusing would hide the most useful fact about it: analyse, and flag it loudly. The
    # flag is one the gate blocks on, so a stale name can never pass as a clean GO.
    if stale_h > STALE_REFUSE_H:
        raise InsufficientData(f"{spec.ticker} has not traded since {last_trade_ts.isoformat()}, {stale_h:.0f}h before as_of")

    features = {c: _clean(row.get(c)) for c in FEATURE_COLUMNS}
    labels = {c: str(row.get(c)) for c in LABEL_COLUMNS} | {"macro_label": macro_label(row)}
    prices = {
        "spot_close": _clean(row.get("spot_close")),
        "perp_close": _clean(row.get("perp_close")),
        "index_close": _clean(row.get("index_close")),
        "mark_close": _clean(row.get("mark_close")),
        "native_close": _clean(row.get("native_close")),
    }
    snap = FeatureSnapshot(
        ticker=spec.ticker,
        as_of=as_of,
        bar_ts=bar_ts,
        features=features,
        labels=labels,
        prices=prices,
        quality_flags=quality_flags_for_row(row, done) + ([f"spot_has_not_traded_for_{stale_h:.0f}h"] if stale_h > STALE_FLAG_H else []),
        history_hours=int(done["spot_close"].notna().sum()),
    )
    return FeatureSnapshot(**{**asdict(snap), "content_hash": _hash(snap)})


def _clean(v) -> float | None:  # noqa: ANN001
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(fv) else fv


def _hash(snap: FeatureSnapshot) -> str:
    payload = {
        "ticker": snap.ticker,
        "bar_ts": snap.bar_ts.isoformat(),
        "features": snap.features,
        "labels": snap.labels,
        "prices": snap.prices,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
