"""Questions about a report, answered out of the report.

The claim these tests defend is narrow and worth defending exactly: every number in an
answer is a field of the report it was asked about. So most of them change a field and
insist the answer follows, which a hardcoded or invented number could not do.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from nightwatch.api.followup import Answer, answer, answer_or_menu, looks_like_a_question
from nightwatch.api.intake import is_a_new_idea

FIXTURE = Path(__file__).parent / "data" / "report.json"


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def numbers(text: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


# --- what it will and will not take on ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["why not bigger?", "What if I do 40k", "how bad can it get", "can I get out", "talk me out of it", "Is this reliable?", "should I hedge"],
)
def test_a_question_is_recognised(text):
    assert looks_like_a_question(text)


@pytest.mark.parametrize("text", ["long 25k TSLA overnight", "short 5k NVDA for 12 hours", "hold 20k of MSFT"])
def test_a_trade_idea_is_not_a_question(text):
    assert not looks_like_a_question(text)


def test_a_different_token_starts_a_new_analysis(report):
    known = ["TSLA", "NVDA", "MSFT"]
    # Even without a side: the right answer to "what about NVDA" is to ask which way,
    # not to keep talking about TSLA.
    assert is_a_new_idea("what about 15k of NVDA?", report, known)
    assert is_a_new_idea("short 10k MSFT instead", report, known)
    assert not is_a_new_idea("what if I do 40k", report, known)
    assert not is_a_new_idea("why not bigger for TSLA?", report, known)


# --- the answers follow the report -------------------------------------------------------


def test_why_not_bigger_names_the_cap_that_binds(report):
    r = copy.deepcopy(report)
    r["ticket"]["notional_quote"] = 100_000.0
    r["sizing"]["binding_cap"] = "concentration"
    for c in r["sizing"]["caps"]:
        c["notional"] = 50_000.0 if c["name"] == "concentration" else 90_000.0
    got = answer(r, "why not bigger?")
    assert got and got.kind == "size"
    assert "concentration" in got.text and "50,000" in got.text

    r["sizing"]["binding_cap"] = "exit_liquidity"
    for c in r["sizing"]["caps"]:
        c["notional"] = 12_345.0 if c["name"] == "exit_liquidity" else 90_000.0
    again = answer(r, "why not bigger?")
    assert again and "exit liquidity" in again.text and "12,345" in again.text


def test_a_size_question_is_answered_from_the_sweep(report):
    r = copy.deepcopy(report)
    r["sensitivity"]["sizes"] = [
        {"notional": 10_000.0, "verdict": "GO", "gate": "GO", "binding_cap": "regime", "recommended_notional": 10_000.0, "worst_severe_pct": -4.0, "exit_cost_bps": 11.0, "risk_pct_of_equity": 0.2},
        {"notional": 40_000.0, "verdict": "NO_GO", "gate": "NO_GO", "binding_cap": "exit_liquidity", "recommended_notional": 0.0, "worst_severe_pct": -4.0, "exit_cost_bps": 62.0, "risk_pct_of_equity": 0.9},
    ]
    got = answer(r, "what if I do 40k")
    assert got and got.kind == "size"
    assert "40,000" in got.text and "NO GO" in got.text and "62.0 bps" in got.text
    assert "the nearest size" not in got.text  # it ran exactly that size


def test_a_size_the_sweep_did_not_run_says_which_one_it_quotes(report):
    r = copy.deepcopy(report)
    r["sensitivity"]["sizes"] = [{"notional": 37_455.0, "verdict": "GO", "gate": "GO", "binding_cap": None, "recommended_notional": 37_455.0, "worst_severe_pct": -4.0, "exit_cost_bps": 16.0, "risk_pct_of_equity": 0.7}]
    got = answer(r, "what if I do 40k")
    assert got and "the nearest size the sweep ran to your 40,000 USDT" in got.text


def test_a_stop_question_is_answered_from_the_sweep(report):
    r = copy.deepcopy(report)
    r["sensitivity"]["stops"] = [
        {"stop_distance_pct": 2.0, "stop_price": 350.0, "verdict": "GO", "gate": "GO", "risk_pct_of_equity": 0.2, "risk_budget_notional": 100_000.0},
        {"stop_distance_pct": 6.0, "stop_price": 330.0, "verdict": "NO_GO", "gate": "NO_GO", "risk_pct_of_equity": 1.4, "risk_budget_notional": 14_000.0},
    ]
    got = answer(r, "what if my stop were 6%")
    assert got and got.kind == "stop"
    assert "6.00%" in got.text and "330.00" in got.text and "NO GO" in got.text


def test_the_worst_case_is_the_worst_preset_by_money(report):
    r = copy.deepcopy(report)
    r["stress"]["presets"] = [{"id": "a", "name": "Quiet gap"}, {"id": "b", "name": "Earnings rout"}]
    r["stress"]["impacts"] = [
        {"total_pnl_quote": -500.0, "total_pct_of_notional": -2.5},
        {"total_pnl_quote": -9_000.0, "total_pct_of_notional": -45.0},
    ]
    got = answer(r, "what is the worst case")
    assert got and got.kind == "worst"
    # The rout leads, because it costs more money, and the number is the report's.
    assert got.text.index("Earnings rout") < got.text.index("Quiet gap")
    assert "9,000 USDT" in got.text


def test_getting_out_quotes_the_book(report):
    r = copy.deepcopy(report)
    r["execution"]["exit_quote"] = {"notional_quote": 20_000.0, "total_cost_bps": 42.5, "total_cost_quote": 85.0, "fully_filled": True}
    r["execution"]["max_notional_within_budget"] = 77_000.0
    got = answer(r, "can I get out?")
    assert got and got.kind == "exit"
    assert "42.5 bps" in got.text and "85 USDT" in got.text and "77,000" in got.text


def test_a_book_that_cannot_absorb_the_size_says_so(report):
    r = copy.deepcopy(report)
    r["execution"]["exit_quote"] = {"notional_quote": 20_000.0, "total_cost_bps": None, "total_cost_quote": None, "fully_filled": False}
    got = answer(r, "can I get out?")
    assert got and "cannot absorb this size at any price" in got.text


def test_the_gate_answer_lists_only_what_failed(report):
    r = copy.deepcopy(report)
    r["gate"]["rules"] = [
        {"rule": "written_plan", "decision": "GO", "reason": "thesis and invalidation stated"},
        {"rule": "exit_liquidity", "decision": "NO_GO", "reason": "exit would cost 62 bps (limit 50)"},
    ]
    got = answer(r, "why not?")
    assert got and got.kind == "gate"
    assert "exit liquidity" in got.text and "62 bps" in got.text
    assert "written plan" not in got.text


def test_nothing_failed_says_so_and_points_at_the_caps(report):
    r = copy.deepcopy(report)
    r["gate"]["rules"] = [{"rule": "written_plan", "decision": "GO", "reason": "stated"}]
    got = answer(r, "why did you say that?")
    assert got and "Nothing in the gate objected" in got.text


def test_lessons_lead_with_the_ones_that_breached(report):
    r = copy.deepcopy(report)
    r["lessons"] = [
        {"classification": "as_expected", "text": "TSLA closed inside the band."},
        {"classification": "worse_than_stress", "text": "TSLA long from 22 Jul closed -13.53%."},
    ]
    got = answer(r, "has this burned me before?")
    assert got and got.kind == "lessons"
    assert "1 finished below the level they were sized against" in got.text
    assert "-13.53%" in got.text


def test_no_matured_lesson_is_said_plainly_rather_than_guessed(report):
    r = copy.deepcopy(report)
    r["lessons"] = []
    got = answer(r, "what happened last time?")
    assert got and "nothing to learn from directly" in got.text


def test_a_question_it_cannot_answer_offers_what_it_can(report):
    got = answer_or_menu(report, "what is the capital of France?")
    assert got.kind == "menu"
    assert "why the size is what it is" in got.text


# --- the claim itself --------------------------------------------------------------------

QUESTIONS = [
    "why not bigger?",
    "what if I do 40k",
    "what if my stop were 6%",
    "what is the worst case",
    "can I get out?",
    "what happened last time?",
    "why not?",
    "talk me out of it",
    "should I hedge",
    "what kind of market is this",
    "how do I know this works",
    "how many past moments were there",
    "show me the moments",
    "what is the price right now",
]


@pytest.mark.parametrize("question", QUESTIONS)
def test_every_answer_is_a_string_about_this_report(report, question):
    got = answer_or_menu(report, question)
    assert isinstance(got, Answer)
    assert got.text and len(got.text) > 20
    assert "None" not in got.text  # a missing field must be worded, not printed


# Three answers pass the report's own sentences through rather than formatting its
# numbers: the case against, the post-mortems, and the gate's reasons. Their numbers live
# inside those strings, so they are checked by quotation instead.
QUOTES_THE_REPORT = {"against", "lessons", "gate"}


def test_the_case_against_is_quoted_not_composed(report):
    got = answer(report, "talk me out of it")
    assert got and got.kind == "against"
    for point in (report["second_opinion"]["against"] or [])[:2]:
        assert point["text"] in got.text


def test_a_lesson_is_quoted_verbatim(report):
    got = answer(report, "what happened last time?")
    assert got and got.kind == "lessons"
    texts = [x["text"] for x in report["lessons"]]
    assert not texts or any(t in got.text for t in texts)


def test_a_failed_rule_is_quoted_verbatim(report):
    r = copy.deepcopy(report)
    r["gate"]["rules"] = [{"rule": "exit_liquidity", "decision": "NO_GO", "reason": "exit would cost 62 bps (limit 50)"}]
    got = answer(r, "why not?")
    assert got and "exit would cost 62 bps (limit 50)" in got.text


@pytest.mark.parametrize("question", QUESTIONS)
def test_the_answer_moves_when_the_report_moves(report, question):
    """A number that is really being read from the report changes when the report does.
    Anything hardcoded, remembered or invented would sit still."""
    original = answer_or_menu(report, question)
    if original.kind == "menu":
        pytest.skip("the menu is the same whatever the report says")
    if original.kind in QUOTES_THE_REPORT:
        pytest.skip("this one quotes the report's own sentences; covered above")

    shifted = copy.deepcopy(report)

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                node[k] = walk(v) if not isinstance(v, (int, float)) or isinstance(v, bool) else v * 1.37 + 3
        elif isinstance(node, list):
            return [walk(x) for x in node]
        return node

    walk(shifted)
    moved = answer_or_menu(shifted, question)
    assert moved.text != original.text, f"{question!r} did not follow the report"


def test_the_engine_reads_nothing_but_the_dict_it_is_given(report):
    """No database, no market data, no model: an empty report degrades to the menu
    rather than reaching for anything else."""
    got = answer_or_menu({}, "what is the worst case")
    assert got.kind == "menu"
    assert numbers(got.text) == []
