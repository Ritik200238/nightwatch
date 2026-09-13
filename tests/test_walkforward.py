"""Walk-forward: the same point-in-time scoring, split into periods."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.journal.walkforward import MIN_PERIOD_N, by_period, render

START = datetime(2026, 1, 1, tzinfo=UTC)


def forecasts(n: int, *, width: float = 4.0, shock_from: int | None = None, seed: int = 5) -> pd.DataFrame:
    """Daily forecasts of a standard-normal outcome, optionally with a regime shift."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        at = START + timedelta(days=i)
        scale = 3.0 if (shock_from is not None and i >= shock_from) else 1.0
        r = float(rng.normal(0, scale))
        rows.append({
            "id": i, "ticker": "TSLA", "as_of": at, "horizon_end": at + timedelta(hours=12),
            "p5": -1.645 * width / 4, "p25": -0.674 * width / 4, "p50": 0.0, "p75": 0.674 * width / 4,
            "p95": 1.645 * width / 4, "ret_pct": r,
        })
    return pd.DataFrame(rows)


def test_no_periods_without_enough_history():
    wf = by_period(forecasts(10))
    assert wf.periods == [] and "not enough" in wf.note


def test_each_month_is_scored_separately_and_thin_ones_are_marked():
    wf = by_period(forecasts(120))
    # Scoring starts once enough forecasts have matured to fit on, so January is partial.
    assert [p.label for p in wf.periods] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert wf.periods[0].thin and not wf.periods[1].thin
    assert all(p.n > 0 for p in wf.periods)
    assert wf.n_total == sum(p.n for p in wf.periods)
    thin = [p for p in wf.periods if p.n < MIN_PERIOD_N]
    assert all(p.thin for p in thin)


def test_a_regime_shift_shows_up_as_a_worse_period():
    """Volatility triples half way through; the months after must breach more."""
    wf = by_period(forecasts(180, shock_from=90))
    calm = [p for p in wf.periods if p.label in ("2026-02", "2026-03")]
    wild = [p for p in wf.periods if p.label in ("2026-05", "2026-06")]
    assert calm and wild
    assert max(p.raw_lo_coverage for p in calm) < min(p.raw_lo_coverage for p in wild)


def test_the_adjustment_widens_the_band_it_reports():
    wf = by_period(forecasts(150, width=2.0))  # far too narrow on purpose
    late = wf.periods[-1]
    assert late.adj_width > late.raw_width
    assert late.adj_band_coverage >= late.raw_band_coverage
    assert late.k_lo > 1.0


def test_weekly_buckets_and_rendering():
    wf = by_period(forecasts(120), freq="W")
    assert len(wf.periods) > len(by_period(forecasts(120)).periods)
    text = render(wf)
    assert "WALK-FORWARD" in text and wf.periods[0].label in text
    assert render(by_period(forecasts(5))).startswith("WALK-FORWARD: not enough")


def test_skill_is_none_without_a_journalled_baseline():
    wf = by_period(forecasts(120))
    assert all(p.skill is None for p in wf.periods)


def test_skill_appears_when_the_baseline_is_there():
    df = forecasts(150)
    for q, k in (("p5", -1.645), ("p25", -0.674), ("p50", 0.0), ("p75", 0.674), ("p95", 1.645)):
        df[f"base_{q}"] = k * 3.0  # a much wider, worse baseline
    wf = by_period(df)
    scored = [p for p in wf.periods if p.skill is not None]
    assert scored and all(p.skill > 0 for p in scored)


def test_a_trend_is_only_called_with_enough_full_periods():
    assert by_period(forecasts(60)).improving is None
    wf = by_period(forecasts(300))
    assert wf.improving in (True, False) and "per period" in wf.note
