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
    # A handful of things worth asking, not a paragraph listing every section.
    assert "why?" in got.text and "explain it simply" in got.text and len(got.text) < 200


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


def test_street_questions_are_answered_from_bitgets_data_and_said_to_be_context():
    from nightwatch.api import followup as fu

    r = {"street": {"token_vs_live_bps": 5.6, "token_vs_close_bps": -63.0, "n_firms": 12, "bullish": 5, "neutral": 5, "bearish": 2,
                    "median_target": 360.0, "target_gap_pct": -4.7, "insider_sells": 3, "insider_buys": 0,
                    "insider_sold_value": 2_100_000.0, "insider_bought_value": 0.0, "mood_score": 34.6, "mood_rating": "fear"}}
    a = fu.answer(r, "what do analysts think?")
    assert a.kind == "street" and "12 analyst firms" in a.text and "$360" in a.text
    assert "None of this moved the size" in a.text
    assert fu.answer(r, "are insiders selling?").kind == "street"


def test_a_report_without_street_data_says_why():
    from nightwatch.api import followup as fu

    a = fu.answer({"street": None}, "what do analysts think?")
    assert a.kind == "street" and "no street data" in a.text


def test_chinese_questions_are_recognised_and_answered_in_chinese():
    from nightwatch.api import followup as fu
    from nightwatch.api import followup_zh as zh

    assert fu.looks_like_a_question("风险大吗？") and fu.looks_like_a_question("为什么需要复核")
    r = {"primary_horizon": "8h", "analog": {"horizons": {"8h": {"cohort": {"n": 40, "median_pct": 0.2, "win_rate": 0.55}, "p5_adjusted": -3.3}}},
         "gate": {"rules": [{"rule": "written_plan", "decision": "REVIEW_REQUIRED", "reason": "missing thesis"}]},
         "verdict": {"verdict": "REVIEW"}}
    h = zh.answer(r, "历史上怎么样？")
    assert h.kind == "history" and "40" in h.text and "-3.3%" in h.text
    g = zh.answer(r, "为什么需要复核？")
    assert g.kind == "gate" and "书面计划" in g.text and "要通过复核" in g.text
    assert zh.answer_or_menu(r, "天气如何").kind == "menu"


# --- the questions a judge asked that used to get the menu ---------------------------------


def test_a_named_shock_is_priced_from_the_position(report):
    """"What if TSLA gaps down 10% at the open?" returned "I could not find that"."""
    got = answer(report, "what if TSLA gaps down 10% at the open?")
    assert got is not None and got.kind == "shock"
    notional = report["ticket"]["notional_quote"]
    assert f"{notional * 0.10:,.0f}" in got.text  # the loss is the position's own arithmetic
    up = answer(report, "what if it rallies 5%?")
    assert up is not None and up.kind == "shock" and "makes about" in up.text


def test_a_shock_through_the_stop_says_the_stop_is_jumped(report):
    r = copy.deepcopy(report)
    entry = r["snapshot"]["prices"]["spot_close"]
    r["ticket"]["stop_price"] = entry * 0.97
    r.setdefault("analog", {}).setdefault("paths", {})["stop_pct"] = -3.0
    got = answer(r, "what if it gaps down 10%?")
    assert got is not None and "through your stop" in got.text


def test_halving_and_doubling_are_sizes(report):
    requested = report["ticket"]["notional_quote"]
    half = answer(report, "what if I halve it?")
    double = answer(report, "double it?")
    assert half is not None and half.kind == "size" and double is not None and double.kind == "size"
    assert "Nothing cuts" not in half.text
    assert f"{requested / 2:,.0f}" in half.text or "nearest size" in half.text


def test_a_bare_why_explains_the_verdict(report):
    got = answer(report, "why?")
    assert got is not None and got.kind == "why"
    assert report["verdict"]["verdict"].replace("_", " ") in got.text


def test_a_question_about_the_reason_gets_the_calendar(report):
    got = answer(report, "is my thesis supported? when were earnings?")
    assert got is not None and got.kind == "premise" and "earnings" in got.text.lower()


def test_what_could_go_wrong_leads_with_the_failure_modes(report):
    r = copy.deepcopy(report)
    r["failure_modes"] = [{
        "key": "gap_worst", "title": "A severe gap at the reopen", "trigger": "News lands while the US market is shut",
        "mechanism": "the stock reopens at a new price", "loss_quote": -1234.0, "loss_pct": -6.2,
        "likelihood": "1% of 400 past closed windows were worse", "source": "stress presets", "short": "x",
    }]
    got = answer(r, "what could go wrong?")
    assert got is not None and "A severe gap at the reopen" in got.text and "1,234" in got.text


def test_why_the_moments_are_similar_is_answered(report):
    r = copy.deepcopy(report)
    r["analog"]["result"]["matches"] = [
        {"ts": o["ts"], "alike_on": ["vol_pctl_90d", "trend_sma_pct", "hours_to_fomc"], "differs_on": ["news_count_24h"]}
        for o in r["analog"]["matches_outcomes"]
    ]
    got = answer(r, "why are these moments similar?")
    assert got is not None and got.kind == "moments" and "What makes them similar" in got.text and "news flow" in got.text


@pytest.mark.parametrize("text", ["halve it", "double it", "use 5x", "hold it until Wednesday", "no leverage", "减半"])
def test_an_instruction_without_a_question_mark_is_about_the_report(text):
    """"halve it" used to be read as a fresh trade and re-ran the same size in silence."""
    assert looks_like_a_question(text)


