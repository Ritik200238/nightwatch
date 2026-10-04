"""Leverage: the liquidation price from Bitget's tiers, and the gate's reading of how
often history reached it."""

import numpy as np
import pytest

from nightwatch.execution import leverage as lv

ROWS = [
    {"startUnit": "0", "endUnit": "10000", "leverage": "100", "keepMarginRate": "0.0050"},
    {"startUnit": "10000", "endUnit": "50000", "leverage": "75", "keepMarginRate": "0.0070"},
    {"startUnit": "50000", "endUnit": "100000", "leverage": "50", "keepMarginRate": "0.0100"},
    {"startUnit": "750000", "endUnit": "3000000", "leverage": "10", "keepMarginRate": "0.0500"},
]


def test_the_tier_is_chosen_by_position_size():
    tiers = lv.parse_tiers(ROWS)
    assert lv.tier_for(tiers, 5_000).mmr == 0.005 and lv.tier_for(tiers, 20_000).max_leverage == 75
    assert lv.tier_for(tiers, 5_000_000).max_leverage == 10  # beyond the table, the last tier


def test_liquidation_price_long_and_short():
    # 5x long at 100 with 0.7% maintenance and 0.06% taker: margin runs out ~20% down, a
    # little sooner because the maintenance margin has to be left over.
    long_ = lv.liquidation_price(100.0, 5.0, long=True, mmr=0.007, taker_fee=0.0006)
    short = lv.liquidation_price(100.0, 5.0, long=False, mmr=0.007, taker_fee=0.0006)
    assert long_ == pytest.approx(80.0 / (1 - 0.0076)) and 80 < long_ < 81
    assert short == pytest.approx(120.0 / (1 + 0.0076)) and 119 < short < 120
    # At the liquidation price the margin left equals the maintenance plus closing fee.
    qty = 1.0
    margin_left = 100.0 / 5 + (long_ - 100.0) * qty
    assert margin_left == pytest.approx(long_ * qty * 0.0076)


def test_leverage_above_the_tier_limit_is_refused():
    v = lv.assess(leverage=100.0, notional=900_000, entry=100.0, long=True, perp_symbol="TSLAUSDT", tiers=lv.parse_tiers(ROWS), taker_fee=0.0006)
    assert not v.allowed and lv.gate_rule(v, -3.0)[0] == "NO_GO"


def test_no_perp_means_no_leverage():
    v = lv.assess(leverage=5.0, notional=20_000, entry=100.0, long=True, perp_symbol=None, tiers=None, taker_fee=0.0006)
    assert lv.gate_rule(v, -3.0) == ("NO_GO", "no Bitget perpetual for this stock, so it cannot be held with leverage")


def test_missing_tiers_are_assumed_and_said():
    v = lv.assess(leverage=5.0, notional=20_000, entry=100.0, long=True, perp_symbol="TSLAUSDT", tiers=None, taker_fee=0.0006)
    assert v.tiers_source == "assumed" and v.mmr == lv.FALLBACK_MMR and any("assumed" in n for n in v.notes)


def _view(distance_hits: int, of: int = 40, presets=None, p5=-2.0):  # noqa: ANN001, ANN202
    v = lv.assess(leverage=10.0, notional=20_000, entry=100.0, long=True, perp_symbol="TSLAUSDT", tiers=lv.parse_tiers(ROWS), taker_fee=0.0006)
    lv.attach_history(v, analog_hits=distance_hits, analog_of=of, preset_moves=presets or {}, mc_worst_pct=np.array([-1.0, -2.0, -30.0]))
    return lv.gate_rule(v, p5), v


def test_the_gate_reads_history_against_the_liquidation_level():
    assert _view(0)[0][0] == "GO"
    assert _view(1)[0][0] == "REVIEW_REQUIRED"  # one past moment in forty got there
    assert _view(2)[0][0] == "NO_GO"  # one in twenty: the same bar as every other loss
    assert _view(0, presets={"Closed-window gap, 1st percentile": -12.0})[0][0] == "REVIEW_REQUIRED"
    assert _view(0, p5=-15.0)[0][0] == "NO_GO"  # the calibrated bad night reaches it
    _, v = _view(0)
    assert v.mc_share == pytest.approx(1 / 3)


# --- the safety ladder -------------------------------------------------------------

def _ladder(requested, worst, *, notional=10_000, p5=-3.0, moves=None, tiers="rows", long=True):
    return lv.safety_ladder(
        requested=requested, notional=notional, entry=100.0, long=long, perp_symbol="TSLAUSDT",
        tiers=lv.parse_tiers(ROWS) if tiers == "rows" else tiers, taker_fee=0.0006,
        worst_adverse=worst, preset_moves=moves or {}, p5_loss_pct=p5,
    )


def test_ladder_has_the_standard_levels_plus_the_requested_one_sorted_and_deduplicated():
    rungs, _, _ = _ladder(4.0, [0.5] * 10)
    assert [r.leverage for r in rungs] == [2.0, 3.0, 4.0, 5.0, 10.0, 20.0]
    rungs, _, _ = _ladder(5.0, [0.5] * 10)
    assert [r.leverage for r in rungs] == [2.0, 3.0, 5.0, 10.0, 20.0]
    assert [r.requested for r in rungs] == [False, False, True, False, False]


