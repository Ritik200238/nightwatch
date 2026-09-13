"""Calibration as a trend, not a single number.

One coverage figure over two years can hide everything that matters: an engine that was
badly wrong for six months and lucky afterwards scores the same as one that was steady.
This splits the same point-in-time scoring into consecutive periods and reports each on
its own, so the question "is it getting better or worse" has an answer.

Everything here reuses the rows produced for the out-of-sample tail evaluation, so a
period can never be scored by different rules than the headline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from nightwatch.journal.adjust import expanding_rows
from nightwatch.journal.calibration import wilson_interval
from nightwatch.journal.skill import QUANTILES, pinball

MIN_PERIOD_N = 20  # below this a period's coverage is noise; report it but say so


@dataclass(frozen=True)
class PeriodScore:
    label: str
    start: datetime
    end: datetime
    n: int
    thin: bool  # too few forecasts to read much into
    raw_lo_coverage: float
    adj_lo_coverage: float
    raw_band_coverage: float
    adj_band_coverage: float
    raw_width: float
    adj_width: float
    k_lo: float
    k_hi: float
    lo_ci: tuple[float, float]
    skill: float | None  # pinball skill against random same-bucket hours, this period only
    mean_abs_error_p50: float | None


@dataclass(frozen=True)
class WalkForward:
    periods: list[PeriodScore] = field(default_factory=list)
    freq: str = "M"
    n_total: int = 0
    improving: bool | None = None  # is the adjusted band coverage trending towards 90%?
    note: str = ""


def _skill_for(df: pd.DataFrame) -> float | None:
    """Pinball skill of the stated quantiles against the journalled baseline, if present."""
    cols = [q for q, _ in QUANTILES]
    need = [*cols, *[f"base_{q}" for q in cols], "ret_pct"]
    if not all(c in df.columns for c in need):
        return None
    sub = df.dropna(subset=need)
    if len(sub) < MIN_PERIOD_N:
        return None
    y = sub["ret_pct"].to_numpy(float)
    a = sum(pinball(y, sub[q].to_numpy(float), tau).mean() for q, tau in QUANTILES)
    b = sum(pinball(y, sub[f"base_{q}"].to_numpy(float), tau).mean() for q, tau in QUANTILES)
    return float(1 - a / b) if b > 0 else None


def by_period(forecasts: pd.DataFrame, *, freq: str = "M", min_fit_n: int = 30) -> WalkForward:
    """Score the matured forecasts period by period. ``freq`` is a pandas period alias:
    "M" for months, "W" for weeks."""
    rows = expanding_rows(forecasts, min_fit_n=min_fit_n)
    if rows.empty:
        return WalkForward(freq=freq, note="not enough matured forecasts to score out of sample")

    # Periods are wall-clock buckets, so drop the zone after converting rather than
    # letting pandas warn and drop it for us.
    def bucket(series: pd.Series) -> pd.Series:
        return pd.to_datetime(series, utc=True).dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period(freq)

    rows = rows.copy()
    rows["period"] = bucket(rows["as_of"])

    src = forecasts.copy()
    if "as_of" in src:
        src["period"] = bucket(src["as_of"])

    periods: list[PeriodScore] = []
    for period, g in rows.groupby("period", sort=True):
        n = len(g)
        raw_lo = float((g["r"] < g["p5"]).mean())
        adj_lo = float((g["r"] < g["a5"]).mean())
        raw_hi = float((g["r"] > g["p95"]).mean())
        adj_hi = float((g["r"] > g["a95"]).mean())
        same = src[src["period"] == period] if "period" in src else pd.DataFrame()
        mae50 = None
        if not same.empty and "p50" in same and "ret_pct" in same:
            d = same.dropna(subset=["p50", "ret_pct"])
            mae50 = float((d["ret_pct"] - d["p50"]).abs().mean()) if len(d) else None
        periods.append(
            PeriodScore(
                label=str(period), start=period.start_time.tz_localize("UTC"), end=period.end_time.tz_localize("UTC"),
                n=n, thin=n < MIN_PERIOD_N, raw_lo_coverage=raw_lo, adj_lo_coverage=adj_lo,
                raw_band_coverage=1.0 - raw_lo - raw_hi, adj_band_coverage=1.0 - adj_lo - adj_hi,
                raw_width=float((g["p95"] - g["p5"]).mean()), adj_width=float((g["a95"] - g["a5"]).mean()),
                k_lo=float(g["k_lo"].iloc[-1]), k_hi=float(g["k_hi"].iloc[-1]),
                lo_ci=wilson_interval(int((g["r"] < g["a5"]).sum()), n),
                skill=_skill_for(same), mean_abs_error_p50=mae50,
            )
        )

    # "Improving" means the distance from the 90% target is shrinking across periods that
    # are big enough to mean anything. One period cannot answer the question.
    solid = [p for p in periods if not p.thin]
    improving = None
    note = ""
    if len(solid) >= 3:
        gaps = np.array([abs(p.adj_band_coverage - 0.90) for p in solid])
        slope = float(np.polyfit(np.arange(len(gaps)), gaps, 1)[0])
        improving = slope < 0
        note = f"the gap to 90% coverage is {'closing' if improving else 'widening'} by {abs(slope) * 100:.2f} points per period"
    elif solid:
        note = "too few full periods to call a trend"
    return WalkForward(periods=periods, freq=freq, n_total=int(len(rows)), improving=improving, note=note)


def render(wf: WalkForward) -> str:
    if not wf.periods:
        return f"WALK-FORWARD: {wf.note}"
    lines = [f"WALK-FORWARD ({wf.n_total} scored forecasts by period; adjusted tails are out of sample)"]
    lines.append("  period      n    below p5 raw -> adj    inside band raw -> adj   width raw -> adj   skill")
    for p in wf.periods:
        skill = f"{p.skill:+.1%}" if p.skill is not None else "   —"
        thin = " (thin)" if p.thin else ""
        lines.append(
            f"  {p.label:<10} {p.n:>4}    {p.raw_lo_coverage:>6.1%} -> {p.adj_lo_coverage:<6.1%}   "
            f"{p.raw_band_coverage:>6.1%} -> {p.adj_band_coverage:<6.1%}  {p.raw_width:>5.2f} -> {p.adj_width:<5.2f}  {skill}{thin}"
        )
    if wf.note:
        lines.append(f"  {wf.note}")
    return "\n".join(lines)