def test_halving_in_chinese_reads_the_size_sweep(report):
    from nightwatch.api import followup_zh

    got = followup_zh.answer(report, "仓位减半呢")
    assert got is not None and got.kind == "size" and "结论为" in got.text


def test_the_chinese_questions_a_judge_found_broken_are_answered(report):
    """The product's own suggestion "如果跌 10% 呢" returned the menu, "会出什么问题" too,
    and "这些时刻为什么相似" got the gate answer."""
    from nightwatch.api import followup_zh

    r = copy.deepcopy(report)
    r["failure_modes"] = [{"key": "gap_worst", "title": "A severe gap at the reopen", "trigger": "t", "mechanism": "m",
                           "loss_quote": -1234.0, "loss_pct": -6.2, "likelihood": "l", "source": "s", "short": "x", "chance": 0.01, "capped": False}]
    r["analog"]["result"]["matches"] = [{"ts": o["ts"], "alike_on": ["vol_pctl_90d", "trend_sma_pct"], "differs_on": ["news_count_24h"]}
                                        for o in r["analog"]["matches_outcomes"]]
    shock = followup_zh.answer(r, "如果跌 10% 呢？")
    assert shock is not None and shock.kind == "shock" and "下跌 10%" in shock.text
    worst = followup_zh.answer(r, "会出什么问题？")
    assert worst is not None and worst.kind == "worst" and "开盘严重跳空" in worst.text
    similar = followup_zh.answer(r, "这些时刻为什么相似？")
    assert similar is not None and similar.kind == "moments" and "波动率分位" in similar.text


def test_a_chinese_leverage_what_if_names_the_change():
    from nightwatch.api import whatif

    assert whatif._describe_zh(whatif.Change(leverage=1.0)) == "不加杠杆"
    assert whatif._describe_zh(whatif.Change(leverage=5.0)) == "5 倍杠杆"


def test_the_thesis_question_says_which_way_history_leans(report):
    got = answer(report, "is my thesis supported?")
    assert got is not None and "history leans" in got.text and "does not claim to call direction" in got.text


def test_loose_matches_are_said_to_be_loose(report):
    r = copy.deepcopy(report)
    r["analog"]["result"]["matches"] = [{"ts": o["ts"], "similarity": 0.05, "alike_on": ["vol_pctl_90d", "trend_sma_pct"], "differs_on": []}
                                        for o in r["analog"]["matches_outcomes"]]
    got = answer(r, "why are these moments similar?")
    assert got is not None and "loose matches" in got.text


def test_chinese_similar_answer_has_no_leaked_feature_names(report):
    """basis_index_d6h_bps and basis_native_bps used to leak straight into the Chinese
    answer because FEATURE_ZH had no entry for them."""
    from nightwatch.api import followup_zh

    r = copy.deepcopy(report)
    r["analog"]["result"]["matches"] = [
        {"ts": o["ts"], "alike_on": ["basis_index_d6h_bps", "basis_native_bps"], "differs_on": ["basis_native_bps"]}
        for o in r["analog"]["matches_outcomes"]
    ]
    got = followup_zh.answer(r, "这些时刻为什么相似？")
    assert got is not None and got.kind == "moments"
    assert "偏离的变化速度" in got.text and "与上次收盘价的偏离" in got.text
    assert "basis_index_d6h_bps" not in got.text and "basis_native_bps" not in got.text


def test_chinese_similar_answer_skips_market_wide_features(report):
    """vix_pctl_1y, curve_pctl_1y, dollar_20d_chg_pct and ten_year_20d_chg_bps are identical
    across a token's recent hours, so naming one as why a moment is "alike" tells the trader
    nothing token-specific; only the token-specific feature should be named."""
    from nightwatch.api import followup_zh

    r = copy.deepcopy(report)
    r["analog"]["result"]["matches"] = [
        {"ts": o["ts"], "alike_on": ["vix_pctl_1y", "curve_pctl_1y", "dollar_20d_chg_pct", "ten_year_20d_chg_bps", "basis_index_d6h_bps"], "differs_on": []}
        for o in r["analog"]["matches_outcomes"]
    ]
    got = followup_zh.answer(r, "这些时刻为什么相似？")
    assert got is not None and got.kind == "moments" and "偏离的变化速度" in got.text
    for word in ("VIX", "收益率曲线", "美元", "十年期美债收益率"):
        assert word not in got.text

    # If every alike feature is market-wide, there is nothing token-specific left to say,
    # so the answer must fall through rather than print an empty "最接近的是：。".
    r2 = copy.deepcopy(report)
    r2["analog"]["result"]["matches"] = [
        {"ts": o["ts"], "alike_on": ["vix_pctl_1y", "curve_pctl_1y"], "differs_on": []}
        for o in r2["analog"]["matches_outcomes"]
    ]
    assert followup_zh._a_similar(r2, "这些时刻为什么相似？") is None


def test_the_questions_suggested_for_a_short_are_answered_as_losses(report):
    """A short is offered "gaps up 10%" and "如果涨 10% 呢" instead of the long's questions;
    both have to come back as a shock that loses money, not the menu."""
    from nightwatch.api import followup_zh

    r = copy.deepcopy(report)
    r["ticket"]["side"] = "short"
    up = answer(r, "what if it gaps up 10%?")
    assert up is not None and up.kind == "shock" and "loses about" in up.text
    up_zh = followup_zh.answer(r, "如果涨 10% 呢？")
    assert up_zh is not None and up_zh.kind == "shock"
