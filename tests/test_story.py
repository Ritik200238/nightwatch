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
    # Ranked worst first, so the brief and the panel lead with what matters most.
    losses = [m.loss_quote for m in modes if m.loss_quote is not None]
    assert losses == sorted(losses)


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
