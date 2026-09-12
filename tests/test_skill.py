"""Skill scoring: pinball loss, paired bootstrap, and the journal's baseline columns."""

from datetime import UTC

import numpy as np
import pandas as pd

from nightwatch.journal.skill import compare_skill, pinball


def test_pinball_is_the_quantile_loss():
    y = np.array([1.0, -1.0])
    q = np.array([0.0, 0.0])
    assert np.allclose(pinball(y, q, 0.05), [0.05, 0.95])
    assert np.allclose(pinball(y, q, 0.95), [0.95, 0.05])


def _frame(n: int, analog_width: float, base_width: float, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    y = rng.normal(0, 1, n)
    z = {"p5": -1.645, "p25": -0.674, "p50": 0.0, "p75": 0.674, "p95": 1.645}
    df = pd.DataFrame({"ticker": ["T"] * n, "ret_pct": y})
    for q, k in z.items():
        df[q] = k * analog_width
        df[f"base_{q}"] = k * base_width
    return df


def test_sharper_correct_distribution_shows_positive_skill():
    rep = compare_skill(_frame(400, analog_width=1.0, base_width=3.0))
    assert rep.n == 400 and rep.skill is not None and rep.skill > 0
    assert rep.diff_ci_low > 0  # analog beats baseline with confidence
    assert rep.by_ticker["T"] > 0


def test_identical_forecasts_have_zero_skill_and_too_few_rows_refuse():
    rep = compare_skill(_frame(100, 1.0, 1.0))
    assert rep.skill == 0.0 and rep.win_share == 0.0
    assert compare_skill(_frame(10, 1.0, 2.0)).skill is None
    assert compare_skill(pd.DataFrame({"ret_pct": [1.0]})).skill is None  # no baseline columns


def test_journal_migrates_baseline_columns_and_resets_replays(tmp_path):
    import sqlite3
    from datetime import datetime

    from nightwatch.data.store import Store
    from nightwatch.journal.journal import Journal

    path = tmp_path / "j.sqlite"
    # An older database without the baseline columns.
    with sqlite3.connect(path) as c:
        c.executescript("CREATE TABLE forecasts (id INTEGER PRIMARY KEY, created_at INTEGER NOT NULL, kind TEXT NOT NULL, ticker TEXT NOT NULL, side TEXT NOT NULL, notional REAL NOT NULL, as_of INTEGER NOT NULL, bar_ts INTEGER NOT NULL, horizon_h REAL NOT NULL, horizon_end INTEGER NOT NULL, entry_price REAL NOT NULL, snapshot_hash TEXT NOT NULL, analog_n INTEGER, analog_scope TEXT, p5 REAL, p25 REAL, p50 REAL, p75 REAL, p95 REAL, es5 REAL, mc_p5 REAL, mc_p95 REAL, verdict TEXT, recommended_notional REAL, payload TEXT NOT NULL);")
    with Store(path) as s:
        j = Journal(s)
        now = datetime(2026, 9, 1, tzinfo=UTC)
        q = {"p5": -2.0, "p25": -1.0, "p50": 0.0, "p75": 1.0, "p95": 2.0}
        b = {"p5": -3.0, "p25": -1.5, "p50": 0.0, "p75": 1.5, "p95": 3.0}
        for kind in ("replay", "replay", "ticket"):
            j.record_forecast(kind=kind, ticker="TSLA", side="long", notional=1.0, as_of=now, bar_ts=now, horizon_h=1.0, entry_price=100.0, snapshot_hash="h", analog_n=40, analog_scope="same_ticker", quantiles=q, es5=None, mc_p5=None, mc_p95=None, verdict=None, recommended_notional=None, payload={}, baseline_quantiles=b)
        df = j.forecasts()
        assert list(df["base_p5"]) == [-3.0, -3.0, -3.0]
        assert j.delete_replays("TSLA") == 2
        assert len(j.forecasts()) == 1 and j.forecasts()["kind"].iloc[0] == "ticket"
