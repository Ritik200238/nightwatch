"""Calibration: did the forecast distributions match what happened?

For every matured forecast we know the predicted quantiles (p5 … p95) and the realised
return. If the forecasts are honest, 5% of realisations fall below p5, 50% below p50,
90% inside [p5, p95]. We report:

* **Coverage** at each quantile with a binomial 95% interval around the observed share.
* **PIT histogram** – where each realisation landed among the predicted quantiles
  (uniform if calibrated; bunched in the tails if the forecasts are too narrow).
* **Tail tests** on the 5% loss tail (the number a risk manager cares about):
  - proportion-of-failures likelihood-ratio test (does the breach *rate* match 5%?),
  - independence likelihood-ratio test (do breaches cluster?),
  - the combined conditional-coverage statistic,
  - a three-band verdict (green / amber / red) from the breach count.
* **Sharpness** – mean predicted p5–p95 width; a calibrated but useless forecast is
  wide, a useful one is narrow *and* calibrated.

All statistics are derived from first principles (likelihood ratios against binomial
and two-state Markov null models) and tested against hand-computed cases.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

QUANTILES = ("p5", "p25", "p50", "p75", "p95")
NOMINAL = {"p5": 0.05, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p95": 0.95}


@dataclass(frozen=True)
class Coverage:
    quantile: str
    nominal: float
    observed: float
    n: int
    ci_low: float
    ci_high: float
    within_ci: bool


@dataclass(frozen=True)
class TailTest:
    n: int
    breaches: int
    expected_rate: float
    observed_rate: float
    pof_stat: float | None
    pof_p_value: float | None
    independence_stat: float | None
    independence_p_value: float | None
    conditional_stat: float | None
    conditional_p_value: float | None
    band: str  # green | amber | red | insufficient


@dataclass(frozen=True)
class CalibrationReport:
    n_matured: int
    coverage: list[Coverage]
    tail: TailTest
    pit_histogram: dict[str, int]
    mean_width_p5_p95: float | None
    mean_abs_error_p50: float | None
    by_ticker: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------- statistics


def _chi2_sf(x: float, df: int) -> float:
    """Survival function of the chi-square distribution for df in {1, 2} (closed forms)."""
    if x <= 0:
        return 1.0
    if df == 1:
        return math.erfc(math.sqrt(x / 2.0))
    if df == 2:
        return math.exp(-x / 2.0)
    raise ValueError("only df 1 and 2 are needed here")


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def proportion_of_failures(breaches: np.ndarray, expected_rate: float) -> tuple[float | None, float | None]:
    """Likelihood ratio of the observed breach rate against the expected rate (df=1)."""
    n = int(breaches.size)
    x = int(breaches.sum())
    if n == 0:
        return None, None
    p = expected_rate
    if x == 0:
        ll0 = n * math.log(1 - p)
        ll1 = 0.0
    elif x == n:
        ll0 = n * math.log(p)
        ll1 = 0.0
    else:
        ph = x / n
        ll0 = x * math.log(p) + (n - x) * math.log(1 - p)
        ll1 = x * math.log(ph) + (n - x) * math.log(1 - ph)
    stat = -2.0 * (ll0 - ll1)
    return stat, _chi2_sf(stat, 1)


def independence_test(breaches: np.ndarray) -> tuple[float | None, float | None]:
    """Likelihood ratio that breaches follow a two-state Markov chain versus being
    independent (df=1). Clustered breaches reject independence."""
    b = breaches.astype(int)
    if b.size < 2:
        return None, None
    prev, cur = b[:-1], b[1:]
    n00 = int(((prev == 0) & (cur == 0)).sum())
    n01 = int(((prev == 0) & (cur == 1)).sum())
    n10 = int(((prev == 1) & (cur == 0)).sum())
    n11 = int(((prev == 1) & (cur == 1)).sum())
    if (n01 + n11) == 0 or (n00 + n10) == 0:
        return 0.0, 1.0
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)

    def _ll(p: float, k: int, m: int) -> float:
        if p <= 0.0 or p >= 1.0:
            return 0.0 if (k == 0 or m == 0) else float("-inf")
        return k * math.log(1 - p) + m * math.log(p)

    ll_ind = _ll(pi, n00 + n10, n01 + n11)
    ll_markov = _ll(pi01, n00, n01) + _ll(pi11, n10, n11)
    if not math.isfinite(ll_ind) or not math.isfinite(ll_markov):
        return 0.0, 1.0
    stat = -2.0 * (ll_ind - ll_markov)
    stat = max(stat, 0.0)
    return stat, _chi2_sf(stat, 1)


def tail_test(realised: np.ndarray, p5: np.ndarray, expected_rate: float = 0.05) -> TailTest:
    mask = ~(np.isnan(realised) | np.isnan(p5))
    r, q = realised[mask], p5[mask]
    n = int(r.size)
    breaches = (r < q).astype(int)
    x = int(breaches.sum())
    if n < 20:
        return TailTest(n, x, expected_rate, x / n if n else float("nan"), None, None, None, None, None, None, "insufficient")
    pof_stat, pof_p = proportion_of_failures(breaches, expected_rate)
    ind_stat, ind_p = independence_test(breaches)
    cc_stat = cc_p = None
    if pof_stat is not None and ind_stat is not None:
        cc_stat = pof_stat + ind_stat
        cc_p = _chi2_sf(cc_stat, 2)
    # Three-band verdict on the breach count relative to expectation (binomial tails).
    expected = n * expected_rate
    sd = math.sqrt(n * expected_rate * (1 - expected_rate))
    z = (x - expected) / sd if sd > 0 else 0.0
    band = "green" if z <= 1.0 else ("amber" if z <= 2.5 else "red")
    return TailTest(n, x, expected_rate, x / n, pof_stat, pof_p, ind_stat, ind_p, cc_stat, cc_p, band)


def pit_bucket(realised: float, row: pd.Series) -> str:
    qs = [row.get(q) for q in QUANTILES]
    if any(q is None or (isinstance(q, float) and np.isnan(q)) for q in qs):
        return "unknown"
    if realised < qs[0]:
        return "<p5"
    if realised < qs[1]:
        return "p5-p25"
    if realised < qs[2]:
        return "p25-p50"
    if realised < qs[3]:
        return "p50-p75"
    if realised < qs[4]:
        return "p75-p95"
    return ">p95"


def calibrate(forecasts: pd.DataFrame) -> CalibrationReport:
    """``forecasts`` = Journal.forecasts(matured_only=True)."""
    df = forecasts.dropna(subset=["ret_pct"]).copy()
    n = len(df)
    coverage: list[Coverage] = []
    for q in QUANTILES:
        sub = df.dropna(subset=[q])
        m = len(sub)
        k = int((sub["ret_pct"] < sub[q]).sum())
        lo, hi = wilson_interval(k, m)
        nominal = NOMINAL[q]
        coverage.append(Coverage(q, nominal, k / m if m else float("nan"), m, lo, hi, lo <= nominal <= hi if m else False))
    tail = tail_test(df["ret_pct"].to_numpy(dtype=float), df["p5"].to_numpy(dtype=float)) if n else TailTest(0, 0, 0.05, float("nan"), None, None, None, None, None, None, "insufficient")
    hist: dict[str, int] = {}
    for _, row in df.iterrows():
        b = pit_bucket(float(row["ret_pct"]), row)
        hist[b] = hist.get(b, 0) + 1
    width = float((df["p95"] - df["p5"]).mean()) if n and df["p95"].notna().any() else None
    mae50 = float((df["ret_pct"] - df["p50"]).abs().mean()) if n and df["p50"].notna().any() else None
    return CalibrationReport(n_matured=n, coverage=coverage, tail=tail, pit_histogram=hist, mean_width_p5_p95=width, mean_abs_error_p50=mae50, by_ticker=df["ticker"].value_counts().to_dict() if n else {})


def render_calibration(rep: CalibrationReport) -> str:
    lines = [f"CALIBRATION — {rep.n_matured} matured forecasts" + (f" ({', '.join(f'{k}:{v}' for k, v in rep.by_ticker.items())})" if rep.by_ticker else "")]
    lines.append("  quantile   nominal   observed   n     95% interval      ok")
    for c in rep.coverage:
        lines.append(f"  {c.quantile:>8}   {c.nominal:>7.0%}   {c.observed:>8.1%}   {c.n:<5} [{c.ci_low:.1%}, {c.ci_high:.1%}]   {'yes' if c.within_ci else 'NO'}")
    t = rep.tail
    lines.append(f"  5% tail: {t.breaches} breaches in {t.n} (expected {t.expected_rate * t.n:.1f}) → band {t.band.upper()}")
    if t.pof_p_value is not None:
        lines.append(f"    failure-rate LR {t.pof_stat:.2f} (p={t.pof_p_value:.3f}) | independence LR {t.independence_stat:.2f} (p={t.independence_p_value:.3f}) | conditional LR {t.conditional_stat:.2f} (p={t.conditional_p_value:.3f})")
    lines.append(f"  PIT histogram: {rep.pit_histogram}")
    if rep.mean_width_p5_p95 is not None:
        lines.append(f"  sharpness: mean p5–p95 width {rep.mean_width_p5_p95:.2f}% | mean |realised − p50| {rep.mean_abs_error_p50:.2f}%")
    return "\n".join(lines)
