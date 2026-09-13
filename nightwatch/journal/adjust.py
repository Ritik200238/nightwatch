"""Calibration-driven tail adjustment.

The first replays showed a recurring shape: the analog cohort's centre is right, but
its p5/p95 are too close to the median (small samples understate extremes). Rather
than hand-wave, we *measure* how much wider the tails need to be and apply it:

    p5_adj  = p50 + k_lo · (p5  − p50)
    p95_adj = p50 + k_hi · (p95 − p50)

``k_lo`` is the factor at which exactly 5% of realised outcomes fall below ``p5_adj``
on the forecasts used to fit it (coverage is monotone in k, so a bisection finds it);
``k_hi`` likewise for the upper tail.

Honesty rules
-------------
* Factors are fitted only on forecasts whose horizon had *ended* before the point in
  time they are applied at (``horizon_end < as_of``), and require a minimum sample.
* Evaluation is **expanding-window, point-in-time**: for each matured forecast we
  refit on everything matured before it and score the adjusted quantiles on it.
  The reported "adjusted coverage" is therefore fully out-of-sample.
* A factor below 1 is allowed (over-wide forecasts get narrowed) but clamped to a
  sane range so a few outliers cannot produce absurd tails.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from nightwatch.journal.calibration import tail_test, wilson_interval
from nightwatch.time_utils import ensure_utc

K_MIN, K_MAX = 0.5, 6.0
MIN_FIT_N = 30


@dataclass(frozen=True)
class TailFactors:
    k_lo: float
    k_hi: float
    n_fit: int
    fitted_through: datetime | None  # latest horizon_end used in the fit
    scope: str  # "pooled" | ticker


def _coverage_lo(k: float, p50: np.ndarray, p5: np.ndarray, r: np.ndarray) -> float:
    return float((r < p50 + k * (p5 - p50)).mean())


def _coverage_hi(k: float, p50: np.ndarray, p95: np.ndarray, r: np.ndarray) -> float:
    return float((r > p50 + k * (p95 - p50)).mean())


def _solve(target: float, f, p50, q, r) -> float:  # noqa: ANN001
    """Bisection on k: coverage decreases as k grows (wider tail → fewer breaches)."""
    lo, hi = K_MIN, K_MAX
    if f(hi, p50, q, r) > target:
        return hi
    if f(lo, p50, q, r) < target:
        return lo
    for _ in range(50):
        mid = (lo + hi) / 2
        if f(mid, p50, q, r) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _fit_arrays(p5: np.ndarray, p50: np.ndarray, p95: np.ndarray, r: np.ndarray, *, through: datetime | None = None, scope: str = "pooled", target: float = 0.05) -> TailFactors | None:
    if len(r) < MIN_FIT_N:
        return None
    return TailFactors(
        k_lo=float(_solve(target, _coverage_lo, p50, p5, r)), k_hi=float(_solve(target, _coverage_hi, p50, p95, r)),
        n_fit=int(len(r)), fitted_through=through, scope=scope,
    )


def fit_factors(forecasts: pd.DataFrame, *, scope: str = "pooled", target: float = 0.05) -> TailFactors | None:
    """``forecasts`` = matured rows with p5/p50/p95 and ret_pct."""
    df = forecasts.dropna(subset=["p5", "p50", "p95", "ret_pct"])
    if len(df) < MIN_FIT_N:
        return None
    p50 = df["p50"].to_numpy(float)
    p5 = df["p5"].to_numpy(float)
    p95 = df["p95"].to_numpy(float)
    r = df["ret_pct"].to_numpy(float)
    k_lo = _solve(target, _coverage_lo, p50, p5, r)
    k_hi = _solve(target, _coverage_hi, p50, p95, r)
    through = pd.to_datetime(df["horizon_end"]).max().to_pydatetime() if "horizon_end" in df else None
    return TailFactors(k_lo=float(k_lo), k_hi=float(k_hi), n_fit=int(len(df)), fitted_through=through, scope=scope)


def apply_factors(p5: float | None, p50: float | None, p95: float | None, f: TailFactors) -> tuple[float | None, float | None]:
    if p5 is None or p50 is None or p95 is None:
        return None, None
    return p50 + f.k_lo * (p5 - p50), p50 + f.k_hi * (p95 - p50)


@dataclass(frozen=True)
class AdjustedEvaluation:
    n_evaluated: int
    raw_lo_coverage: float
    adj_lo_coverage: float
    raw_hi_coverage: float
    adj_hi_coverage: float
    raw_band_coverage: float  # share inside [p5, p95]
    adj_band_coverage: float
    raw_tail_band: str
    adj_tail_band: str
    raw_width: float
    adj_width: float
    k_lo_last: float | None
    k_hi_last: float | None
    lo_ci: tuple[float, float]
    adj_lo_ci: tuple[float, float]


def expanding_rows(forecasts: pd.DataFrame, *, min_fit_n: int = MIN_FIT_N, refit_every: int = 25) -> pd.DataFrame:
    """Every scorable forecast with the tails that were in force at the time.

    Returned columns: ``as_of``, ``ticker``, ``r`` (realised), the stated ``p5``/``p95``
    and the adjusted ``a5``/``a95``, plus the factors used. Splitting this out of the
    summary lets a walk-forward view group the identical rows by period instead of
    recomputing them differently.
    """
    df = forecasts.dropna(subset=["p5", "p50", "p95", "ret_pct"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["as_of", "ticker", "r", "p5", "p95", "a5", "a95", "k_lo", "k_hi"])
    df["as_of"] = pd.to_datetime(df["as_of"], utc=True)
    df["horizon_end"] = pd.to_datetime(df["horizon_end"], utc=True)
    df = df.sort_values("as_of").reset_index(drop=True)

    order = np.argsort(df["horizon_end"].to_numpy(), kind="stable")
    ends_sorted = df["horizon_end"].to_numpy()[order]
    p5_h, p50_h, p95_h, r_h = (df[c].to_numpy(float)[order] for c in ("p5", "p50", "p95", "ret_pct"))
    as_ofs = df["as_of"].to_numpy()
    p5_a, p50_a, p95_a, r_a = (df[c].to_numpy(float) for c in ("p5", "p50", "p95", "ret_pct"))
    tickers = df["ticker"].to_numpy() if "ticker" in df else np.array([""] * len(df))

    rows = []
    last: TailFactors | None = None
    fitted_at = -1
    for i in range(len(df)):
        k = int(np.searchsorted(ends_sorted, as_ofs[i], side="left"))
        if k < min_fit_n:
            continue
        if last is None or k - fitted_at >= refit_every:
            last = _fit_arrays(p5_h[:k], p50_h[:k], p95_h[:k], r_h[:k], through=pd.Timestamp(ends_sorted[k - 1]).to_pydatetime())
            fitted_at = k
        if last is None:
            continue
        a5, a95 = apply_factors(p5_a[i], p50_a[i], p95_a[i], last)
        rows.append({"as_of": as_ofs[i], "ticker": tickers[i], "r": r_a[i], "p5": p5_a[i], "p95": p95_a[i],
                     "a5": a5, "a95": a95, "k_lo": last.k_lo, "k_hi": last.k_hi})
    return pd.DataFrame(rows)


def evaluate_expanding(forecasts: pd.DataFrame, *, min_fit_n: int = MIN_FIT_N, refit_every: int = 25) -> AdjustedEvaluation | None:
    """Point-in-time evaluation: each forecast is scored with factors fitted only on
    forecasts that had matured before its ``as_of``.

    ``refit_every`` is how many newly matured forecasts must arrive before the factors
    are re-solved. It is a production choice as much as a speed one: refitting on every
    single new observation would chase noise. The factors in force are always fitted on
    strictly earlier data, so the evaluation stays out of sample either way.
    """
    e = expanding_rows(forecasts, min_fit_n=min_fit_n, refit_every=refit_every)
    if e.empty:
        return None
    n = len(e)
    raw_lo = float((e["r"] < e["p5"]).mean())
    adj_lo = float((e["r"] < e["a5"]).mean())
    raw_hi = float((e["r"] > e["p95"]).mean())
    adj_hi = float((e["r"] > e["a95"]).mean())
    raw_tail = tail_test(e["r"].to_numpy(float), e["p5"].to_numpy(float)).band
    adj_tail = tail_test(e["r"].to_numpy(float), e["a5"].to_numpy(float)).band
    return AdjustedEvaluation(
        n_evaluated=n, raw_lo_coverage=raw_lo, adj_lo_coverage=adj_lo, raw_hi_coverage=raw_hi, adj_hi_coverage=adj_hi,
        raw_band_coverage=1.0 - raw_lo - raw_hi, adj_band_coverage=1.0 - adj_lo - adj_hi,
        raw_tail_band=raw_tail, adj_tail_band=adj_tail,
        raw_width=float((e["p95"] - e["p5"]).mean()), adj_width=float((e["a95"] - e["a5"]).mean()),
        k_lo_last=float(e["k_lo"].iloc[-1]), k_hi_last=float(e["k_hi"].iloc[-1]),
        lo_ci=wilson_interval(int((e["r"] < e["p5"]).sum()), n), adj_lo_ci=wilson_interval(int((e["r"] < e["a5"]).sum()), n),
    )


def factors_as_of(forecasts: pd.DataFrame, as_of: datetime, *, min_fit_n: int = MIN_FIT_N) -> TailFactors | None:
    """Factors usable at ``as_of``: fitted only on forecasts matured before it."""
    df = forecasts.dropna(subset=["p5", "p50", "p95", "ret_pct"]).copy()
    if df.empty:
        return None
    df["horizon_end"] = pd.to_datetime(df["horizon_end"], utc=True)
    prior = df[df["horizon_end"] < pd.Timestamp(ensure_utc(as_of))]
    if len(prior) < min_fit_n:
        return None
    return fit_factors(prior)
