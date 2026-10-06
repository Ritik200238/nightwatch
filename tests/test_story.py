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
    # Largest loss first: the list is headed "worst first", so the first card is the worst one.
    losses = [m.loss_quote for m in modes if m.loss_quote is not None]
    assert losses == sorted(losses)
    assert modes[0].loss_quote == min(losses)


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


def test_failure_modes_rank_by_loss_largest_first_and_stop_at_the_margin():
    """A 0% liquidation was listed first and an 83% one fifth; a 50x position with 200 USDT
    of margin was shown losing 2,995. Neither can happen. The list says "worst first", so it is
    ordered by loss: a -833 gap must not head a list that holds a -2,843 crash replay."""
    from nightwatch.decision.story import FailureMode, _cap_at_margin, _rank

    def fm(key, loss, chance):  # noqa: ANN001, ANN202
        return FailureMode(key, key, "t", "m", loss, loss / 100, "l", "s", "x", chance)

    ranked = _rank([fm("rare_big", -2000.0, 0.01), fm("likely", -300.0, 0.6), fm("liquidation", -200.0, 0.0), fm("crisis", -3000.0, None)])
    assert [m.key for m in ranked] == ["crisis", "rare_big", "likely", "liquidation"]
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


def test_the_report_payload_carries_chinese_names_for_failure_modes_and_presets():
    from nightwatch.pipeline.analyze import _add_zh_names

    out = {"failure_modes": [{"key": "halt", "title": "Stuck for 24 hours"}, {"key": "nope", "title": "x"}],
           "stress": {"presets": [{"id": "closed_window_gap_p95", "name": "Closed-window gap, 95th percentile"},
                                  {"id": "replay_covid_2020", "name": "Replay: COVID crash"}]}}
    _add_zh_names(out)
    assert out["failure_modes"][0]["title_zh"] == "24 小时无法平仓" and "title_zh" not in out["failure_modes"][1]
    assert out["stress"]["presets"][0]["name_zh"].startswith("休市期间跳空")
    assert "2020" in out["stress"]["presets"][1]["name_zh"]


def test_a_known_probability_note_gets_a_chinese_line_and_an_unknown_one_does_not():
    from nightwatch.pipeline.analyze import _add_zh_names

    out = {"stress": {"presets": [
        {"id": "closed_window_gap_p95", "name": "n", "probability_note": "5% of 438 past runs of 3 closed windows were worse for this side"},
        {"id": "x", "name": "n", "probability_note": "something nobody translated"}]}}
    _add_zh_names(out)
    p = out["stress"]["presets"]
    assert "438" in p[0]["probability_note_zh"] and "5%" in p[0]["probability_note_zh"]
    assert "probability_note_zh" not in p[1]


def test_stress_assumptions_say_what_the_replays_and_the_spike_do_not_model(seeded_store):  # noqa: F811
    from types import SimpleNamespace

    r = _report(seeded_store, thesis="t", invalidation="i")
    r.stress = SimpleNamespace(presets=[SimpleNamespace(id="replay_covid_2020"), SimpleNamespace(id="vol_spike_x2")], monte_carlo=object())
    by_topic = {a.topic: a for a in story.assumptions(r)}
    assert "did not exist" in by_topic["crash replays"].text and by_topic["crash replays"].kind == "caveat"
    assert "weekend" in by_topic["volatility spike"].text
    assert "not yet scored" in by_topic["monte carlo"].text
    r.stress = SimpleNamespace(presets=[], monte_carlo=None)
    assert not {"crash replays", "volatility spike", "monte carlo"} & {a.topic for a in story.assumptions(r)}


def test_every_assumption_a_report_writes_has_a_chinese_line():
    # The live NVDA weekend report's own 13 lines, as written by story.assumptions.
    from nightwatch.decision.zh import assumption_zh

    lines = [
        "Held for 66 hours (the coming weekend, Friday's close to Monday's open), then closed.",
        "Held for 21 hours, to the next US regular open, then closed.",
        "Entered at the token's last price, 242.46, as of 06 Oct 14:00 UTC.",
        "No leverage: a plain token position. Say \"5x\" to test it on the perpetual.",
        "5x on the Bitget perpetual, isolated margin, maintenance margin 0.66% from Bitget's tier for this size.",
        "The perp is priced off the token's path; the gap between the two is shocked separately by the basis presets.",
        "Stop at 170.00. A resting stop fills at the next price there is, so a gap can fill it worse than the stop.",
        "No stop: the risk is sized on the calibrated 1-in-20 loss instead.",
        "Account of 200,000 USDT; the size limits are shares of it.",
        "Account size not given, so the size limits that depend on it are not checked.",
        "The 80 past moments compared against run from Jun 2025 to Oct 2026, across 1 token; the future is assumed to resemble them only as much as the calibration page shows it has.",
        "The crash replays apply NVDA's own stock move from those crises to today's token. The token did not exist then (only the April 2025 shock overlaps its life), so basis, thin night books and listing effects were not part of what was replayed. The five windows were picked after the fact.",
        "The 2σ and 3σ spike scales volatility by the square root of the hours held over a 24-hour, seven-day year, which counts weekend and overnight hours as if they traded like the day. Over a weekend that is not true; read the sigma label as approximate.",
        "The Monte Carlo band redraws blocks of this token's own past hourly returns and adds up the hours held. It uses only hours the token traded, with no volatility scaling for weekends or news, and it is recorded but not yet scored against outcomes the way the 1-in-20 line is.",
        "TQQQ is a 3x leveraged Nasdaq-100 fund that resets daily: over more than a day it does not return 3x the index, and a choppy market erodes it.",
        "Fair value is Bitget's index for the stock; the token sits -9 bps from it now.",
        "Exit cost is walked on the recorded order book at 15:58 UTC, taker fee on both legs; a thinner book at exit is a separate stress preset.",
        "Exit cost is walked on the live order book, taker fee on both legs; a thinner book at exit is a separate stress preset.",
        "Earnings fall inside the hold (in 3 days); the earnings-gap presets are included.",
        "No earnings inside the hold (no earnings in the next 30 days).",
        "No earnings inside the hold (next in 9 days).",
        "Earnings timing is not known (no upcoming date on the earnings calendar), so the earnings-gap presets are not tied to this hold.",
        "Dividends and splits were not checked: the calendar has not been synced yet.",
        "No ex-dividend date or split inside the hold in the stored calendar (Nasdaq, Yahoo, Bitget notices).",
    ]
    for en in lines:
        zh = assumption_zh(en)
        assert zh and any("一" <= c <= "鿿" for c in zh), en
    assert "66 小时" in assumption_zh(lines[0]) and "周五收盘到周一开盘" in assumption_zh(lines[0])
    assert assumption_zh("something the desk never wrote") is None
