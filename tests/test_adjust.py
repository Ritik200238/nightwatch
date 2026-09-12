from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.journal.adjust import apply_factors, evaluate_expanding, factors_as_of, fit_factors

UTC = UTC
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def synthetic(n: int = 300, seed: int = 0, narrow: float = 0.5) -> pd.DataFrame:
    """Forecasts whose tails are `narrow`× too tight: true sigma 2, predicted p5/p95 at ±1.645*2*narrow."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 2.0, n)
    p50 = np.zeros(n)
    p5 = p50 - 1.645 * 2.0 * narrow
    p95 = p50 + 1.645 * 2.0 * narrow
    as_of = [T0 + timedelta(hours=12 * i) for i in range(n)]
    return pd.DataFrame({"as_of": as_of, "horizon_end": [a + timedelta(hours=6) for a in as_of], "p5": p5, "p25": p5 / 2, "p50": p50, "p75": p95 / 2, "p95": p95, "ret_pct": r, "ticker": "X"})


def test_fit_recovers_the_widening_factor():
    f = fit_factors(synthetic(narrow=0.5))
    assert f is not None and 1.7 < f.k_lo < 2.4 and 1.7 < f.k_hi < 2.4  # true factor 2.0
    a5, a95 = apply_factors(-1.0, 0.0, 1.0, f)
    assert a5 < -1.5 and a95 > 1.5


def test_fit_narrows_when_forecasts_are_too_wide():
    f = fit_factors(synthetic(narrow=2.0))
    assert f is not None and f.k_lo < 0.7


def test_expanding_evaluation_is_out_of_sample_and_improves_coverage():
    ev = evaluate_expanding(synthetic(n=400, narrow=0.5))
    assert ev is not None and ev.n_evaluated > 300
    assert ev.raw_lo_coverage > 0.12  # too-narrow forecasts breach far more than 5%
    assert abs(ev.adj_lo_coverage - 0.05) < 0.03
    assert ev.adj_tail_band in ("green", "amber") and ev.raw_tail_band == "red"
    assert ev.adj_width > ev.raw_width


def test_factors_as_of_uses_only_matured_history():
    df = synthetic(n=100)
    assert factors_as_of(df, T0 + timedelta(hours=10)) is None  # nothing matured yet
    late = factors_as_of(df, T0 + timedelta(hours=12 * 99))
    assert late is not None and late.n_fit < 100  # the last forecast has not matured
