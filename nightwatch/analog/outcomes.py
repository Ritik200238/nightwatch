"""What happened after each matched moment.

For a past hour *t* (an analog match) we measure the token's path forward on the same
hourly grid the features were built from. Horizons are both fixed (24h, 72h) and
*structural* — the next US regular open and the end of the closed window — because
for an overnight/weekend holder those are the moments that matter.

Per match we report, for every horizon:
* ``ret_pct``      – spot close-to-close return from *t*
* ``mfe_pct`` / ``mae_pct`` – best / worst excursion of the spot high/low over the window
* ``native_ret_pct`` – return of the carried native close over the same span (what the
  real stock did; ``NaN`` when the stock never printed inside the window)
* ``excess_pct``   – ``ret_pct − native_ret_pct``: the part of the move that is *token
  behaviour*, i.e. the change in basis
* ``max_abs_basis_bps`` – worst |basis vs index| seen inside the window
* ``status``       – ``MATURED`` or ``PENDING`` (window extends past available data)

Outcome tags classify the token path for cohort counting. Thresholds are in bps of
return and are deliberately simple and stated, not tuned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from nightwatch.time_utils import classify_session, ensure_utc

HORIZONS_FIXED_H: tuple[int, ...] = (24, 72)
STRUCTURAL = ("next_open", "window_end")
TAG_STRONG_PCT = 3.0
TAG_MOVE_PCT = 1.0


@dataclass(frozen=True)
class HorizonOutcome:
    horizon: str
    hours: float
    status: str  # MATURED | PENDING
    ret_pct: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    native_ret_pct: float | None = None
    excess_pct: float | None = None
    max_abs_basis_bps: float | None = None
    tag: str | None = None


@dataclass(frozen=True)
class MatchOutcome:
    ts: datetime
    entry_close: float
    outcomes: dict[str, HorizonOutcome] = field(default_factory=dict)

    @property
    def matured(self) -> bool:
        return any(o.status == "MATURED" for o in self.outcomes.values())


def structural_horizons(ts: datetime) -> dict[str, float]:
    """Hours from ``ts`` to the next US regular open and to the end of the current
    closed window (identical when ``ts`` is inside a closed window; when the market is
    open, ``window_end`` is the *next* regular close)."""
    info = classify_session(ts)
    to_open = info.seconds_until_open / 3600.0
    if info.is_closed:
        return {"next_open": to_open, "window_end": to_open}
    to_close = (info.regular_close_utc - ensure_utc(ts)).total_seconds() / 3600.0
    # At the close instant the session is already POST, so the classifier reports the
    # exact time to the next regular open.
    nxt = classify_session(info.regular_close_utc)
    return {"next_open": to_close + nxt.seconds_until_open / 3600.0, "window_end": to_close}


def tag_outcome(ret_pct: float, mfe_pct: float, mae_pct: float) -> str:
    if ret_pct >= TAG_STRONG_PCT:
        return "STRONG_UP"
    if ret_pct >= TAG_MOVE_PCT:
        return "UP"
    if ret_pct <= -TAG_STRONG_PCT:
        return "STRONG_DOWN"
    if ret_pct <= -TAG_MOVE_PCT:
        return "DOWN"
    if mae_pct <= -TAG_STRONG_PCT or mfe_pct >= TAG_STRONG_PCT:
        return "WHIPSAW"
    return "FLAT"


def compute_match_outcomes(
    frame: pd.DataFrame,
    ts: datetime,
    *,
    fixed_h: tuple[int, ...] = HORIZONS_FIXED_H,
    basis_col: str = "basis_index_bps",
) -> MatchOutcome:
    """``frame`` is a feature frame (aligned hourly, with basis columns) covering *ts*
    and, ideally, the horizons after it."""
    ts = ensure_utc(ts)
    t0 = pd.Timestamp(ts)
    if t0 not in frame.index:
        raise KeyError(f"{ts} not in frame")
    entry = float(frame.at[t0, "spot_close"])
    if np.isnan(entry):
        raise ValueError(f"no spot close at {ts}")
    native_entry = frame.at[t0, "native_close"] if "native_close" in frame else np.nan

    horizons: dict[str, float] = {f"{h}h": float(h) for h in fixed_h}
    horizons.update(structural_horizons(ts))

    last_ts = frame.index[-1]
    out: dict[str, HorizonOutcome] = {}
    for name, hours in horizons.items():
        # Target grid point: the first completed bar at or after ts + hours.
        target = (t0 + pd.Timedelta(hours=hours)).ceil("1h")
        if target > last_ts or hours <= 0:
            out[name] = HorizonOutcome(horizon=name, hours=hours, status="PENDING")
            continue
        window = frame.loc[t0 + pd.Timedelta(hours=1): target]
        if window.empty or window["spot_close"].isna().all():
            out[name] = HorizonOutcome(horizon=name, hours=hours, status="PENDING")
            continue
        exit_close = float(window["spot_close"].iloc[-1])
        hi = float(np.nanmax(window["spot_high"].to_numpy(dtype=float)))
        lo = float(np.nanmin(window["spot_low"].to_numpy(dtype=float)))
        ret = (exit_close / entry - 1.0) * 100.0
        mfe = (hi / entry - 1.0) * 100.0
        mae = (lo / entry - 1.0) * 100.0
        native_ret = None
        excess = None
        if "native_close" in window and not np.isnan(native_entry):
            native_exit = window["native_close"].iloc[-1]
            if not np.isnan(native_exit):
                native_ret = (float(native_exit) / float(native_entry) - 1.0) * 100.0
                excess = ret - native_ret
        max_basis = None
        if basis_col in window:
            b = window[basis_col].abs()
            max_basis = None if b.isna().all() else float(b.max())
        out[name] = HorizonOutcome(
            horizon=name, hours=hours, status="MATURED", ret_pct=ret, mfe_pct=mfe, mae_pct=mae,
            native_ret_pct=native_ret, excess_pct=excess, max_abs_basis_bps=max_basis, tag=tag_outcome(ret, mfe, mae),
        )
    return MatchOutcome(ts=ts, entry_close=entry, outcomes=out)


def outcomes_table(match_outcomes: list[MatchOutcome], horizon: str) -> pd.DataFrame:
    rows = []
    for mo in match_outcomes:
        o = mo.outcomes.get(horizon)
        if o is None:
            continue
        rows.append(
            {"ts": mo.ts, "status": o.status, "hours": o.hours, "ret_pct": o.ret_pct, "mfe_pct": o.mfe_pct, "mae_pct": o.mae_pct,
             "native_ret_pct": o.native_ret_pct, "excess_pct": o.excess_pct, "max_abs_basis_bps": o.max_abs_basis_bps, "tag": o.tag}
        )
    return pd.DataFrame(rows).set_index("ts") if rows else pd.DataFrame()
