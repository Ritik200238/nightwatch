"""The second opinion: the case against the verdict, from the report's own numbers."""

from types import SimpleNamespace

from nightwatch.decision.devil import build


def stub(**over):
    """A report-shaped object with only the fields the second opinion reads."""
    cohort = SimpleNamespace(insufficient=False, p5=-5.0, es5_pct=-7.0, es5_n=2, win_rate=0.4, n=40)
    horizon = SimpleNamespace(
        cohort=cohort, p5_adjusted=-6.0,
        baseline=SimpleNamespace(permutation_p_value=0.5, mean_diff_pct=-0.1),
    )
    scenario = SimpleNamespace(name="Earnings gap: worst observed", probability_note="worst of 4 past reactions")
    impact = SimpleNamespace(total_pct_of_notional=-9.0)
    base = dict(
        verdict=SimpleNamespace(verdict=SimpleNamespace(value="GO"), recommended_notional=10_000.0),
        ticket=SimpleNamespace(notional_quote=10_000.0, ticker="TSLA"),
        primary_horizon="24h",
        analog=SimpleNamespace(horizons={"24h": horizon}),
        stress=SimpleNamespace(
            presets=[scenario], impacts=[impact],
            monte_carlo=SimpleNamespace(prob_loss_gt={5.0: 0.11}, expected_shortfall_5_pct=-8.0),
        ),
        execution=SimpleNamespace(
            exit_quote=SimpleNamespace(total_cost_bps=30.0), hedge_quote=SimpleNamespace(total_cost_bps_of_position=12.0),
            liquidity_history=SimpleNamespace(buckets=[SimpleNamespace(bucket="weekend", thin=False, share_below_reference=0.4)]),
        ),
        sizing=SimpleNamespace(caps=[SimpleNamespace(name="exit_liquidity", notional=8_000.0)]),
        sensitivity=SimpleNamespace(max_go_notional=9_000.0),
        portfolio=SimpleNamespace(mean_correlation_to_book=0.8),
        regimes=None,
        lessons=[{"classification": "worse_than_stress"}, {"classification": "as_expected"}],
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_it_leads_with_the_biggest_money_loss():
    so = build(stub())
    assert so.against[0].source == "stress presets"  # 9% of 10,000 beats everything else
    assert "900" in so.against[0].text
    assert [c.magnitude_quote for c in so.against if c.magnitude_quote] == sorted(
        [c.magnitude_quote for c in so.against if c.magnitude_quote], reverse=True
    )


def test_every_point_names_where_it_came_from():
    so = build(stub())
    assert all(c.source for c in so.against)
    sources = {c.source for c in so.against}
    assert {"stress presets", "analog cohort", "order book", "Monte Carlo"} <= sources


def test_the_calibrated_tail_is_the_one_quoted_with_how_far_past_it_went():
    so = build(stub())
    tail = next(c for c in so.against if "One time in twenty" in c.text)
    assert "6.0%" in tail.text  # the adjusted p5, not the raw -5.0
    assert "-7.0%" in tail.text and "2 episodes" in tail.text  # and the shortfall beyond it


def test_a_weak_baseline_is_held_against_it():
    so = build(stub())
    assert any("resemblance may be doing nothing" in c.text for c in so.against)


def test_a_correlated_book_and_a_thin_archive_are_both_raised():
    so = build(stub())
    assert any("moves with what you already hold" in c.text for c in so.against)
    assert any("could not absorb this size" in c.text for c in so.against)


def test_a_refusal_gets_the_case_for_taking_it():
    so = build(stub(verdict=SimpleNamespace(verdict=SimpleNamespace(value="NO_GO"), recommended_notional=0.0)))
    assert so.summary.startswith("The desk says no")
    assert any("passes every check" in c.text for c in so.supporting)
    assert any("straight go" in c.text for c in so.supporting)


def test_a_winning_setup_is_reported_as_support_not_opposition():
    s = stub()
    s.analog.horizons["24h"].cohort.win_rate = 0.7
    so = build(s)
    assert any("70% of those moments ended positive" in c.text for c in so.supporting)
    assert not any("ended positive" in c.text for c in so.against)


def test_a_thin_report_still_produces_something():
    bare = stub(analog=None, stress=SimpleNamespace(presets=[], impacts=[], monte_carlo=None),
                execution=SimpleNamespace(exit_quote=None, hedge_quote=None, liquidity_history=None),
                portfolio=None, sensitivity=None, lessons=[])
    so = build(bare)
    assert so.summary and isinstance(so.against, list)


def test_a_review_says_so():
    so = build(stub(verdict=SimpleNamespace(verdict=SimpleNamespace(value="REVIEW"), recommended_notional=None)))
    assert "cannot decide yet" in so.summary
