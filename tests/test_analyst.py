"""The analyst's take: what the model is given, what it is not allowed to add, and that
nobody waits for it."""

import threading
import time

from nightwatch.api import analyst

REPORT = {
    "ticket": {"ticker": "TSLA", "side": "long", "notional_quote": 20000.0, "stop_price": 350.0},
    "horizon_h": 95.0, "primary_horizon": "95h",
    "verdict": {"verdict": "GO", "recommended_notional": 20000.0}, "sizing": {"binding_cap": "regime"},
    "analog": {"horizons": {"95h": {"cohort": {"n": 40, "median_pct": -1.8, "p5": -4.0, "win_rate": 0.45}, "p5_adjusted": -4.6}},
               "paths": {"stop_pct": -7.6, "stopped": 4, "paths": [{}] * 40}, "lens": None},
    "plan_check": {"invalidation": "跌破360", "kind": "level", "distance_pct": -5.0, "crossed": 7, "of": 40},
    "stress": {"presets": [{"name": "Volatility spike x3"}], "impacts": [{"total_pnl_quote": -2147.0, "total_pct_of_notional": -10.7}],
               "inputs_summary": {"earnings_in_window": False}},
    "execution": {"exit_quote": {"total_cost_bps": 21.0}},
    "street": {"token_vs_live_bps": 36.0, "n_firms": 21, "bullish": 9, "neutral": 10, "bearish": 2, "median_target": 420.0, "mood_score": 35.0, "mood_rating": "fear"},
    "warnings": ["the native stock has not printed for three days"],
}


def test_the_fact_sheet_carries_the_decision_and_nothing_raw():
    sheet = analyst.fact_sheet(REPORT)
    for piece in ("GO", "40 similar past moments", "-4.6%", "4 of 40", "No earnings report", "21", "+36 bps", "Caveat"):
        assert piece in sheet, piece
    assert "p5" not in sheet.lower(), "plain words for the model, so plain words back"


def test_a_sentence_with_an_invented_number_is_removed():
    sheet = analyst.fact_sheet(REPORT)
    text = "The call\nA GO at 20,000 USDT.\nWhat matters most tonight\nA bad night loses 4.6%. Tesla will rally 12% by Monday."
    clean, removed = analyst.strip_unverified(text, sheet)
    assert removed == 1 and "12%" not in clean and "4.6%" in clean and "20,000" in clean


class FakeProvider:
    model = "fake"

    def __init__(self, text="The call\\nGO at 20,000 USDT.", delay=0.0):  # noqa: ANN001
        self.text, self.delay, self.calls = text.replace("\\n", "\n"), delay, []

    def write(self, *, system, user, max_tokens=1500):  # noqa: ANN001, ANN003, ANN201
        self.calls.append(system)
        time.sleep(self.delay)
        return self.text


def test_starting_a_take_returns_at_once_and_it_arrives_later():
    jobs = analyst.AnalystJobs()
    p = FakeProvider(delay=0.3)
    t0 = time.time()
    first = jobs.start(1, REPORT, p)
    assert first.status == "pending" and time.time() - t0 < 0.2
    for _ in range(50):
        if jobs.get(1).status == "done":
            break
        threading.Event().wait(0.05)
    assert jobs.get(1).status == "done" and "GO" in jobs.get(1).text


def test_asking_twice_does_not_write_twice():
    jobs = analyst.AnalystJobs()
    p = FakeProvider(delay=0.2)
    jobs.start(2, REPORT, p)
    jobs.start(2, REPORT, p)
    threading.Event().wait(0.5)
    assert len(p.calls) == 1


def test_chinese_is_asked_for_in_chinese():
    jobs = analyst.AnalystJobs()
    p = FakeProvider()
    jobs.start(3, REPORT, p, "zh")
    threading.Event().wait(0.3)
    assert "Simplified Chinese" in p.calls[0] and "结论" in p.calls[0]


def test_without_a_model_the_take_says_so():
    assert analyst.AnalystJobs().start(4, REPORT, None).status == "unavailable"


def test_the_nested_levels_are_stated_the_right_way_round():
    """The model once read "7 crossed 360, 4 reached 350" as "once 360 breaks it runs to
    350". The sheet now says what the counts mean, so there is nothing to invert."""
    rel = analyst.relations(REPORT)
    assert any("of the 7 that crossed the invalidation, 4 went on to the stop and 3 turned back" in x for x in rel)


def test_the_bad_night_is_placed_against_each_level():
    rel = " ".join(analyst.relations(REPORT))
    assert "stops short of the stop" in rel and "about the same distance as the invalidation" in rel


def test_a_gap_that_jumps_the_stop_is_said():
    assert any("could jump past the stop" in x for x in analyst.relations(REPORT))


def test_the_sheet_carries_the_relations_and_the_instruction_to_use_them():
    assert "Computed relations" in analyst.fact_sheet(REPORT)
    assert "use them as given" in analyst.SYSTEM_EN and "use them as given" in analyst.SYSTEM_ZH


def test_no_stop_and_no_plan_means_no_level_relations():
    r = {**REPORT, "ticket": {**REPORT["ticket"], "stop_price": None}, "plan_check": None}
    assert not any("stop" in x or "invalidation" in x for x in analyst.relations(r))
