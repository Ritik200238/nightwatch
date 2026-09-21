"""Calibration-driven tail adjustment.

The first replays showed a recurring shape: the analog cohort's centre is right, but
its p5/p95 are too close to the median (small samples understate extremes). Rather
than hand-wave, we *measure* how much wider the tails need to be and apply it:

    p5_adj  = p50 + k_lo · (p5  − p50)
    p95_adj = p50 + k_hi · (p95 − p50)

``k_lo`` is the factor at which exactly 5% of realised outcomes fall below ``p5_adj``
on the forecasts used to fit it (coverage is monotone in k, so a bisection finds it);
``k_hi`` likewise for the upper tail.

One factor per window length
----------------------------
A single factor fitted across every horizon is a compromise between them, and the
compromise is not neutral. Measured on 2,278 matured replays, one pooled factor gave:

    overnight (18h)   6.7% of outcomes below p5_adj, band 10.9% wide
    multi-day (66-90h) 0.2% of outcomes below p5_adj, band 20.4% wide

Pooled coverage was 5.4% — apparently on target, but only because a badly over-wide
weekend band cancelled a too-narrow overnight one. Two wrongs averaging to look right
is worse than either wrong alone, because it hides both. Fitting per band moved the
multi-day band to 5.7% breaches at half the width and the overnight band to 6.0%.

Halving the weekend band is not a cosmetic gain: that number feeds the sizing caps and
the gate, so the pooled factor was refusing and shrinking weekend positions against a
loss roughly twice what this token's own history supports.

Honesty rules
-------------
* Factors are fitted only on forecasts whose horizon had *ended* before the point in
  time they are applied at (``horizon_end < as_of``), and require a minimum sample.
* Evaluation is **expanding-window, point-in-time**: for each matured forecast we
  refit on everything matured before it and score the adjusted quantiles on it.
  The reported "adjusted coverage" is therefore fully out-of-sample.
* A band falls back to the pooled factor until it has ``MIN_BAND_N`` matured forecasts
  of its own, so a thin band is never fitted on a handful of observations.
* A factor below 1 is allowed (over-wide forecasts get narrowed) but clamped to a
  sane range so a few outliers cannot produce absurd tails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from nightwatch.journal.calibration import tail_test, wilson_interval
from nightwatch.time_utils import ensure_utc

K_MIN, K_MAX = 0.5, 6.0
MIN_FIT_N = 30

# How many matured forecasts a band needs before it is trusted with its own factor.
# Below this it uses the pooled one, which is wrong in a known direction but is not
# noise. 120 is the point at which the multi-day band's fitted factor stopped moving
# materially between refits on our own history.
MIN_BAND_N = 120

# Window lengths that behave differently enough to need their own factor. The boundary
# sits at 40h because the horizons the desk actually issues are 18h (overnight) and
# 66-90h (a weekend or a long holiday close); nothing lands in between, so the cut is
# reading the data rather than slicing it.
HORIZON_BANDS: tuple[tuple[str, float, float], ...] = (
    ("overnight", 0.0, 40.0),
    ("multi_day", 40.0, float("inf")),
)
POOLED = "pooled"


def horizon_band(hours: float | None) -> str:
    """Which band a horizon belongs to, or ``POOLED`` when it cannot be placed.

    An unknown horizon is not guessed at: it falls back to the pooled factor, which is
    also what happens for a forecast frame that never recorded ``horizon_h``.
    """
    if hours is None:
        return POOLED
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return POOLED
    if not np.isfinite(h):
        return POOLED
    for name, lo, hi in HORIZON_BANDS:
        if lo <= h < hi:
            return name
    return POOLED


@dataclass(frozen=True)
class TailFactors:
    k_lo: float
    k_hi: float
    n_fit: int
    fitted_through: datetime | None  # latest horizon_end used in the fit
    scope: str  # "pooled" | a horizon band | ticker


@dataclass(frozen=True)
class BandedFactors:
    """The factors in force at one instant: one per window length, plus the fallback.

    ``for_hours`` is the whole interface. A caller asks for the horizon it is about to
    report and gets the factor fitted on that kind of window, or the pooled one when
    that band is still too thin to fit.
    """

    pooled: TailFactors | None
    bands: dict[str, TailFactors] = field(default_factory=dict)

    def for_hours(self, hours: float | None) -> TailFactors | None:
        return self.bands.get(horizon_band(hours)) or self.pooled

    @property
    def any(self) -> TailFactors | None:
        """Something to show when no particular horizon is in question."""
        return self.pooled or next(iter(self.bands.values()), None)


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
class BandEvaluation:
    """One window length, scored on its own.

    Reported next to the overall number because the overall number can be on target
    while both halves of it are wrong in opposite directions — which is exactly what
    a single pooled factor produced here before bands existed.
    """

    band: str
    n: int
    raw_lo_coverage: float
    adj_lo_coverage: float
    adj_hi_coverage: float
    raw_width: float
    adj_width: float
    adj_tail_band: str
    k_lo: float
    k_hi: float


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
    bands: list[BandEvaluation] = field(default_factory=list)


def expanding_rows(forecasts: pd.DataFrame, *, min_fit_n: int = MIN_FIT_N, refit_every: int = 25, banded: bool = True) -> pd.DataFrame:
    """Every scorable forecast with the tails that were in force at the time.

    Returned columns: ``as_of``, ``ticker``, ``band``, ``r`` (realised), the stated
    ``p5``/``p95`` and the adjusted ``a5``/``a95``, plus the factors used. Splitting
    this out of the summary lets a walk-forward view group the identical rows by period
    instead of recomputing them differently.

    Each row is adjusted by the factor for *its own* window length once that band has
    ``MIN_BAND_N`` matured forecasts behind it, and by the pooled factor until then.
    A frame without a ``horizon_h`` column has nothing to band on and behaves exactly
    as it did before bands existed.
    """
    df = forecasts.dropna(subset=["p5", "p50", "p95", "ret_pct"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["as_of", "ticker", "band", "r", "p5", "p95", "a5", "a95", "k_lo", "k_hi"])
    df["as_of"] = pd.to_datetime(df["as_of"], utc=True)
    df["horizon_end"] = pd.to_datetime(df["horizon_end"], utc=True)
    df = df.sort_values("as_of").reset_index(drop=True)

    order = np.argsort(df["horizon_end"].to_numpy(), kind="stable")
    ends_sorted = df["horizon_end"].to_numpy()[order]
    p5_h, p50_h, p95_h, r_h = (df[c].to_numpy(float)[order] for c in ("p5", "p50", "p95", "ret_pct"))
    as_ofs = df["as_of"].to_numpy()
    p5_a, p50_a, p95_a, r_a = (df[c].to_numpy(float) for c in ("p5", "p50", "p95", "ret_pct"))
    tickers = df["ticker"].to_numpy() if "ticker" in df else np.array([""] * len(df))
    bands_a = (df["horizon_h"].map(horizon_band).to_numpy() if banded and "horizon_h" in df else np.array([POOLED] * len(df)))
    bands_h = bands_a[order]

    rows = []
    pooled: TailFactors | None = None
    pooled_at = -1
    per_band: dict[str, TailFactors] = {}
    band_at: dict[str, int] = {}
    for i in range(len(df)):
        k = int(np.searchsorted(ends_sorted, as_ofs[i], side="left"))
        if k < min_fit_n:
            continue
        if pooled is None or k - pooled_at >= refit_every:
            pooled = _fit_arrays(p5_h[:k], p50_h[:k], p95_h[:k], r_h[:k], through=pd.Timestamp(ends_sorted[k - 1]).to_pydatetime())
            pooled_at = k
        band = str(bands_a[i])
        use = pooled
        if band != POOLED:
            mask = bands_h[:k] == band
            n_band = int(mask.sum())
            if n_band >= MIN_BAND_N and n_band - band_at.get(band, -refit_every) >= refit_every:
                fitted = _fit_arrays(
                    p5_h[:k][mask], p50_h[:k][mask], p95_h[:k][mask], r_h[:k][mask],
                    through=pd.Timestamp(ends_sorted[:k][mask][-1]).to_pydatetime(), scope=band,
                )
                if fitted is not None:
                    per_band[band], band_at[band] = fitted, n_band
            use = per_band.get(band, pooled)
        if use is None:
            continue
        a5, a95 = apply_factors(p5_a[i], p50_a[i], p95_a[i], use)
        rows.append({"as_of": as_ofs[i], "ticker": tickers[i], "band": use.scope, "r": r_a[i], "p5": p5_a[i], "p95": p95_a[i],
                     "a5": a5, "a95": a95, "k_lo": use.k_lo, "k_hi": use.k_hi})
    return pd.DataFrame(rows)


def evaluate_expanding(forecasts: pd.DataFrame, *, min_fit_n: int = MIN_FIT_N, refit_every: int = 25, banded: bool = True) -> AdjustedEvaluation | None:
    """Point-in-time evaluation: each forecast is scored with factors fitted only on
    forecasts that had matured before its ``as_of``.

    ``refit_every`` is how many newly matured forecasts must arrive before the factors
    are re-solved. It is a production choice as much as a speed one: refitting on every
    single new observation would chase noise. The factors in force are always fitted on
    strictly earlier data, so the evaluation stays out of sample either way.
    """
    e = expanding_rows(forecasts, min_fit_n=min_fit_n, refit_every=refit_every, banded=banded)
    if e.empty:
        return None
    n = len(e)
    raw_lo = float((e["r"] < e["p5"]).mean())
    adj_lo = float((e["r"] < e["a5"]).mean())
    raw_hi = float((e["r"] > e["p95"]).mean())
    adj_hi = float((e["r"] > e["a95"]).mean())
    raw_tail = tail_test(e["r"].to_numpy(float), e["p5"].to_numpy(float)).band
    adj_tail = tail_test(e["r"].to_numpy(float), e["a5"].to_numpy(float)).band
    bands = [
        BandEvaluation(
            band=str(name), n=len(g),
            raw_lo_coverage=float((g["r"] < g["p5"]).mean()), adj_lo_coverage=float((g["r"] < g["a5"]).mean()),
            adj_hi_coverage=float((g["r"] > g["a95"]).mean()),
            raw_width=float((g["p95"] - g["p5"]).mean()), adj_width=float((g["a95"] - g["a5"]).mean()),
            adj_tail_band=tail_test(g["r"].to_numpy(float), g["a5"].to_numpy(float)).band,
            k_lo=float(g["k_lo"].iloc[-1]), k_hi=float(g["k_hi"].iloc[-1]),
        )
        for name, g in e.groupby("band", sort=True)
    ] if "band" in e and e["band"].nunique() > 1 else []
    return AdjustedEvaluation(
        n_evaluated=n, raw_lo_coverage=raw_lo, adj_lo_coverage=adj_lo, raw_hi_coverage=raw_hi, adj_hi_coverage=adj_hi,
        raw_band_coverage=1.0 - raw_lo - raw_hi, adj_band_coverage=1.0 - adj_lo - adj_hi,
        raw_tail_band=raw_tail, adj_tail_band=adj_tail,
        raw_width=float((e["p95"] - e["p5"]).mean()), adj_width=float((e["a95"] - e["a5"]).mean()),
        k_lo_last=float(e["k_lo"].iloc[-1]), k_hi_last=float(e["k_hi"].iloc[-1]),
        lo_ci=wilson_interval(int((e["r"] < e["p5"]).sum()), n), adj_lo_ci=wilson_interval(int((e["r"] < e["a5"]).sum()), n),
        bands=bands,
    )


def factors_as_of(forecasts: pd.DataFrame, as_of: datetime, *, min_fit_n: int = MIN_FIT_N, min_band_n: int = MIN_BAND_N) -> BandedFactors | None:
    """Factors usable at ``as_of``: fitted only on forecasts matured before it.

    One per window length, plus the pooled fallback a thin band borrows until it has
    enough history of its own. The caller picks with ``for_hours``.
    """
    df = forecasts.dropna(subset=["p5", "p50", "p95", "ret_pct"]).copy()
    if df.empty:
        return None
    df["horizon_end"] = pd.to_datetime(df["horizon_end"], utc=True)
    prior = df[df["horizon_end"] < pd.Timestamp(ensure_utc(as_of))]
    if len(prior) < min_fit_n:
        return None
    pooled = fit_factors(prior)
    bands: dict[str, TailFactors] = {}
    if "horizon_h" in prior:
        for name, g in prior.groupby(prior["horizon_h"].map(horizon_band)):
            if name == POOLED or len(g) < min_band_n:
                continue
            fitted = fit_factors(g, scope=str(name))
            if fitted is not None:
                bands[str(name)] = fitted
    if pooled is None and not bands:
        return None
    return BandedFactors(pooled=pooled, bands=bands)
