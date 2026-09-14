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
* ``liq_ratio`` – quote volume over the last 24 hours vs what this token normally does
  *in those same hours of the week*, taken from the preceding four weeks. A tokenized US
  stock trades every hour but not equally: Sunday afternoon is structurally quieter than
  Tuesday's US open, so a flat 30-day average calls every weekend a liquidity crisis.
  Like-for-like asks the question we mean — is this name thinner than it usually is at
  this time of week? The baseline strictly precedes the window, so a slow bleed cannot
  hide itself, and where there is no same-hour history yet it falls back to the flat
  30-day average. ``no_trade_share_24h`` – share of the last 24 hours with no trades, and
  ``no_trade_excess_24h`` – how far that sits above the same-hour-of-week norm.
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
LIQ_SEASONAL_WEEKS = 4  # same-hour-of-week observations behind the window
LIQ_RATIO_CAP = 10.0  # ten times normal and a thousand times normal mean the same thing
HOURS_PER_WEEK = 24 * 7


@dataclass(frozen=True)
class RegimeThresholds:
    calm_pctl: float = 40.0
    turbulent_pctl: float = 75.0
    turbulent_abs_vol: float = 0.60  # 60% annualised
    thin_liq_ratio: float = 0.7
    surging_liq_ratio: float = 1.5
    thin_no_trade_share: float = 0.25  # excess over the same-hour-of-week norm
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

    # Volatility is measured over the last N *traded* hours, then carried through the
    # hours nothing traded: over a weekend the answer to "how volatile is this token" is
    # "as volatile as it was on Friday", not "unknown". Without this every US-stock token
    # lost its regime label from Friday close to Monday open and the desk could not decide.
    traded = r_active.dropna()
    f["rv_24h"] = (traded.rolling(RV_SHORT_H, min_periods=RV_SHORT_H // 2).std() * np.sqrt(HOURS_PER_YEAR)).reindex(f.index).ffill()
    f["rv_168h"] = (traded.rolling(RV_LONG_H, min_periods=RV_LONG_H // 2).std() * np.sqrt(HOURS_PER_YEAR)).reindex(f.index).ffill()
    # Percentile rank of the current value within its trailing window (vectorised;
    # equivalent to ranking the last element against the window's valid values).
    f["vol_pctl_90d"] = f["rv_24h"].rolling(VOL_PCTL_WINDOW_H, min_periods=RV_LONG_H).rank(pct=True) * 100.0

    sma = close.rolling(SMA_H, min_periods=SMA_H // 2).mean()
    f["trend_sma_pct"] = (close / sma - 1.0) * 100.0
    f["sma_slope_5d_pct"] = (sma / sma.shift(SLOPE_H) - 1.0) * 100.0

    vol = f["spot_vol_quote"].astype(float).fillna(0.0)
    recent = vol.rolling(LIQ_WINDOW_H, min_periods=LIQ_WINDOW_H).sum()
    # Expected volume for each hour: what the same hour of the week did over the last
    # four weeks, falling back to the flat 30-day average while that history is short.
    flat_hourly = vol.rolling(LIQ_BASELINE_H, min_periods=LIQ_BASELINE_H // 2).mean().shift(LIQ_WINDOW_H)
    expected_hourly = _seasonal_norm(vol, LIQ_SEASONAL_WEEKS).fillna(flat_hourly)
    baseline = expected_hourly.rolling(LIQ_WINDOW_H, min_periods=LIQ_WINDOW_H).sum()
    # Only a baseline of literally nothing falls back to the flat one: a weekend baseline
    # is *meant* to be a small fraction of the all-hours average, and an earlier version
    # of this guard treated "less than a twentieth of the flat average" as broken, which
    # quietly restored the very bug the seasonal baseline exists to remove.
    flat_baseline = flat_hourly.rolling(LIQ_WINDOW_H, min_periods=LIQ_WINDOW_H).sum()
    baseline = baseline.where(baseline > 0.0, flat_baseline)
    # Cap what survives: beyond a point, "much busier than normal" is one fact, not a
    # scale, and uncapped a single hour dominates anything that standardises this column.
    f["liq_ratio"] = (recent / baseline.replace(0.0, np.nan)).clip(upper=LIQ_RATIO_CAP)

    filled = f["spot_filled"].astype(float)
    f["no_trade_share_24h"] = filled.rolling(LIQ_WINDOW_H, min_periods=LIQ_WINDOW_H).mean()
    # Excess over the same-hour-of-week norm. With no same-hour history the norm is zero,
    # which makes the excess the raw share and the thinning test its original self.
    expected_quiet = _seasonal_norm(filled, LIQ_SEASONAL_WEEKS).rolling(LIQ_WINDOW_H, min_periods=LIQ_WINDOW_H).mean()
    f["no_trade_excess_24h"] = f["no_trade_share_24h"] - expected_quiet.fillna(0.0)

    f["liq_state"] = _liq_state(f["liq_ratio"], f["no_trade_excess_24h"], thresholds)
    f["vol_state"] = _vol_state(f["vol_pctl_90d"], f["rv_24h"], thresholds)
    f["trend_state"] = _trend_state(f["trend_sma_pct"], f["sma_slope_5d_pct"])
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


def _seasonal_norm(values: pd.Series, weeks: int) -> pd.Series:
    """Median of the same hour of the week over the previous ``weeks`` weeks.

    Trailing and strictly exclusive: the current observation never enters its own norm.
    Median rather than mean so one earnings evening does not raise the bar for every
    later Wednesday at 21:00.
    """
    if not isinstance(values.index, pd.DatetimeIndex) or len(values) < HOURS_PER_WEEK:
        return pd.Series(np.nan, index=values.index, dtype=float)
    hour_of_week = pd.Series(values.index.dayofweek * 24 + values.index.hour, index=values.index)
    return values.groupby(hour_of_week).transform(lambda s: s.shift(1).rolling(weeks, min_periods=2).median())


def _liq_state(ratio: pd.Series, no_trade_excess: pd.Series, t: RegimeThresholds) -> pd.Series:
    out = pd.Series("unknown", index=ratio.index, dtype=object)
    known = ratio.notna()
    out[known] = "normal"
    out[known & (ratio > t.surging_liq_ratio)] = "surging"
    thin = known & ((ratio < t.thin_liq_ratio) | (no_trade_excess.fillna(0) >= t.thin_no_trade_share))
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
