"""The studies have to be able to come out the other way.

A study whose verdict is written into the code is a claim wearing a lab coat. These
build evidence where the answer is known and the opposite of what our own data gave,
and check the verdict follows the numbers rather than the narrative.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.data.store import Store
from nightwatch.journal.studies import (
    NO,
    UNCLEAR,
    YES,
    Evidence,
    Study,
    StudyStore,
    study_analogs_beat_random_hours,
    study_closer_is_not_tighter,
    study_distance_does_not_warn,
    study_one_factor_hid_two_errors,
    study_weighting_does_not_help,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
TOKENS = [f"T{i}" for i in range(12)]


def evidence(*, closer_is_tighter: bool, truth_from: str = "near", k: int = 40, per_token: int = 12, seed: int = 0) -> Evidence:
    """Retrieval evidence with a known answer.

    Each moment gets ``k`` matches. Half sit near and half far; whichever half is meant
    to be the calm one gets outcomes drawn from a narrow distribution, the other wide.

    ``truth_from`` is the part that decides whether weighting should help. With
    ``"near"`` the near matches really are the representative ones and leaning on them
    ought to win. With ``"pooled"`` the realised outcome follows the whole cohort, so
    leaning on a near half that happens to be wide overstates the tail - which is the
    shape our own data turned out to have.
    """
    rng = np.random.default_rng(seed)
    q_rows, m_rows, qid = [], [], 0
    for tok in TOKENS:
        for j in range(per_token):
            near_sd, far_sd = (1.0, 3.0) if closer_is_tighter else (3.0, 1.0)
            truth_sd = near_sd if truth_from == "near" else float(np.sqrt((near_sd**2 + far_sd**2) / 2))
            for i in range(k):
                near = i < k // 2
                m_rows.append({
                    "qid": qid, "m_ticker": tok if i % 8 == 0 else TOKENS[(i + 1) % len(TOKENS)],
                    "distance": float(rng.uniform(0.5, 1.5) if near else rng.uniform(3.0, 5.0)),
                    "similarity": 0.9 if near else 0.1,
                    "ret_pct": float(rng.normal(0, near_sd if near else far_sd)),
                    "same_ticker": int(i % 8 == 0),
                })
            q_rows.append({
                "qid": qid, "ticker": tok, "as_of": (T0 + timedelta(days=j)).isoformat(),
                "horizon_h": 18, "bucket": "weeknight", "regime": "mixed",
                "n_matches": k, "distance_scale": 1.0,
                "truth_ret_pct": float(rng.normal(0, truth_sd)),
            })
            qid += 1
    return Evidence(pd.DataFrame(q_rows), pd.DataFrame(m_rows))


def test_the_verdict_follows_the_data_not_the_narrative():
    """Our own data said no. Evidence built the other way must say yes."""
    yes = study_closer_is_not_tighter(evidence(closer_is_tighter=True))
    assert yes.verdict == YES, yes.finding
    assert yes.stats["sd_ratio_near_over_far"] < 1.0
    assert "yes" in yes.finding.lower()

    no = study_closer_is_not_tighter(evidence(closer_is_tighter=False))
    assert no.verdict == NO, no.finding
    assert no.stats["sd_ratio_near_over_far"] > 1.0
    assert "wider" in no.finding


def test_a_wash_is_reported_as_a_wash():
    """Equal spreads in both halves must not be read as a finding in either direction."""
    rng = np.random.default_rng(7)
    ev = evidence(closer_is_tighter=True)
    ev.matches["ret_pct"] = rng.normal(0, 2.0, len(ev.matches))
    assert study_closer_is_not_tighter(ev).verdict == UNCLEAR


def test_weighting_is_credited_when_it_actually_helps():
    """If the near matches are the calm, representative ones, leaning on them should
    win - and the study has to be able to say so."""
    helped = study_weighting_does_not_help(evidence(closer_is_tighter=True, truth_from="near", seed=3))
    # Near matches that are wide while the real outcome follows the whole cohort: the
    # shape our own data has, where leaning on the close ones overstates the tail.
    hurt = study_weighting_does_not_help(evidence(closer_is_tighter=False, truth_from="pooled", seed=3))
    assert helped.verdict in (YES, UNCLEAR)
    assert hurt.verdict == NO, hurt.finding
    # And the numbers behind the sentence are present either way.
    assert "breach_equal" in hurt.stats and "pinball_equal" in hurt.stats


def test_a_between_token_effect_does_not_count_as_a_warning():
    """Volatile tokens have far analogs and big moves for unrelated reasons. Pooled
    that looks like a signal; per token it must not."""
    rng = np.random.default_rng(11)
    ev = evidence(closer_is_tighter=True, seed=5)
    # Give each token its own volatility, and scale both its distances and its outcome
    # with it, so the pooled correlation is strong and the within-token one is nil.
    vol = {t: 0.5 + 3.0 * (i / len(TOKENS)) for i, t in enumerate(TOKENS)}
    ev.queries["truth_ret_pct"] = [rng.normal(0, vol[t]) for t in ev.queries["ticker"]]
    scale = ev.queries.set_index("qid")["ticker"].map(vol)
    ev.matches["distance"] = ev.matches["distance"] * ev.matches["qid"].map(scale).to_numpy()
    s = study_distance_does_not_warn(ev)
    assert s.verdict in (NO, UNCLEAR), s.finding
    assert s.stats["clustered_t"] < s.stats["pooled_t"]


# ------------------------------------------------------------------ journal studies


def forecasts(n: int = 900, *, split: bool, seed: int = 4) -> pd.DataFrame:
    """Matured forecasts over two holding periods.

    With ``split`` the two periods need opposite corrections, so one factor cannot
    serve both; without it they need the same one and a split buys nothing.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        at = T0 + timedelta(hours=8 * i)
        long_hold = i % 3 == 0
        narrow = (2.0 if long_hold else 0.5) if split else 0.5
        p5, p95 = -1.645 * 2.0 * narrow, 1.645 * 2.0 * narrow
        rows.append({
            "ticker": TOKENS[i % len(TOKENS)], "as_of": at, "horizon_end": at + timedelta(hours=2),
            "horizon_h": 66.0 if long_hold else 18.0,
            "p5": p5, "p25": p5 / 2, "p50": 0.0, "p75": p95 / 2, "p95": p95,
            "ret_pct": float(rng.normal(0, 2.0)),
            "base_p5": p5 * 1.5, "base_p50": 0.0, "base_p95": p95 * 1.5,
        })
    return pd.DataFrame(rows)


