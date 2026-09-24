"""The trader's plan, tested against the data where it can be.

The desk used to check only that a thesis and an invalidation were written. These pin
what it now does with them: read three shapes of invalidation it can measure, measure
them honestly, and say plainly when a sentence is not one it can test.
"""

from types import SimpleNamespace

import pandas as pd
import pytest

from nightwatch.decision import plan_check as pc

FRAME = pd.DataFrame({"spot_close": [90.0] * 360 + [110.0] * 360})  # 30-day average 100
PATHS = SimpleNamespace(paths=[
    SimpleNamespace(values=(0.0, -1.0, -6.0)),
    SimpleNamespace(values=(0.0, 2.0, 1.0)),
    SimpleNamespace(values=(0.0, -3.0, -2.0)),
    SimpleNamespace(values=(0.0, 5.0, 4.5)),
])


def run(inv, thesis="", long=True, price=105.0):  # noqa: ANN001, ANN202
    return pc.check(inv, thesis, long=long, price=price, frame=FRAME, paths=PATHS)


def test_a_price_level_is_measured_and_counted_against_the_paths():
    c = run("close below 100")
    assert c.kind == "level" and c.level == 100.0
    assert c.distance_pct == pytest.approx(-4.76, abs=0.01)
    assert (c.crossed, c.of) == (1, 4), "only the path that fell 6% reached it"


def test_the_30_day_average_is_the_desks_own_number():
    c = run("wrong if it loses the 30-day average")
    assert c.kind == "moving_average" and c.level == pytest.approx(100.0) and "30-day" in c.note


def test_another_length_of_average_is_computed_from_the_same_closes():
    c = run("below the 10 day moving average")
    assert c.kind == "moving_average" and c.level == pytest.approx(110.0), "the last 10 days all closed at 110"
    assert c.already, "at 105 a long is already under it"


def test_a_percentage_move_is_counted_against_the_paths():
    c = run("if it drops 5%")
    assert c.kind == "move" and c.distance_pct == -5.0 and (c.crossed, c.of) == (1, 4)
    short = run("if it rallies 4%", long=False)
    assert short.distance_pct == 4.0 and short.crossed == 1, "only the path that reached +5% got there"


def test_a_short_is_proved_wrong_by_a_rise():
    c = run("a close above 108", long=False)
    assert c.kind == "level" and c.crossed == 1


def test_a_level_on_the_wrong_side_is_called_a_target_not_counted():
    c = run("wrong if it gets above 120")
    assert c.kind == "wrong_side" and c.crossed is None
    assert "reads like a target" in pc.describe(c)


def test_a_sentence_it_cannot_read_is_said_to_be_untested():
    c = run("if the story changes")
    assert c.kind == "untested"
    assert "not something the desk can test" in pc.describe(c)


def test_a_number_that_is_not_a_price_is_not_taken_for_one():
    assert run("if nothing happens within 3 sessions").kind == "untested"


def test_a_reason_that_reads_against_the_position_is_flagged():
    assert "reads bearish, but the position is long" in run("close below 100", thesis="weakness into the close").thesis_mismatch
    assert run("close below 100", thesis="strength into the open").thesis_mismatch == ""
    assert "reads bullish" in run("above 108", thesis="breakout higher", long=False).thesis_mismatch
    assert run("close below 100", thesis="fade the weakness, then a rebound").thesis_mismatch == "", "mixed words are not a mismatch"


def test_no_plan_and_no_mismatch_is_nothing_to_say():
    assert pc.check("", "", long=True, price=100.0, frame=FRAME) is None


def test_the_chinese_description_carries_the_same_numbers():
    c = run("close below 100")
    assert "4.8%" in pc.describe(c) and "4.8%" in pc.describe(c, "zh")
