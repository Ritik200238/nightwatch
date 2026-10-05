"""The multiple-testing correction has to be right, and has to say so when it cannot be."""

from __future__ import annotations

import math

import pytest

from nightwatch.journal import fdr, lens_study
from nightwatch.journal.fdr import (
    NOT_A_TEST,
    annotate,
    bh_adjust,
    derive_p,
    one_sided_p_from_t,
    small_sample,
    two_sided_p_from_t,
)


def test_bh_matches_the_textbook_example():
    # R: p.adjust(c(0.01, 0.04, 0.03, 0.005), "BH") -> 0.02 0.04 0.04 0.02
    got = bh_adjust([0.01, 0.04, 0.03, 0.005])
    assert got == pytest.approx([0.02, 0.04, 0.04, 0.02])
    # Equal steps of alpha/m all adjust to the same value.
    assert bh_adjust([0.01, 0.02, 0.03, 0.04, 0.05]) == pytest.approx([0.05] * 5)


def test_bh_is_monotone_capped_and_order_preserving():
    p = [0.9, 0.0001, 0.2, 0.04, 0.5]
    q = bh_adjust(p)
    assert all(qi >= pi for qi, pi in zip(q, p, strict=True))
    assert max(q) <= 1.0
    order = sorted(range(len(p)), key=lambda i: p[i])
    assert [q[i] for i in order] == sorted(q)
    assert bh_adjust([]) == []


@pytest.mark.parametrize("t, df, p", [
    (2.0639, 24, 0.05),   # tabulated critical values
    (2.0687, 23, 0.05),
    (2.0930, 19, 0.05),
    (1.0, 1, 0.5),        # Cauchy: P(|T|>1) = 0.5
    (12.706, 1, 0.05),
    (0.0, 10, 1.0),
])
def test_student_t_p_matches_tables(t, df, p):
    assert two_sided_p_from_t(t, df) == pytest.approx(p, abs=5e-4)


def test_normal_approximation_and_edges():
    assert two_sided_p_from_t(1.959964, None) == pytest.approx(0.05, abs=1e-6)
    assert two_sided_p_from_t(float("nan"), 10) is None
    assert two_sided_p_from_t(None, 10) is None
    assert one_sided_p_from_t(2.0, 30) == pytest.approx(two_sided_p_from_t(2.0, 30) / 2)
    assert one_sided_p_from_t(-2.0, 30) > 0.5


def _study(key, verdict, n, stats):
    return {"key": key, "verdict": verdict, "n": n, "stats": stats, "title": key}


def test_clustered_studies_use_tokens_minus_one_degrees_of_freedom():
    s = _study("closer_is_not_tighter", "no", 958, {"clustered_t": -2.0687, "tokens": 24.0})
    p, how = derive_p(s)
    assert p == pytest.approx(0.05, abs=5e-4)
    assert "23 degrees of freedom" in how


def test_random_hours_takes_the_weaker_of_the_two_things_the_verdict_needs():
    st = {"clustered_t": 5.0, "tokens": 24.0, "mean_advantage": 0.01, "boot_ci_low": 0.0, "boot_ci_high": 0.02}
    p, how = derive_p(_study("analogs_beat_random_hours", "yes", 100, st))
    # The interval only just touches zero, so its normal-approximation p is about 0.05,
    # which is far weaker than the clustered t of 5.
    assert p == pytest.approx(0.05, abs=1e-3)
    assert "normal approximation" in how


def test_studies_that_are_not_tests_get_no_p_value():
    for key in ("one_factor_hid_two_errors", "online_calibration_adds_nothing"):
        p, how = derive_p(_study(key, "no", 2000, {"x": 1.0}))
        assert p is None and how.startswith(NOT_A_TEST)
    assert derive_p(_study("closer_is_not_tighter", "unclear", 0, {}))[0] is None


def test_missing_cluster_count_falls_back_to_a_lower_bound_and_says_so():
    st = {"clustered_t": 2.0, "n_called": 200.0, "hit_rate": 0.5}
    p, how = derive_p(_study("filing_read_calls_direction", "unclear", 200, st))
    assert p is not None and "token count not stored" in how


def test_narrowing_judges_only_conditions_with_enough_nights_and_corrects_for_them():
    st = {
        "a.n": 100.0, "a.t_clustered": 2.9, "a.tokens": 20.0,
        "b.n": 300.0, "b.t_clustered": 0.5, "b.tokens": 20.0,
        "tiny.n": 24.0, "tiny.t_clustered": 9.0, "tiny.tokens": 10.0,  # would win if it were judged
        "fomc.n": 3.0,
    }
    s = _study("narrowing_gives_a_truer_tail", "yes", 427, st)
    p, how = derive_p(s)
    p_a = two_sided_p_from_t(2.9, 19)
    assert p == pytest.approx(2 * p_a)  # two judged conditions, so the best is doubled
    assert "2 conditions" in how
    note = small_sample(s)
    assert note and "tiny (n=24)" in note and "fomc (n=3)" in note and "do not decide the verdict" in note


def test_small_sample_threshold_matches_the_one_the_lens_study_judges_by():
    assert fdr.SMALL_N == lens_study.MIN_PAIRS
    assert small_sample(_study("x", "yes", 29, {"a": 1.0})) is not None
    assert small_sample(_study("x", "yes", 30, {"a": 1.0})) is None


def test_annotate_is_additive_and_counts_yes_answers_that_survive():
    studies = [
        _study("closer_is_not_tighter", "yes", 900, {"clustered_t": 6.0, "tokens": 24.0}),
        _study("distance_does_not_warn", "yes", 900, {"clustered_t": 2.1, "tokens": 24.0}),
        _study("filing_read_predicts_size", "no", 600, {"clustered_t": 0.2, "tokens": 20.0}),
        _study("one_factor_hid_two_errors", "no", 2000, {"x": 1.0}),
    ]
    before = [dict(s) for s in studies]
    out, summary = annotate(studies)
    assert studies == before  # inputs untouched
    for o, b in zip(out, before, strict=True):
        assert all(o[k] == v for k, v in b.items())  # verdicts and stats unchanged
        assert {"p_value", "q_value", "survives_fdr", "small_sample", "small_sample_note", "p_method"} <= set(o)
    by = {o["key"]: o for o in out}
    assert by["one_factor_hid_two_errors"]["p_value"] is None and by["one_factor_hid_two_errors"]["survives_fdr"] is None
    assert by["closer_is_not_tighter"]["survives_fdr"] is True
    assert by["distance_does_not_warn"]["survives_fdr"] is False  # p ~ 0.047 alone, but q is above 0.05 with company
    assert summary["m_tests"] == 3 and summary["m_studies"] == 4
    assert summary["yes_total"] == 2 and summary["yes_survive"] == 1
    assert summary["yes_fail"] == ["distance_does_not_warn"]
    assert math.isclose(by["closer_is_not_tighter"]["q_value"], bh_adjust([o["p_value"] for o in out if o["p_value"] is not None])[0])


def test_adjusted_baseline_study_is_inside_the_correction_family():
    st = {"clustered_t": 3.0, "tokens": 24.0, "mean_advantage": 0.01, "boot_ci_low": 0.004, "boot_ci_high": 0.016}
    p, how = derive_p(_study("adjusted_analogs_beat_adjusted_baseline", "yes", 2000, st))
    assert p is not None and "night-bootstrap" in how
