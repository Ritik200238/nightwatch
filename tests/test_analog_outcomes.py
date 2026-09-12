from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.analog.cohort import compare_to_baseline, sample_baseline_times, summarize
from nightwatch.analog.outcomes import compute_match_outcomes, structural_horizons, tag_outcome
from nightwatch.time_utils import ET

UTC = UTC


def frame_with_path(start: datetime, hours: int, closes: np.ndarray, native: np.ndarray | None = None) -> pd.DataFrame:
    idx = pd.date_range(start, periods=hours, freq="1h", tz="UTC", name="ts")
    f = pd.DataFrame(index=idx)
    f["spot_close"] = closes
    f["spot_high"] = closes * 1.01
    f["spot_low"] = closes * 0.99
    f["native_close"] = native if native is not None else np.nan
    f["basis_index_bps"] = np.linspace(-10, 40, hours)
    return f


def test_structural_horizons_inside_closed_window():
    sat = datetime(2026, 9, 12, 12, tzinfo=ET)  # Saturday noon ET -> Mon 09:30 ET
    h = structural_horizons(sat)
    assert h["next_open"] == h["window_end"] == 45.5


def test_structural_horizons_during_session():
    wed = datetime(2026, 9, 9, 12, tzinfo=ET)
    h = structural_horizons(wed)
    assert h["window_end"] == 4.0  # to 16:00 close
    assert h["next_open"] == 4.0 + 17.5  # 16:00 -> next day 09:30


def test_outcomes_returns_mfe_mae_excess_and_pending():
    start = datetime(2026, 9, 9, 15, tzinfo=UTC)  # Wed 11:00 ET
    closes = np.full(200, 100.0)
    closes[1:25] = 102.0  # +2% for the first 24h
    closes[25:] = 97.0
    native = np.full(200, 50.0)
    native[10:] = 50.5  # +1% native
    f = frame_with_path(start, 200, closes, native)
    mo = compute_match_outcomes(f, start)
    o24 = mo.outcomes["24h"]
    assert o24.status == "MATURED" and abs(o24.ret_pct - 2.0) < 1e-9
    assert abs(o24.mfe_pct - (102 * 1.01 / 100 - 1) * 100) < 1e-9
    assert abs(o24.native_ret_pct - 1.0) < 1e-9 and abs(o24.excess_pct - 1.0) < 1e-9
    assert o24.max_abs_basis_bps is not None
    o72 = mo.outcomes["72h"]
    assert o72.status == "MATURED" and abs(o72.ret_pct - (-3.0)) < 1e-9 and o72.tag == "STRONG_DOWN"
    # A horizon beyond the frame is PENDING, not fabricated.
    late = compute_match_outcomes(f, start + timedelta(hours=150))
    assert late.outcomes["72h"].status == "PENDING"


def test_tags():
    assert tag_outcome(3.5, 4, -1) == "STRONG_UP"
    assert tag_outcome(-1.5, 1, -2) == "DOWN"
    assert tag_outcome(0.2, 3.5, -3.2) == "WHIPSAW"
    assert tag_outcome(0.1, 0.5, -0.4) == "FLAT"


def make_table(rets, pending: int = 0):
    rows = [{"ts": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=48 * i), "status": "MATURED", "hours": 24.0, "ret_pct": r,
             "mfe_pct": r + 1, "mae_pct": r - 1, "native_ret_pct": 0.0, "excess_pct": r, "max_abs_basis_bps": 20.0, "tag": tag_outcome(r, r + 1, r - 1)} for i, r in enumerate(rets)]
    for j in range(pending):
        rows.append({"ts": datetime(2027, 1, 1, tzinfo=UTC) + timedelta(hours=j), "status": "PENDING", "hours": 24.0, "ret_pct": None, "mfe_pct": None, "mae_pct": None, "native_ret_pct": None, "excess_pct": None, "max_abs_basis_bps": None, "tag": None})
    return pd.DataFrame(rows).set_index("ts")


def test_summary_respects_min_sample_and_reports_ci():
    small = summarize(make_table([1, -1, 2, 0.5]), min_sample=15)
    assert small.insufficient and small.n == 4 and small.mean_pct is None
    rng = np.random.default_rng(0)
    rets = rng.normal(0.5, 2.0, 60)
    s = summarize(make_table(rets, pending=3), min_sample=15)
    assert not s.insufficient and s.n == 60 and s.n_pending == 3
    assert s.ci_mean.low < s.mean_pct < s.ci_mean.high
    assert s.p5 < s.p25 < s.median_pct < s.p75 < s.p95
    assert abs(s.win_rate - (rets > 0).mean()) < 1e-12
    assert sum(s.tag_counts.values()) == 60


def test_weighted_stats_follow_weights():
    rets = np.array([-5.0] * 20 + [5.0] * 20)
    w = np.array([1.0] * 20 + [9.0] * 20)
    s = summarize(make_table(rets), weights=w, min_sample=10)
    assert s.mean_pct == 0.0 and s.weighted_mean_pct == 4.0


def test_baseline_comparison_detects_shift():
    rng = np.random.default_rng(1)
    cohort = make_table(rng.normal(2.0, 1.0, 40))
    base = make_table(rng.normal(0.0, 1.0, 200))
    cmp_ = compare_to_baseline(cohort, base, min_sample=15, n_perm=1000)
    assert cmp_.mean_diff_pct > 1.5 and cmp_.permutation_p_value < 0.01
    same = compare_to_baseline(make_table(rng.normal(0, 1, 40)), base, min_sample=15, n_perm=1000)
    assert same.permutation_p_value > 0.05


def test_sample_baseline_times_spaced_and_excluding():
    idx = pd.date_range(datetime(2026, 1, 1, tzinfo=UTC), periods=24 * 60, freq="1h", tz="UTC")
    mask = pd.Series(idx.dayofweek >= 5, index=idx)
    exclude = pd.DatetimeIndex([idx[24 * 3 + 5]])
    times = sample_baseline_times(idx, n=10, bucket_mask=mask, exclude=exclude, min_separation_h=36)
    assert len(times) == 10 and all(t.dayofweek >= 5 for t in times)
    for a in times:
        for b in times:
            if a != b:
                assert abs((a - b).total_seconds()) >= 36 * 3600
        assert abs((a - exclude[0]).total_seconds()) >= 36 * 3600
