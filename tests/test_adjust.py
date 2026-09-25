from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.journal.adjust import apply_factors, evaluate_expanding, expanding_rows, factors_as_of, fit_factors

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
    assert late is not None and late.pooled is not None
    assert late.pooled.n_fit < 100  # the last forecast has not matured


def test_a_horizon_gets_the_factor_fitted_on_its_own_window_length():
    """Two window lengths whose tails are wrong by different amounts.

    One pooled factor has to split the difference and is wrong for both; the point of
    bands is that each horizon is corrected by what its own kind of window did.
    """
    short = synthetic(n=400, seed=1, narrow=0.5)  # p5/p95 half as wide as they should be
    short["horizon_h"] = 18.0
    long_ = synthetic(n=400, seed=2, narrow=2.0)  # and twice as wide as they should be
    long_["horizon_h"] = 66.0
    long_["ticker"] = "Y"
    df = pd.concat([short, long_], ignore_index=True).sort_values("as_of").reset_index(drop=True)

    f = factors_as_of(df, T0 + timedelta(hours=12 * 799))
    assert f is not None
    assert set(f.bands) == {"overnight", "multi_day"}
    assert f.bands["overnight"].k_lo > 1.5  # needs widening
    assert f.bands["multi_day"].k_lo < 0.7  # needs narrowing
    # And the caller gets the right one for the horizon it asks about.
    assert f.for_hours(18.0).scope == "overnight"
    assert f.for_hours(66.0).scope == "multi_day"
    # A horizon we cannot place, or none at all, falls back rather than guessing.
    assert f.for_hours(None) is f.pooled


def test_a_thin_band_borrows_the_pooled_factor_instead_of_fitting_on_noise():
    df = synthetic(n=400, narrow=0.5)
    df["horizon_h"] = 18.0
    df.loc[df.index[:20], "horizon_h"] = 66.0  # far below MIN_BAND_N
    f = factors_as_of(df, T0 + timedelta(hours=12 * 399))
    assert f is not None and "multi_day" not in f.bands
    assert f.for_hours(66.0) is f.pooled


def test_banding_changes_nothing_when_the_horizon_was_never_recorded():
    """The journal did not always store a horizon; those rows must behave as before."""
    df = synthetic(n=400, narrow=0.5)
    banded = evaluate_expanding(df)
    flat = evaluate_expanding(df, banded=False)
    assert banded is not None and flat is not None
    assert banded.adj_lo_coverage == flat.adj_lo_coverage
    assert banded.bands == []


def test_the_pooled_number_can_hide_two_opposite_errors():
    """The reason bands exist, as a test.

    Half the forecasts are far too narrow and half far too wide. Scored together under
    one factor the breach rate lands near target while neither half is near it; scored
    per band, both halves are.
    """
    short = synthetic(n=500, seed=3, narrow=0.45)  # tails far too tight
    short["horizon_h"] = 18.0
    long_ = synthetic(n=500, seed=4, narrow=1.6)  # tails far too wide
    long_["horizon_h"] = 66.0
    # Interleave rather than overlap, so a row can be traced back to its own band.
    long_["as_of"] = long_["as_of"] + timedelta(hours=6)
    long_["horizon_end"] = long_["horizon_end"] + timedelta(hours=6)
    df = pd.concat([short, long_], ignore_index=True).sort_values("as_of").reset_index(drop=True)

    flat = evaluate_expanding(df, banded=False)
    assert flat is not None and flat.bands == []
    rows = expanding_rows(df, banded=False).merge(df[["as_of", "horizon_h"]], on="as_of", how="left")
    assert len(rows) == flat.n_evaluated  # the join stayed one to one
    per = {h: (g["r"] < g["a5"]).mean() for h, g in rows.groupby("horizon_h")}
    # One pooled fit cannot serve both. The margin rescues the short band, but only by
    # pinning the factor at its floor, so the long band stays absurdly wide and the
    # overall rate sits well under target: two wrongs, no longer averaging to look right.
    assert flat.k_lo_last == 0.5 and flat.c_lo_last is not None and flat.c_lo_last > 1.0
    assert flat.adj_lo_coverage < 0.035
    assert per[66.0] < 0.01  # the long band never breaches, because its band is absurd

    banded = evaluate_expanding(df)
    assert banded is not None
    named = {b.band: b for b in banded.bands}
    assert {"overnight", "multi_day"} <= set(named)
    for name in ("overnight", "multi_day"):
        assert abs(named[name].adj_lo_coverage - 0.05) < 0.02, f"{name} still off target"
    # The over-wide band is narrowed, not widened - a factor below 1 has to be reachable.
    assert named["multi_day"].adj_width < named["multi_day"].raw_width
    assert named["multi_day"].k_lo < 1.0 < named["overnight"].k_lo
    # Roughly halved here, which is the size of the error the pooled factor was hiding.
    assert named["multi_day"].adj_width < 0.7 * per_band_width(rows, 66.0)


