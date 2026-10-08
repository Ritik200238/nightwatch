"""Open-session versus shut-session beta: the method must recover a known answer."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nightwatch.stress import session_beta as sb


def synthetic(beta_open: float, beta_closed: float, hours: int = 6000, seed: int = 3):
    idx = pd.date_range("2025-01-01", periods=hours, freq="h", tz="UTC")
    closed = pd.Series(((idx.hour < 14) | (idx.hour >= 21)) | (idx.dayofweek >= 5), index=idx)
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.004, hours)
    noise = rng.normal(0, 0.003, hours)
    y = np.where(closed.to_numpy(), beta_closed, beta_open) * x + noise
    c = lambda r: pd.Series(100 * np.exp(np.cumsum(r)), index=idx)  # noqa: E731
    return {"QQQ": c(x), "ABC": c(y), "SAME": c(1.5 * x + noise)}, closed


def test_it_recovers_different_slopes_and_a_difference_whose_interval_excludes_zero():
    closes, closed = synthetic(1.0, 2.0)
    r = sb.summarize(closes, closed)["ABC"]
    assert abs(r["open"]["beta"] - 1.0) < 0.15 and abs(r["closed"]["beta"] - 2.0) < 0.15
    lo, hi = r["diff"]["ci"]
    assert 0 < lo < r["diff"]["est"] < hi


def test_a_token_with_one_slope_in_both_regimes_has_a_difference_interval_that_covers_zero():
    closes, closed = synthetic(1.5, 1.5)
    d = sb.summarize(closes, closed)["SAME"]["diff"]
    assert d["ci"][0] < 0 < d["ci"][1]


def test_the_proxy_itself_is_left_out_and_a_regime_with_too_few_hours_is_not_reported():
    closes, closed = synthetic(1.0, 1.0, hours=400)
    out = sb.summarize(closes, closed)
    assert "QQQ" not in out and "ABC" not in out  # 400 hours leave under 300 shut ones: no slope is printed


def test_a_gap_in_the_hours_is_not_read_as_an_hourly_return():
    closes, closed = synthetic(1.0, 1.0)
    gappy = {k: v.drop(v.index[1000:1500]) for k, v in closes.items()}
    r = sb.summarize(gappy, closed)["ABC"]
    assert r["open"]["n"] + r["closed"]["n"] <= 6000 - 500 - 1
