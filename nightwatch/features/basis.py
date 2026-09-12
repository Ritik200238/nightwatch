"""Basis: how far the token trades from fair value, and how that gap behaves.

Three fair-value references, each answering a different question:

* ``index``  – Bitget's own index price for the perp (their fair value; available 24/7).
* ``perp``   – the perpetual's last trade (what the derivative market thinks).
* ``native`` – the last completed regular-session close of the real stock (what the
  real market last agreed on; stale while it is closed, and *that staleness is the
  point*: the token is pricing information the stock cannot yet).

All basis values are in basis points: ``(spot / reference - 1) * 1e4``.

Rolling statistics use only past rows (pandas rolling is trailing), so every value at
row *t* is computable from bars closed at or before *t*.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BPS = 1e4
Z_WINDOW_H = 24 * 14  # two weeks of hourly observations
Z_MIN_PERIODS = 24 * 3


def add_basis_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Add basis_* columns to an aligned hourly frame (see ``features.series``)."""
    f = frame.copy()
    spot = f["spot_close"]
    f["basis_index_bps"] = (spot / f["index_close"] - 1.0) * BPS if "index_close" in f else np.nan
    f["basis_perp_bps"] = (spot / f["perp_close"] - 1.0) * BPS if "perp_close" in f else np.nan
    f["basis_native_bps"] = (spot / f["native_close"] - 1.0) * BPS if "native_close" in f else np.nan

    for col in ("basis_index_bps", "basis_perp_bps", "basis_native_bps"):
        s = f[col]
        roll = s.rolling(Z_WINDOW_H, min_periods=Z_MIN_PERIODS)
        mean, std = roll.mean(), roll.std()
        f[col.replace("_bps", "_z")] = (s - mean) / std.replace(0.0, np.nan)
        f[col.replace("_bps", "_abs_bps")] = s.abs()
        # Widening rate: change in |basis| over the last 3 and 6 completed hours.
        f[col.replace("_bps", "_d3h_bps")] = s.abs().diff(3)
        f[col.replace("_bps", "_d6h_bps")] = s.abs().diff(6)
    return f


def basis_by_bucket(frame: pd.DataFrame, col: str = "basis_index_bps") -> pd.DataFrame:
    """Descriptive stats of |basis| per hour-of-week bucket — the "1.8× wider when the
    US market is closed" table, computed from stored data instead of asserted."""
    s = frame[[col, "bucket"]].dropna()
    g = s.groupby("bucket")[col]
    out = pd.DataFrame(
        {
            "n": g.size(),
            "mean_abs_bps": s.assign(a=s[col].abs()).groupby("bucket")["a"].mean(),
            "median_bps": g.median(),
            "p05_bps": g.quantile(0.05),
            "p95_bps": g.quantile(0.95),
            "p99_abs_bps": s.assign(a=s[col].abs()).groupby("bucket")["a"].quantile(0.99),
            "std_bps": g.std(),
        }
    )
    return out.sort_values("mean_abs_bps", ascending=False)


def closed_vs_open_ratio(frame: pd.DataFrame, col: str = "basis_index_bps") -> float | None:
    """mean |basis| while the US market is closed ÷ mean |basis| while it is open."""
    s = frame[[col, "is_closed"]].dropna()
    if s.empty:
        return None
    closed = s.loc[s["is_closed"], col].abs().mean()
    opened = s.loc[~s["is_closed"], col].abs().mean()
    if not opened or np.isnan(opened) or np.isnan(closed):
        return None
    return float(closed / opened)
