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
