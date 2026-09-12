"""Regime: volatility, trend and liquidity state of the token, hour by hour.

Computed as trailing statistics on the aligned hourly frame so the same code gives
(a) the state *now* for the ticket and (b) the state at every past hour for analog
search. Every window is trailing; nothing peeks forward.

Definitions
-----------
* ``rv_24h`` / ``rv_168h`` – annualised realised volatility of hourly log returns over
  the last 24 / 168 completed hours (sqrt(8760) scaling for a 24/7 market).
* ``vol_pctl_90d`` – percentile rank of ``rv_24h`` within its own trailing 90-day
  distribution (0–100). Turbulent when high *or* when absolute vol crosses a floor,
  so a quiet name in a violent month is still flagged.
* ``trend_sma_pct`` – distance of the close from its 30-day simple moving average, and
  ``sma_slope_5d_pct`` – how that average moved over the last 5 days.
* ``liq_ratio`` – quote volume over the last 24 hours vs the average 24-hour volume over
  the preceding 30 days (baseline strictly precedes the window, so a slow bleed cannot
  hide itself). ``no_trade_share_24h`` – share of the last 24 hours with no trades.
* States and a size multiplier in [0.25, 1] that downstream sizing applies.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HOURS_PER_YEAR = 24 * 365
RV_SHORT_H = 24
RV_LONG_H = 24 * 7
VOL_PCTL_WINDOW_H = 24 * 90
SMA_H = 24 * 30
SLOPE_H = 24 * 5
LIQ_WINDOW_H = 24
LIQ_BASELINE_H = 24 * 30


@dataclass(frozen=True)
class RegimeThresholds:
    calm_pctl: float = 40.0
    turbulent_pctl: float = 75.0
    turbulent_abs_vol: float = 0.60  # 60% annualised
    thin_liq_ratio: float = 0.7
    surging_liq_ratio: float = 1.5
    thin_no_trade_share: float = 0.25
    turbulent_factor: float = 0.5
    downtrend_factor: float = 0.75
    thin_factor: float = 0.85
    min_multiplier: float = 0.25


DEFAULT_THRESHOLDS = RegimeThresholds()


def add_regime_columns(frame: pd.DataFrame, thresholds: RegimeThresholds = DEFAULT_THRESHOLDS) -> pd.DataFrame:
    f = frame.copy()
    close = f["spot_close"].astype(float)
    logret = np.log(close).diff()
    # Filled (no-trade) hours contribute zero return; that is the truthful reading of
    # "no trade happened", not a data error, but we exclude them from vol so a dead
    # weekend does not masquerade as calm.
    active = ~f["spot_filled"].astype(bool)
    r_active = logret.where(active)

    f["rv_24h"] = r_active.rolling(RV_SHORT_H, min_periods=RV_SHORT_H // 2).std() * np.sqrt(HOURS_PER_YEAR)
    f["rv_168h"] = r_active.rolling(RV_LONG_H, min_periods=RV_LONG_H // 2).std() * np.sqrt(HOURS_PER_YEAR)
    # Percentile rank of the current value within its trailing window (vectorised;
    # equivalent to ranking the last element against the window's valid values).
    f["vol_pctl_90d"] = f["rv_24h"].rolling(VOL_PCTL_WINDOW_H, min_periods=RV_LONG_H).rank(pct=True) * 100.0

    sma = close.rolling(SMA_H, min_periods=SMA_H // 2).mean()
    f["trend_sma_pct"] = (close / sma - 1.0) * 100.0
    f["sma_slope_5d_pct"] = (sma / sma.shift(SLOPE_H) - 1.0) * 100.0

    vol = f["spot_vol_quote"].astype(float).fillna(0.0)
    recent = vol.rolling(LIQ_WINDOW_H, min_periods=LIQ_WINDOW_H).sum()
    baseline_daily = vol.rolling(LIQ_BASELINE_H, min_periods=LIQ_BASELINE_H // 2).sum().shift(LIQ_WINDOW_H) / (LIQ_BASELINE_H / 24)
    f["liq_ratio"] = recent / baseline_daily.replace(0.0, np.nan)
    f["no_trade_share_24h"] = f["spot_filled"].astype(float).rolling(LIQ_WINDOW_H, min_periods=LIQ_WINDOW_H).mean()

    f["vol_state"] = _vol_state(f["vol_pctl_90d"], f["rv_24h"], thresholds)
    f["trend_state"] = _trend_state(f["trend_sma_pct"], f["sma_slope_5d_pct"])
    f["liq_state"] = _liq_state(f["liq_ratio"], f["no_trade_share_24h"], thresholds)
    f["regime_label"] = _regime_label(f["vol_state"], f["trend_state"], f["liq_state"])
    f["risk_multiplier"] = _multiplier(f["vol_state"], f["trend_state"], f["liq_state"], f["regime_label"], thresholds)
    return f


def _vol_state(pctl: pd.Series, rv: pd.Series, t: RegimeThresholds) -> pd.Series:
    out = pd.Series("unknown", index=pctl.index, dtype=object)
    known = pctl.notna()
    turbulent = known & ((pctl >= t.turbulent_pctl) | (rv >= t.turbulent_abs_vol))
    calm = known & ~turbulent & (pctl <= t.calm_pctl)
    out[known] = "normal"
    out[calm] = "calm"
    out[turbulent] = "turbulent"
    return out


def _trend_state(dist: pd.Series, slope: pd.Series) -> pd.Series:
    out = pd.Series("unknown", index=dist.index, dtype=object)
    known = dist.notna() & slope.notna()
    out[known] = "sideways"
    out[known & (dist > 0) & (slope > 0)] = "up"
    out[known & (dist < 0) & (slope < 0)] = "down"
    return out


def _liq_state(ratio: pd.Series, no_trade: pd.Series, t: RegimeThresholds) -> pd.Series:
    out = pd.Series("unknown", index=ratio.index, dtype=object)
    known = ratio.notna()
    out[known] = "normal"
    out[known & (ratio > t.surging_liq_ratio)] = "surging"
    thin = known & ((ratio < t.thin_liq_ratio) | (no_trade.fillna(0) >= t.thin_no_trade_share))
    out[thin] = "thinning"
    return out


def _regime_label(vol: pd.Series, trend: pd.Series, liq: pd.Series) -> pd.Series:
    out = pd.Series("mixed", index=vol.index, dtype=object)
    hostile = (vol == "turbulent") | ((trend == "down") & (liq == "thinning"))
    favorable = (trend == "up") & vol.isin(["calm", "normal"]) & (liq != "thinning")
    out[favorable] = "favorable"
    out[hostile] = "hostile"
    out[vol == "unknown"] = "unknown"
    return out


def _multiplier(vol: pd.Series, trend: pd.Series, liq: pd.Series, label: pd.Series, t: RegimeThresholds) -> pd.Series:
    m = pd.Series(1.0, index=vol.index, dtype=float)
    m[vol == "turbulent"] *= t.turbulent_factor
    m[trend == "down"] *= t.downtrend_factor
    m[liq == "thinning"] *= t.thin_factor
    m = m.clip(lower=t.min_multiplier)
    m[label == "favorable"] = 1.0
    return m
