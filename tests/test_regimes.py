"""Regime map: clusters fitted on the past, described by what they measurably are."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from nightwatch.analog.regimes import DEFAULT_K, MIN_ROWS_PER_FIT, build

START = datetime(2026, 1, 1, tzinfo=UTC)


def two_regime_frame(n: int = 2000, seed: int = 3) -> pd.DataFrame:
    """Alternating blocks of calm and turbulent hours, so clusters have something to find."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(START, periods=n, freq="1h", tz="UTC")
    turbulent = (np.arange(n) // 200) % 2 == 1
    vol = np.where(turbulent, rng.normal(85, 5, n), rng.normal(20, 5, n)).clip(0, 100)
    basis = np.where(turbulent, rng.normal(1.5, 0.3, n), rng.normal(0.0, 0.3, n))
    trend = np.where(turbulent, rng.normal(-3, 1, n), rng.normal(2, 1, n))
    rets = rng.normal(0, np.where(turbulent, 0.012, 0.002))
    return pd.DataFrame(
        {
            "vol_pctl_90d": vol, "basis_index_z": basis, "trend_sma_pct": trend,
            "liq_ratio": np.where(turbulent, 0.5, 1.2), "rv_24h": vol / 200,
            "spot_close": 100 * np.exp(np.cumsum(rets)),
        },
        index=idx,
    )


def test_too_little_history_refuses_rather_than_guesses():
    m = build(two_regime_frame(n=MIN_ROWS_PER_FIT - 100))
    assert m.regimes == [] and "too few" in m.note


def test_it_finds_the_two_states_and_sorts_them_by_volatility():
    m = build(two_regime_frame(), k=DEFAULT_K)
    assert len(m.regimes) == DEFAULT_K
    vols = [r.centre["vol_pctl_90d"] for r in m.regimes]
    assert vols == sorted(vols)  # calmest first
    assert vols[0] < 40 and vols[-1] > 60
    assert sum(r.share for r in m.regimes) == pytest.approx(1.0, abs=1e-6)


def test_descriptions_state_what_was_measured():
    m = build(two_regime_frame())
    calm, wild = m.regimes[0], m.regimes[-1]
    assert "calm" in calm.description
    assert "turbulent" in wild.description and "thin" in wild.description


def test_the_turbulent_regime_has_the_wider_outcome_band():
    m = build(two_regime_frame(), horizon_h=24)
    calm, wild = m.regimes[0], m.regimes[-1]
    assert calm.n_outcomes > 0 and wild.n_outcomes > 0
    assert (wild.next_ret_p95_pct - wild.next_ret_p5_pct) > (calm.next_ret_p95_pct - calm.next_ret_p5_pct)


def test_regimes_persist_and_the_matrix_is_a_distribution():
    m = build(two_regime_frame(), horizon_h=24)
    for row in m.transitions:
        assert sum(row) == pytest.approx(1.0, abs=1e-6) or sum(row) == 0.0
    # With five clusters over two true states, "same cluster a day later" is diluted by
    # the sibling clusters, so persistence is tested where the states map one to one.
    two = build(two_regime_frame(), k=2, horizon_h=24)
    assert all(r.persistence > 0.8 for r in two.regimes)  # blocks last 200 hours


def test_the_current_state_is_the_last_usable_hour():
    frame = two_regime_frame()
    m = build(frame)
    assert m.current is not None
    # The fixture's last block is a turbulent one, and that is what the map should say.
    assert m.regime(m.current).centre["vol_pctl_90d"] > 50


def test_nothing_after_the_as_of_can_shape_the_fit():
    frame = two_regime_frame()
    cut = frame.index[1000]
    early = build(frame, as_of=cut)
    assert early.n_fitted == 1001
    assert early.n_fitted < build(frame).n_fitted


def test_a_frame_without_the_state_columns_is_refused():
    frame = two_regime_frame().drop(columns=["vol_pctl_90d", "basis_index_z", "trend_sma_pct"])
    assert build(frame).note.startswith("not enough state columns")


def test_a_thin_regime_reports_no_outcome_statistics():
    """One far-away hour forms its own cluster; it must not pretend to have a distribution."""
    frame = two_regime_frame()
    frame.iloc[-1, frame.columns.get_loc("vol_pctl_90d")] = 1e6
    m = build(frame, k=DEFAULT_K)
    thin = [r for r in m.regimes if r.n_outcomes < 30]
    assert thin and all(r.next_ret_median_pct is None for r in thin)