def test_one_factor_is_credited_when_one_factor_is_enough():
    same = study_one_factor_hid_two_errors(forecasts(split=False))
    assert same.verdict == YES, same.finding
    split = study_one_factor_hid_two_errors(forecasts(split=True))
    assert split.verdict == NO, split.finding
    assert split.stats["pooled_width_multi_day"] > split.stats["banded_width_multi_day"]


def test_the_baseline_can_win():
    """If the stored baseline is the better forecast, the study has to say so rather
    than reporting an edge the numbers do not show."""
    df = forecasts(split=False)
    # Make the baseline the well-calibrated one and the analogs far too tight.
    df["base_p5"], df["base_p95"] = -1.645 * 2.0, 1.645 * 2.0
    df["p5"], df["p95"] = -0.2, 0.2
    s = study_analogs_beat_random_hours(df)
    assert s.verdict == NO, s.finding
    assert s.stats["mean_advantage"] < 0


def test_results_round_trip_through_the_store(tmp_path):
    s = Study(key="k", title="t", question="q", method="m", finding="f", consequence="c", verdict=YES, n=3, stats={"a": 1.5})
    with Store(tmp_path / "s.sqlite") as store:
        ss = StudyStore(store)
        assert ss.last_run() is None
        assert ss.save([s]) == 1
        got = ss.all()
        assert len(got) == 1 and got[0]["title"] == "t" and got[0]["stats"]["a"] == 1.5
        assert ss.last_run() is not None
        # Re-running replaces rather than duplicating.
        ss.save([Study(**{**s.to_dict(), "finding": "different"})])
        assert len(ss.all()) == 1 and ss.all()[0]["finding"] == "different"
