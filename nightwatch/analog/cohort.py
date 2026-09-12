"""Turn a set of matured outcomes into an honest distribution.

Rules that make the numbers trustworthy:

* **Sample size first.** Every summary carries ``n``; below ``min_sample`` the summary
  is marked ``insufficient`` and no verdict-grade statistics are produced.
* **Percentiles over moments.** The trader wants "how bad does it get" — p5, p25,
  median, p75, p95 — not just a mean.
* **Uncertainty is shown.** Bootstrap confidence intervals for the mean, median and
  p5 tell the reader how much to trust a number from *n* episodes.
* **A baseline.** The same statistics for *random* past hours of the same kind (same
  bucket) answer "is this setup special, or is this just what the token does?".
  The difference in means is tested with a permutation test.
* **Similarity weighting.** Optionally weight episodes by analog similarity so
  closer matches count more; the unweighted numbers are always reported too.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nightwatch.time_utils import index_epoch_ns

DEFAULT_MIN_SAMPLE = 15
PCTS = (5, 25, 50, 75, 95)


@dataclass(frozen=True)
class Interval95:
    low: float
    high: float


@dataclass(frozen=True)
class CohortStats:
    n: int
    n_pending: int
    insufficient: bool
    mean_pct: float | None = None
    median_pct: float | None = None
    std_pct: float | None = None
    win_rate: float | None = None  # share with ret > 0
    p5: float | None = None
    p25: float | None = None
    p75: float | None = None
    p95: float | None = None
    mfe_median_pct: float | None = None
    mae_median_pct: float | None = None
    mae_p5_pct: float | None = None
    excess_mean_pct: float | None = None
    max_abs_basis_p95_bps: float | None = None
    tag_counts: dict[str, int] = field(default_factory=dict)
    ci_mean: Interval95 | None = None
    ci_median: Interval95 | None = None
    ci_p5: Interval95 | None = None
    weighted_mean_pct: float | None = None
    weighted_p5: float | None = None


@dataclass(frozen=True)
class BaselineComparison:
    baseline: CohortStats
    mean_diff_pct: float | None
    permutation_p_value: float | None  # two-sided, H0: same mean as random hours
    p5_diff_pct: float | None


def _pct(a: np.ndarray, p: float) -> float:
    return float(np.percentile(a, p))


def bootstrap_ci(values: np.ndarray, stat, *, n_boot: int = 4000, seed: int = 11) -> Interval95:  # noqa: ANN001
    """Percentile bootstrap CI. ``stat`` is ``"mean"``, ``"median"``, ``("percentile", p)``
    or a callable accepting ``axis=1`` on an (n_boot, n) array — vectorised so 4000
    resamples cost milliseconds, not seconds."""
    rng = np.random.default_rng(seed)
    n = len(values)
    idx = rng.integers(0, n, size=(n_boot, n))
    samples = values[idx]
    if stat == "mean":
        stats = samples.mean(axis=1)
    elif stat == "median":
        stats = np.median(samples, axis=1)
    elif isinstance(stat, tuple) and stat[0] == "percentile":
        stats = np.percentile(samples, stat[1], axis=1)
    else:
        stats = stat(samples, axis=1)
    return Interval95(low=float(np.percentile(stats, 2.5)), high=float(np.percentile(stats, 97.5)))


def weighted_percentile(values: np.ndarray, weights: np.ndarray, p: float) -> float:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w) - 0.5 * w
    cum /= w.sum()
    return float(np.interp(p / 100.0, cum, v))


def summarize(table: pd.DataFrame, *, weights: np.ndarray | None = None, min_sample: int = DEFAULT_MIN_SAMPLE) -> CohortStats:
    """``table`` is ``outcomes_table(...)`` for one horizon."""
    if table.empty:
        return CohortStats(n=0, n_pending=0, insufficient=True)
    pending = int((table["status"] != "MATURED").sum())
    m = table[table["status"] == "MATURED"].copy()
    n = len(m)
    if n < min_sample:
        return CohortStats(n=n, n_pending=pending, insufficient=True, tag_counts=m["tag"].value_counts().to_dict() if n else {})

    r = m["ret_pct"].to_numpy(dtype=float)
    mfe = m["mfe_pct"].to_numpy(dtype=float)
    mae = m["mae_pct"].to_numpy(dtype=float)
    excess = m["excess_pct"].dropna().to_numpy(dtype=float)
    basis = m["max_abs_basis_bps"].dropna().to_numpy(dtype=float)

    stats = CohortStats(
        n=n,
        n_pending=pending,
        insufficient=False,
        mean_pct=float(r.mean()),
        median_pct=float(np.median(r)),
        std_pct=float(r.std(ddof=1)) if n > 1 else None,
        win_rate=float((r > 0).mean()),
        p5=_pct(r, 5), p25=_pct(r, 25), p75=_pct(r, 75), p95=_pct(r, 95),
        mfe_median_pct=float(np.median(mfe)),
        mae_median_pct=float(np.median(mae)),
        mae_p5_pct=_pct(mae, 5),
        excess_mean_pct=float(excess.mean()) if excess.size else None,
        max_abs_basis_p95_bps=_pct(basis, 95) if basis.size else None,
        tag_counts=m["tag"].value_counts().to_dict(),
        ci_mean=bootstrap_ci(r, "mean"),
        ci_median=bootstrap_ci(r, "median"),
        ci_p5=bootstrap_ci(r, ("percentile", 5)),
    )
    if weights is not None:
        w = np.asarray(weights, dtype=float)
        if len(w) == len(table):
            w = w[(table["status"] == "MATURED").to_numpy()]
        if len(w) == n and w.sum() > 0:
            stats = CohortStats(**{**stats.__dict__, "weighted_mean_pct": float(np.average(r, weights=w)), "weighted_p5": weighted_percentile(r, w, 5)})
    return stats


def compare_to_baseline(cohort: pd.DataFrame, baseline: pd.DataFrame, *, min_sample: int = DEFAULT_MIN_SAMPLE, n_perm: int = 5000, seed: int = 5) -> BaselineComparison:
    base_stats = summarize(baseline, min_sample=min_sample)
    c = cohort[cohort["status"] == "MATURED"]["ret_pct"].to_numpy(dtype=float)
    b = baseline[baseline["status"] == "MATURED"]["ret_pct"].to_numpy(dtype=float)
    if len(c) < min_sample or len(b) < min_sample:
        return BaselineComparison(baseline=base_stats, mean_diff_pct=None, permutation_p_value=None, p5_diff_pct=None)
    observed = c.mean() - b.mean()
    pooled = np.concatenate([c, b])
    rng = np.random.default_rng(seed)
    count = 0
    for _ in range(n_perm):
        rng.shuffle(pooled)
        diff = pooled[: len(c)].mean() - pooled[len(c):].mean()
        if abs(diff) >= abs(observed):
            count += 1
    p = (count + 1) / (n_perm + 1)
    return BaselineComparison(
        baseline=base_stats, mean_diff_pct=float(observed), permutation_p_value=float(p),
        p5_diff_pct=float(_pct(c, 5) - _pct(b, 5)),
    )


def sample_baseline_times(history_index: pd.DatetimeIndex, *, n: int, bucket_mask: pd.Series | None = None, fallback_mask: pd.Series | None = None, exclude: pd.DatetimeIndex | None = None, min_separation_h: int = 36, min_pool: int = 30, seed: int = 21) -> list[pd.Timestamp]:
    """Random past hours of the same kind, spaced apart, avoiding the analog matches.

    If the same-bucket pool is thinner than ``min_pool`` rows, ``fallback_mask``
    (e.g. all closed-market hours) is used instead so the baseline stays meaningful."""
    rng = np.random.default_rng(seed)
    candidates = history_index if bucket_mask is None else history_index[bucket_mask.to_numpy()]
    if fallback_mask is not None and len(candidates) < min_pool:
        candidates = history_index[fallback_mask.to_numpy()]
    cand_ns = index_epoch_ns(candidates)
    sep_ns = np.int64(min_separation_h) * 3_600_000_000_000
    if exclude is not None and len(exclude):
        ex_ns = index_epoch_ns(pd.DatetimeIndex(exclude))
        keep = (np.abs(cand_ns[:, None] - ex_ns[None, :]) >= sep_ns).all(axis=1)
        cand_ns = cand_ns[keep]
    order = rng.permutation(cand_ns.size)
    chosen_ns = np.empty(0, dtype=np.int64)
    for i in order:
        t = cand_ns[i]
        if chosen_ns.size and np.abs(chosen_ns - t).min() < sep_ns:
            continue
        chosen_ns = np.append(chosen_ns, t)
        if chosen_ns.size >= n:
            break
    return [pd.Timestamp(t, tz="UTC") for t in chosen_ns]
