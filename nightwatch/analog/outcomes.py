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
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.time_utils import Session, classify_session, ensure_utc

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


def hours_through_weekend(ts: datetime) -> float:
    """Hours from ``ts`` to the first US regular open after the coming weekend.

    "Hold it through the weekend" said on a Thursday means until Monday's open, not
    Thursday's - which is what "next open" would give. From Friday evening, Saturday or
    Sunday the two agree. Holidays come from the session calendar, so a long weekend runs
    to Tuesday.
    """
    now = ensure_utc(ts)
    days_to_saturday = (5 - now.weekday()) % 7
    if now.weekday() == 6:  # Sunday: this weekend is already under way
        days_to_saturday = -1
    saturday = (now + timedelta(days=days_to_saturday)).date()
    at = now
    for _ in range(10):  # a week of sessions is more than enough to get past a weekend
        opens = at + timedelta(hours=structural_horizons(at)["next_open"])
        if opens.date() > saturday:
            return (opens - now).total_seconds() / 3600.0
        at = opens + timedelta(minutes=5)  # inside that session, so the next open is the following one
    return structural_horizons(now)["next_open"]


def coming_weekend_hours(ts: datetime) -> tuple[float, datetime]:
    """The length of the coming weekend as a hold - the last regular close of this week to
    the first regular open after it - and the instant that close happens.

    "Over the weekend" said on a Monday means buying on Friday, not holding the whole
    week: from Monday that would be a 173 hour hold, longer than any the desk has scored.
    A holiday Friday moves the close to Thursday, as the calendar says. From Friday itself
    (or later) the weekend is the one under way, which is ``hours_through_weekend``'s."""
    from nightwatch.time_utils import ET, _regular_bounds, is_trading_day, previous_trading_day

    now = ensure_utc(ts)
    friday = now.astimezone(ET).date() + timedelta(days=(4 - now.astimezone(ET).weekday()) % 7)
    if not is_trading_day(friday):
        friday = previous_trading_day(friday)
    close = _regular_bounds(friday)[1]
    return structural_horizons(close)["next_open"], close


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


WEEKEND_H = 40.0  # a closed window longer than this is a weekend or a holiday


def closed_windows(frame: pd.DataFrame) -> pd.DataFrame:
    """Every closed window: when it started, how long it lasted, and the token's move
    from the last regular close to the first regular price after it."""
    f = frame[["spot_close", "session"]].dropna(subset=["spot_close"])
    rows, start, last_close, in_closed = [], None, None, False
    for ts, close, session in zip(f.index, f["spot_close"].to_numpy(float), f["session"].to_numpy(), strict=True):
        if session == Session.REGULAR.value:
            if in_closed and last_close is not None and start is not None:
                rows.append({"start": start, "hours": (ts - start).total_seconds() / 3600.0, "ret_pct": (close / last_close - 1.0) * 100.0})
            in_closed, last_close = False, close
        elif not in_closed:
            in_closed, start = True, ts
    return pd.DataFrame(rows)


def weekend_windows(w: pd.DataFrame) -> pd.DataFrame:
    """The closed windows that are weekends: a long closure that starts on a Friday. A
    Thanksgiving Wednesday night also runs past 40 hours and is not what "over the weekend"
    means. One definition, so every "n weekends" the desk quotes counts the same ones."""
    if w.empty:
        return w
    starts = pd.DatetimeIndex(w["start"])
    starts = starts.tz_localize("UTC") if starts.tz is None else starts
    return w[(w["hours"] >= WEEKEND_H) & (starts.tz_convert("America/New_York").weekday == 4)]


def weekend_history(frame: pd.DataFrame, side: str) -> dict[str, float | int | str] | None:
    """What past weekends did to this token, Friday's close to Monday's first regular price.

    The answer to "over the weekend" asked early in the week, when holding from now would
    be a six-day trade and the trader almost always means buying on Friday. Unconditional
    and raw: every weekend in the stored history, none of them selected to look like now,
    and no calibration applied.
    """
    w = closed_windows(frame)
    if w.empty:
        return None
    w = weekend_windows(w)
    if len(w) < 10:
        return None
    signed = w["ret_pct"].to_numpy(float) * (1.0 if side == "long" else -1.0)
    return {
        "n": int(len(w)), "since": w["start"].min().isoformat(),
        "p5_pct": float(np.percentile(signed, 5)), "median_pct": float(np.median(signed)),
        "worst_pct": float(signed.min()), "typical_h": float(w["hours"].median()),
    }