def per_band_width(rows: pd.DataFrame, horizon_h: float) -> float:
    g = rows[rows["horizon_h"] == horizon_h]
    return float((g["a95"] - g["a5"]).mean())


def test_a_uniform_error_gets_no_floor():
    """When every forecast is too narrow by the same factor, the factor alone fixes it
    and the margin must come out zero, so the fit is exactly the old one-parameter fit."""
    f = fit_factors(synthetic(narrow=0.5))
    assert f is not None and f.c_lo == 0.0


def test_narrow_forecasts_get_an_absolute_floor():
    """Half the forecasts are stated far too narrow and half about right, with the same
    real spread underneath. A factor alone lands on target overall while the narrow half
    keeps breaching; the margin puts the narrow half on target as well."""
    rng = np.random.default_rng(7)
    n = 1200
    narrow_row = np.arange(n) % 2 == 0
    # Stated tail 0.3 against a real sigma of 1.2 (far too tight) next to 2.0 against
    # 2.0 (too tight by the usual 1.645). One factor cannot fix both: the exact fit is
    # k = 0.78 with a margin of 1.74 points, well inside the clamps.
    r = rng.normal(0, np.where(narrow_row, 1.2, 2.0), n)
    p50 = np.zeros(n)
    width = np.where(narrow_row, 0.3, 2.0)
    df = pd.DataFrame({
        "as_of": [T0 + timedelta(hours=6 * i) for i in range(n)], "p5": p50 - width, "p25": p50 - width / 2, "p50": p50,
        "p75": p50 + width / 2, "p95": p50 + width, "ret_pct": r, "ticker": "X",
    })
    df["horizon_end"] = df["as_of"] + timedelta(hours=3)
    f = fit_factors(df)
    assert f is not None and 1.0 < f.c_lo < 2.5 and 0.5 < f.k_lo < 1.2
    a5 = (df["p50"] + f.k_lo * (df["p5"] - df["p50"]) - f.c_lo).to_numpy()
    for half in (narrow_row, ~narrow_row):
        assert abs((r[half] < a5[half]).mean() - 0.05) < 0.02
    assert abs((r < a5).mean() - 0.05) < 0.02
    # The factor alone could not have done this: solved on its own for 5% overall, it
    # leaves the narrow half breaching several times too often.
    from nightwatch.journal.adjust import _coverage_lo, _solve

    k_alone = _solve(0.05, _coverage_lo, p50, df["p5"].to_numpy(), r)
    assert _coverage_lo(k_alone, p50[narrow_row], df["p5"].to_numpy()[narrow_row], r[narrow_row]) >= 0.09  # about twice the target
    rows = expanding_rows(df)
    assert (rows["c_lo"] > 0).mean() > 0.9  # the margin is in force out of sample too
    ev = evaluate_expanding(df)
    assert ev is not None and ev.c_lo_last is not None and ev.c_lo_last > 1.0
