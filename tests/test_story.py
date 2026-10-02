"""What the verdict assumes and how the trade loses money: written by rules, from the
report's own numbers, and honest about the data it leans on."""

from dataclasses import replace

from nightwatch.decision import story
from tests.test_intake import _report
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture


def test_every_failure_mode_carries_a_cost_a_cause_and_how_often(seeded_store):  # noqa: F811
    r = _report(seeded_store, stop_price=None, thesis="t", invalidation="i")
    modes = story.failure_modes(r)
    assert modes, "a report with stress presets should have at least one way to lose"
    for m in modes:
        assert m.trigger and m.mechanism and m.likelihood and m.source and m.short
    # Ranked by expected loss where the chance was measured, then the rest by size, so the
    # brief and the panel lead with what is both likely and costly.
    known = [m.chance * m.loss_quote for m in modes if m.chance is not None and m.loss_quote is not None]
    assert known == sorted(known)
    first_unknown = next((i for i, m in enumerate(modes) if m.chance is None), len(modes))
    assert all(m.chance is None for m in modes[first_unknown:])


def test_a_stop_a_gap_can_jump_is_named(seeded_store):  # noqa: F811
    r = _report(seeded_store, thesis="t", invalidation="i")
    entry = r.snapshot.prices["spot_close"]
    tight = _report(seeded_store, stop_price=entry * 0.999, thesis="t", invalidation="i")
    worst = next((s for s in tight.stress.presets if s.id == "closed_window_gap_p1"), None)
    names = {m.key for m in story.failure_modes(tight)}
    if worst is not None and abs(worst.price_move_pct) > 0.1:
        assert "stop_jumped" in names
    assert "stop_jumped" not in {m.key for m in story.failure_modes(r)}  # no stop, nothing to jump


def test_assumptions_say_what_is_missing_as_a_caveat(seeded_store):  # noqa: F811
    r = _report(seeded_store, account_equity_quote=None, thesis="t", invalidation="i")
    by_topic = {a.topic: a for a in story.assumptions(r)}
    assert by_topic["account"].kind == "caveat" and "not given" in by_topic["account"].text
    assert "No leverage" in by_topic["leverage"].text
    assert "history" in by_topic and by_topic["history"].kind == "caveat"


def test_a_reason_that_leans_on_an_event_the_data_does_not_show_is_said(seeded_store):  # noqa: F811
    r = _report(seeded_store, thesis="post-earnings drift continues", invalidation="i")
    far = replace(r.snapshot, features={**r.snapshot.features, "hours_since_earnings": 720.0, "hours_to_earnings": 720.0})
    r.snapshot = far
    said = story.premise(r)
    assert said and "over 30 days" in said[0]
    near = replace(far, features={**far.features, "hours_since_earnings": 30.0})
    r.snapshot = near
    assert story.premise(r) == []
    r.ticket = replace(r.ticket, thesis="strength into the close")
    assert story.premise(r) == []  # nothing event-shaped, nothing to check


def test_the_report_and_the_brief_carry_them(seeded_store):  # noqa: F811
    from nightwatch.api import intake as it

    r = _report(seeded_store, thesis="t", invalidation="i")
    assert r.assumptions and r.failure_modes
    text = it.brief(r)
    assert "How this loses money:" in text
    assert "主要亏损方式" in it.brief(r, "zh")


def test_failure_modes_rank_by_chance_times_loss_and_stop_at_the_margin():
    """A 0% liquidation was listed first and an 83% one fifth; a 50x position with 200 USDT
    of margin was shown losing 2,995. Neither can happen."""
    from nightwatch.decision.story import FailureMode, _cap_at_margin, _rank

    def fm(key, loss, chance):  # noqa: ANN001, ANN202
        return FailureMode(key, key, "t", "m", loss, loss / 100, "l", "s", "x", chance)

    ranked = _rank([fm("rare_big", -2000.0, 0.01), fm("likely", -300.0, 0.6), fm("liquidation", -200.0, 0.0), fm("crisis", -3000.0, None)])
    assert [m.key for m in ranked] == ["likely", "rare_big", "liquidation", "crisis"]
    capped = _cap_at_margin([fm("crisis", -3000.0, None), fm("small", -50.0, 0.1)], {"margin_quote": 200.0, "leverage": 50.0, "liquidation_distance_pct": 1.9})
    assert capped[0].loss_quote == -200.0 and capped[0].capped and "liquidated first" in capped[0].mechanism
    assert capped[1].loss_quote == -50.0 and not capped[1].capped


def test_premise_covers_the_fed_data_releases_and_a_stop_past_the_invalidation(seeded_store):  # noqa: F811
    r = _report(seeded_store, thesis="the Fed will surprise hawkish and CPI runs hot", invalidation="i")
    r.snapshot = replace(r.snapshot, features={**r.snapshot.features, "hours_to_fomc": None, "macro_events_72h": 0.0})
    said = " ".join(story.premise(r))
    assert "no FOMC decision in the next 30 days" in said and "no scheduled release" in said
    entry = r.snapshot.prices["spot_close"]
    r.ticket = replace(r.ticket, thesis="t", stop_price=entry * 0.90)
    r.plan_check = {"kind": "level", "level": entry * 0.95, "already": False}
    assert any("beyond your own 'wrong if' level" in x for x in story.premise(r))


def test_a_leveraged_fund_says_what_it_is(seeded_store):  # noqa: F811
    r = _report(seeded_store, thesis="t", invalidation="i")
    r.ticket = replace(r.ticket, ticker="SQQQ")
    assert any(a.topic == "instrument" and "inverse" in a.text for a in story.assumptions(r))


def test_the_traders_own_line_is_a_measured_chain_not_a_template(seeded_store):  # noqa: F811
    """What history did after the trader's own invalidation broke, and how many went on to
    the stop - measured for this trade, not a sentence that reads the same on every one."""
    r = _report(seeded_store, thesis="t", invalidation="i")
    entry = r.snapshot.prices["spot_close"]
    r.plan_check = {"invalidation": "wrong if it closes below X", "kind": "level", "level": entry * 0.99, "distance_pct": -1.0, "crossed": 13, "of": 40, "already": False}
    mode = next(m for m in story.failure_modes(r) if m.key == "invalidation")
    assert mode.chance == 13 / 40 and "13 of 40" in mode.mechanism and "wrong if it closes below X" in mode.title
    r.street = {"token_vs_live_bps": 40.0}
    assert any(m.key == "convergence" for m in story.failure_modes(r))  # a long above the stock's price gives it up
    r.street = {"token_vs_live_bps": -40.0}
    assert not any(m.key == "convergence" for m in story.failure_modes(r))  # a discount helps a long


def test_failure_mode_loss_is_at_the_requested_size_with_the_recommended_beside_it():
    from dataclasses import replace

    from nightwatch.decision.story import FailureMode

    m = FailureMode("gap_bad", "t", "x", "y", -1000.0, -10.0, "l", "s")
    assert m.loss_quote_at_recommended is None
    assert replace(m, loss_quote_at_recommended=-200.0).to_dict()["loss_quote_at_recommended"] == -200.0
