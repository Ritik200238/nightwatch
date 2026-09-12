"""Forecast skill: does the analog distribution beat a random same-bucket baseline?

Calibration asks whether the stated probabilities are honest. Skill asks whether the
forecast carries information at all. Both are needed: an unconditional climatology is
perfectly calibrated and perfectly useless.

The score is the pinball (quantile) loss, the proper scoring rule for a quantile
forecast: for realised ``y`` and predicted quantile ``q`` at level ``tau``,

    L = (y - q) * tau            if y >= q
      = (q - y) * (1 - tau)      otherwise

Lower is better. Averaged over the five stated quantiles it approximates the CRPS of
the whole distribution. The comparison is paired: each replay point has an analog
forecast and a baseline forecast (random past hours from the same time-of-week bucket,
sampled from history strictly before the point), so the difference in loss per point is
what is bootstrapped. A skill score of ``1 - L_analog / L_baseline`` > 0 means the
analogs beat climatology.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

QUANTILES: tuple[tuple[str, float], ...] = (("p5", 0.05), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p95", 0.95))


def pinball(y: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    diff = y - q
    return np.where(diff >= 0, tau * diff, (tau - 1.0) * diff)


@dataclass(frozen=True)
class QuantileSkill:
    quantile: str
    tau: float
    loss_analog: float
    loss_baseline: float
    skill: float  # 1 - analog/baseline
    diff_ci_low: float  # bootstrap CI of (baseline - analog); > 0 favours analogs
    diff_ci_high: float
    win_share: float  # share of points where the analog loss is lower


@dataclass(frozen=True)
class SkillReport:
    n: int
    per_quantile: list[QuantileSkill]
    mean_loss_analog: float | None
    mean_loss_baseline: float | None
    skill: float | None
    diff_ci_low: float | None
    diff_ci_high: float | None
    win_share: float | None
    baseline_lo_coverage: float | None  # share of outcomes below baseline p5
    baseline_hi_coverage: float | None
    analog_lo_coverage: float | None
    analog_hi_coverage: float | None
    by_ticker: dict[str, float] = field(default_factory=dict)  # skill per ticker


def _paired_ci(diff: np.ndarray, *, n_boot: int = 4000, seed: int = 17) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), size=(n_boot, len(diff)))
    means = diff[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def compare_skill(forecasts: pd.DataFrame, *, min_n: int = 30) -> SkillReport:
    """``forecasts`` = Journal.forecasts(matured_only=True); rows without a baseline are skipped."""
    cols = [q for q, _ in QUANTILES]
    need = ["ret_pct", *cols, *[f"base_{q}" for q in cols]]
    df = forecasts.dropna(subset=[c for c in need if c in forecasts.columns]) if all(c in forecasts.columns for c in need) else forecasts.iloc[0:0]
    n = len(df)
    if n < min_n:
        return SkillReport(n=n, per_quantile=[], mean_loss_analog=None, mean_loss_baseline=None, skill=None, diff_ci_low=None, diff_ci_high=None, win_share=None, baseline_lo_coverage=None, baseline_hi_coverage=None, analog_lo_coverage=None, analog_hi_coverage=None)
    y = df["ret_pct"].to_numpy(dtype=float)
    per: list[QuantileSkill] = []
    total_a = np.zeros(n)
    total_b = np.zeros(n)
    for q, tau in QUANTILES:
        la = pinball(y, df[q].to_numpy(dtype=float), tau)
        lb = pinball(y, df[f"base_{q}"].to_numpy(dtype=float), tau)
        total_a += la
        total_b += lb
        lo, hi = _paired_ci(lb - la)
        per.append(QuantileSkill(q, tau, float(la.mean()), float(lb.mean()), float(1 - la.mean() / lb.mean()) if lb.mean() > 0 else 0.0, lo, hi, float((la < lb).mean())))
    ma, mb = total_a.mean() / len(QUANTILES), total_b.mean() / len(QUANTILES)
    lo, hi = _paired_ci((total_b - total_a) / len(QUANTILES))
    by_ticker: dict[str, float] = {}
    for t, sub in df.groupby("ticker"):
        yy = sub["ret_pct"].to_numpy(dtype=float)
        a = sum(pinball(yy, sub[q].to_numpy(dtype=float), tau).mean() for q, tau in QUANTILES)
        b = sum(pinball(yy, sub[f"base_{q}"].to_numpy(dtype=float), tau).mean() for q, tau in QUANTILES)
        by_ticker[str(t)] = float(1 - a / b) if b > 0 else 0.0
    return SkillReport(
        n=n, per_quantile=per, mean_loss_analog=float(ma), mean_loss_baseline=float(mb), skill=float(1 - ma / mb) if mb > 0 else 0.0,
        diff_ci_low=lo, diff_ci_high=hi, win_share=float((total_a < total_b).mean()),
        baseline_lo_coverage=float((y < df["base_p5"].to_numpy(dtype=float)).mean()), baseline_hi_coverage=float((y > df["base_p95"].to_numpy(dtype=float)).mean()),
        analog_lo_coverage=float((y < df["p5"].to_numpy(dtype=float)).mean()), analog_hi_coverage=float((y > df["p95"].to_numpy(dtype=float)).mean()),
        by_ticker=by_ticker,
    )


def render_skill(rep: SkillReport) -> str:
    if rep.skill is None:
        return f"SKILL vs random same-bucket hours: not enough paired forecasts (n={rep.n}, need 30)"
    lines = [f"SKILL vs random same-bucket hours ({rep.n} paired forecasts)"]
    lines.append(f"  mean pinball loss: analog {rep.mean_loss_analog:.3f} vs baseline {rep.mean_loss_baseline:.3f} -> skill {rep.skill:+.1%} (95% CI of loss difference [{rep.diff_ci_low:+.3f}, {rep.diff_ci_high:+.3f}]; analog wins {rep.win_share:.0%} of points)")
    lines.append("  quantile   analog   baseline   skill    diff CI")
    for q in rep.per_quantile:
        lines.append(f"  {q.quantile:>8}   {q.loss_analog:6.3f}   {q.loss_baseline:8.3f}   {q.skill:+6.1%}   [{q.diff_ci_low:+.3f}, {q.diff_ci_high:+.3f}]")
    lines.append(f"  tails: below p5 analog {rep.analog_lo_coverage:.1%} vs baseline {rep.baseline_lo_coverage:.1%} | above p95 analog {rep.analog_hi_coverage:.1%} vs baseline {rep.baseline_hi_coverage:.1%}")
    if rep.by_ticker:
        lines.append("  per token: " + ", ".join(f"{t} {s:+.0%}" for t, s in sorted(rep.by_ticker.items())))
    return "\n".join(lines)