def test_ladder_drops_levels_bitget_will_not_allow_at_this_size_but_keeps_the_requested_one():
    # 900k notional sits in the 10x tier: 20x is out, a requested 25x stays to be refused.
    rungs, _, _ = _ladder(25.0, [0.5] * 10, notional=900_000)
    assert [r.leverage for r in rungs] == [2.0, 3.0, 5.0, 10.0, 25.0]
    assert rungs[-1].gate == "NO_GO"


def test_each_rung_has_its_own_margin_price_and_count():
    # Worst moves against us: three past moments went 6%, 12% and 30% against.
    rungs, _, _ = _ladder(10.0, [6.0, 12.0, 30.0], p5=-1.0)
    by = {r.leverage: r for r in rungs}
    assert by[5.0].margin_quote == pytest.approx(2_000) and by[10.0].margin_quote == pytest.approx(1_000)
    assert by[5.0].liquidation_price == pytest.approx(lv.liquidation_price(100.0, 5.0, long=True, mmr=0.007, taker_fee=0.0006))
    # 2x liquidates ~49% down, 3x ~32%, 5x ~19.5%, 10x ~9.5%, 20x ~4.5%.
    assert [by[x].analog_hits for x in (2.0, 3.0, 5.0, 10.0, 20.0)] == [0, 0, 1, 2, 3]
    assert all(r.analog_of == 3 for r in rungs)


def test_a_rung_is_graded_by_the_same_rule_as_the_gate():
    rungs, _, _ = _ladder(10.0, [6.0, 12.0, 30.0] + [0.0] * 37, p5=-1.0)
    for r in rungs:
        view = lv.assess(leverage=r.leverage, notional=10_000, entry=100.0, long=True, perp_symbol="TSLAUSDT", tiers=lv.parse_tiers(ROWS), taker_fee=0.0006)
        lv.attach_history(view, analog_hits=r.analog_hits, analog_of=r.analog_of, preset_moves={}, mc_worst_pct=None)
        assert lv.gate_rule(view, -1.0)[0] == r.gate


def test_safest_is_the_highest_level_where_nothing_was_liquidated_and_p5_stops_short():
    # Worst move 12%: 10x (9.5% away) is hit, 5x (19.5% away) is not.
    rungs, safest, extra = _ladder(10.0, [12.0] + [1.0] * 39, p5=-2.0)
    assert safest == 5.0
    assert extra == pytest.approx(10_000 / 5 - 10_000 / 10)
    assert {r.leverage: r.gate for r in rungs}[10.0] != "GO"


def test_the_one_in_twenty_loss_reaching_the_liquidation_price_rules_a_level_out():
    # No past moment got there, but the calibrated p5 is a 25% loss: 5x (19.5%) is out, 3x (32%) is fine.
    _, safest, _ = _ladder(10.0, [1.0] * 40, p5=-25.0)
    assert safest == 3.0


def test_a_severe_preset_downgrades_a_level_to_review():
    rungs, safest, _ = _ladder(10.0, [1.0] * 40, p5=-2.0, moves={"gap down": -15.0})
    by = {r.leverage: r for r in rungs}
    assert by[10.0].presets_hit == ["gap down"] and by[10.0].gate == "REVIEW_REQUIRED"
    assert safest == 5.0


def test_no_extra_margin_when_the_requested_level_is_already_safe():
    _, safest, extra = _ladder(3.0, [1.0] * 40, p5=-2.0)
    assert safest is not None and safest >= 3.0 and extra is None


def test_no_safe_level_is_claimed_without_the_drawn_paths_or_when_none_qualifies():
    rungs, safest, extra = _ladder(5.0, None)
    assert rungs and safest is None and extra is None and all(r.analog_hits is None for r in rungs)
    _, safest, extra = _ladder(5.0, [60.0] * 40)  # every moment fell 60%: even 2x is wiped out
    assert safest is None and extra is None


def test_a_short_is_measured_against_the_upside_liquidation():
    rungs, _, _ = _ladder(5.0, [25.0], long=False, p5=-1.0)
    by = {r.leverage: r for r in rungs}
    assert by[5.0].liquidation_price > 100.0 and by[5.0].analog_hits == 1  # ~19.8% away, 25% went against
    assert by[3.0].analog_hits == 0


def test_no_perp_means_no_ladder():
    assert lv.safety_ladder(requested=5.0, notional=10_000, entry=100.0, long=True, perp_symbol=None, tiers=None,
                            taker_fee=0.0006, worst_adverse=[1.0], preset_moves={}, p5_loss_pct=-2.0) == ([], None, None)


def test_the_ladder_lands_on_the_view_and_in_its_json():
    rungs, safest, extra = _ladder(10.0, [12.0] + [1.0] * 39, p5=-2.0)
    v = lv.assess(leverage=10.0, notional=10_000, entry=100.0, long=True, perp_symbol="TSLAUSDT", tiers=lv.parse_tiers(ROWS), taker_fee=0.0006)
    assert v.ladder == [] and v.safest_leverage is None  # defaults
    lv.attach_ladder(v, rungs, safest, extra)
    d = v.to_dict()
    assert d["safest_leverage"] == 5.0 and d["safest_extra_margin_quote"] == pytest.approx(1_000)
    assert d["ladder"][0]["leverage"] == 2.0 and set(d["ladder"][0]) >= {"liquidation_price", "distance_pct", "margin_quote", "analog_hits", "analog_of", "p5_reaches", "gate", "requested"}
