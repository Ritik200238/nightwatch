"""Monte Carlo over the horizon and reverse stress.

Paths are built by **moving-block bootstrap of hourly log returns** drawn from the
token's own history *conditioned on the relevant session kind* (closed-market hours
for a weekend hold, all hours otherwise). Blocks preserve the short-range dependence
(volatility clustering, gap-then-drift) that i.i.d. resampling destroys, and using
the token's own returns keeps fat tails without assuming a distribution.

Outputs: terminal-return percentiles, expected shortfall, probability of breaching a
loss threshold, and the distribution of the worst intra-horizon drawdown (what a stop
would have hit). Reverse stress answers "how large a move loses X% of notional after
exit costs?" by inverting the scenario P&L function.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nightwatch.data.models import OrderBookSnapshot
from nightwatch.stress.scenarios import Position, Scenario, Severity, apply_scenario


@dataclass(frozen=True)
class MonteCarloResult:
    n_paths: int
    horizon_h: int
    block_h: int
    source_hours: int
    terminal_ret_pct: np.ndarray  # per path
    worst_drawdown_pct: np.ndarray  # per path, most adverse point vs entry
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    expected_shortfall_5_pct: float  # mean of the worst 5% terminal returns
    prob_loss_gt: dict[float, float]  # threshold pct -> probability
    drawdown_p5: float


def hourly_log_returns(frame: pd.DataFrame, *, closed_only: bool) -> np.ndarray:
    """Log returns of traded (non-filled) hours; optionally only hours inside closed windows."""
    f = frame[["spot_close", "spot_filled", "is_closed"]].copy()
    r = np.log(f["spot_close"]).diff()
    mask = ~f["spot_filled"].astype(bool)
    if closed_only:
        mask &= f["is_closed"].astype(bool)
    return r[mask].dropna().to_numpy(dtype=float)


def block_bootstrap_paths(returns: np.ndarray, horizon_h: int, *, n_paths: int = 5000, block_h: int | None = None, seed: int = 17) -> np.ndarray:
    """Returns an (n_paths, horizon_h) array of resampled log returns."""
    if returns.size < 48 or horizon_h <= 0:
        raise ValueError("need at least 48 hourly returns and a positive horizon")
    rng = np.random.default_rng(seed)
    block = block_h or int(np.clip(round(np.sqrt(horizon_h) * 2), 3, 24))
    n_blocks = int(np.ceil(horizon_h / block))
    starts = rng.integers(0, returns.size - block + 1, size=(n_paths, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]).reshape(n_paths, -1)[:, :horizon_h]
    return returns[idx]


def simulate(position_sign: float, returns: np.ndarray, horizon_h: int, *, n_paths: int = 5000, block_h: int | None = None, seed: int = 17, loss_thresholds: tuple[float, ...] = (2.0, 5.0, 10.0)) -> MonteCarloResult:
    paths = block_bootstrap_paths(returns, horizon_h, n_paths=n_paths, block_h=block_h, seed=seed)
    cum = np.cumsum(paths, axis=1)
    pnl_path = position_sign * (np.exp(cum) - 1.0) * 100.0  # % of notional along the path
    terminal = pnl_path[:, -1]
    worst = pnl_path.min(axis=1)
    worst = np.minimum(worst, 0.0)
    sorted_t = np.sort(terminal)
    k = max(1, int(0.05 * len(sorted_t)))
    return MonteCarloResult(
        n_paths=n_paths, horizon_h=horizon_h, block_h=block_h or int(np.clip(round(np.sqrt(horizon_h) * 2), 3, 24)), source_hours=int(returns.size),
        terminal_ret_pct=terminal, worst_drawdown_pct=worst,
        p5=float(np.percentile(terminal, 5)), p25=float(np.percentile(terminal, 25)), p50=float(np.percentile(terminal, 50)),
        p75=float(np.percentile(terminal, 75)), p95=float(np.percentile(terminal, 95)),
        expected_shortfall_5_pct=float(sorted_t[:k].mean()),
        prob_loss_gt={t: float((terminal <= -t).mean()) for t in loss_thresholds},
        drawdown_p5=float(np.percentile(worst, 5)),
    )


def reverse_stress(position: Position, *, book: OrderBookSnapshot | None, taker_fee: float, target_loss_pct: float, horizon_h: float, basis_shock_bps: float = 0.0, depth_multiplier: float = 1.0) -> float | None:
    """Price move (pct, adverse) at which total P&L after exit costs equals −target_loss_pct.
    Bisection on the scenario P&L; None if the book cannot absorb the exit at all."""
    def total_at(move: float) -> float | None:
        sc = Scenario(id="reverse", name="reverse", severity=Severity.SEVERE, horizon_h=horizon_h, price_move_pct=move, basis_shock_bps=basis_shock_bps, depth_multiplier=depth_multiplier)
        return apply_scenario(position, sc, book=book, taker_fee=taker_fee).total_pct_of_notional

    lo, hi = 0.0, 60.0  # adverse magnitude in pct
    sign = -position.sign  # adverse direction
    t0 = total_at(0.0)
    if t0 is None:
        return None
    if t0 <= -target_loss_pct:
        return 0.0  # already breached by exit costs alone
    for _ in range(60):
        mid = (lo + hi) / 2.0
        t = total_at(sign * mid)
        if t is None:
            return None
        if t <= -target_loss_pct:
            hi = mid
        else:
            lo = mid
    return sign * hi
