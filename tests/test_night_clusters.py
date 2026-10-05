"""Night-clustered intervals, the method freeze holdout and de-duplicated misses."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nightwatch.journal.calibration import (
    MIN_NIGHTS,
    calibrate,
    count_nights,
    distinct_events,
    night_bootstrap_ci,
    tail_test,
    wilson_interval,
)
from nightwatch.journal.freeze import holdout


def _clustered(n_nights: int = 60, per_night: int = 24, rate: float = 0.05, seed: int = 1):
    """Whole nights breach together: every token on a bad night breaches at once."""
    rng = np.random.default_rng(seed)
    bad = rng.random(n_nights) < rate
    dates = pd.date_range("2026-03-01", periods=n_nights, tz="UTC")
    as_of = np.repeat(dates.to_numpy(), per_night)
    flags = np.repeat(bad, per_night).astype(float)
    return as_of, flags


def test_night_ci_is_wider_than_the_independent_interval_when_nights_cluster():
    as_of, flags = _clustered()
    k, n = int(flags.sum()), len(flags)
    w_lo, w_hi = wilson_interval(k, n)
    lo, hi = night_bootstrap_ci(as_of, flags)
    assert hi - lo > 2 * (w_hi - w_lo)
    assert count_nights(as_of) == 60


def test_night_ci_is_deterministic_and_none_with_few_nights():
    as_of, flags = _clustered()
    assert night_bootstrap_ci(as_of, flags) == night_bootstrap_ci(as_of, flags)
    few, f = _clustered(n_nights=MIN_NIGHTS - 1)
    assert night_bootstrap_ci(few, f) is None


def test_night_ci_matches_independent_case_when_every_forecast_is_its_own_night():
    rng = np.random.default_rng(4)
    n = 400
    as_of = pd.date_range("2025-01-01", periods=n, tz="UTC").to_numpy()
    flags = (rng.random(n) < 0.05).astype(float)
    lo, hi = night_bootstrap_ci(as_of, flags)
    w_lo, w_hi = wilson_interval(int(flags.sum()), n)
    assert abs((hi - lo) - (w_hi - w_lo)) < 0.02


def test_tail_test_carries_the_night_count():
    as_of, flags = _clustered()
    n = len(flags)
    p5 = np.full(n, -1.0)
    realised = np.where(flags > 0, -2.0, 0.5)
    t = tail_test(realised, p5, as_of=as_of)
    assert t.n_nights == 60 and t.night_ci is not None
    assert tail_test(realised, p5).n_nights is None


def test_calibrate_reports_nights_next_to_every_interval():
    as_of, flags = _clustered()
    n = len(flags)
    df = pd.DataFrame({"as_of": as_of, "ticker": "AAA", "ret_pct": np.where(flags > 0, -2.0, 0.5),
                       "p5": -1.0, "p25": -0.3, "p50": 0.0, "p75": 0.3, "p95": 1.0})
    rep = calibrate(df)
    assert all(c.n_nights == 60 for c in rep.coverage)
    assert rep.tail.n_nights == 60
    assert n == rep.n_matured


def test_distinct_events_collapses_repeated_tickets_on_one_outcome():
    g = pd.DataFrame({
        "ticker": ["CRCL"] * 4 + ["META", "TSLA"],
        "r": [-6.6056] * 4 + [-3.0, 1.0],
        "exit_ts": ["2026-10-01T14:30"] * 4 + ["2026-10-02", "2026-10-02"],
        "as_of": pd.to_datetime(["2026-09-30"] * 6, utc=True),
        "miss": [True] * 4 + [True, False],
    })
    d = distinct_events(g)
    assert d["distinct_events"] == 3 and d["distinct_missed"] == 2
    assert abs(d["distinct_rate"] - 2 / 3) < 1e-9
    assert g["miss"].sum() == 5  # the raw count is untouched


def _rows(dates, breach):
    return pd.DataFrame({"as_of": pd.to_datetime(dates, utc=True), "r": [-9.0 if b else 0.0 for b in breach],
                         "a5": -5.0, "a95": 5.0})


FREEZE = {"frozen_at": "2026-10-06T00:00:00+00:00", "git_tag": "t", "git_commit": "c", "note": "n"}


def test_holdout_counts_only_forecasts_made_after_the_freeze():
    days = ["2026-10-01", "2026-10-05", "2026-10-06", "2026-10-07"] * 6
    breach = [True, True, False, False] * 6
    out = holdout(_rows(days, breach), FREEZE)
    assert out["n"] == 12 and out["breaches"] == 0 and out["n_nights"] == 2
    assert out["night_ci"] is None  # two nights is not an interval


def test_holdout_is_empty_before_anything_matures():
    out = holdout(_rows(["2026-09-01", "2026-09-02"], [True, False]), FREEZE)
    assert out["n"] == 0 and out["rate"] is None
    assert holdout(pd.DataFrame(), FREEZE)["n"] == 0


def test_holdout_with_enough_nights_gives_both_intervals():
    days = list(pd.date_range("2026-10-06", periods=20, tz="UTC").strftime("%Y-%m-%d")) * 3
    breach = [i % 20 == 3 for i in range(60)]
    out = holdout(_rows(days, breach), FREEZE)
    assert out["n"] == 60 and out["n_nights"] == 20
    assert out["wilson_ci"] and out["night_ci"]
