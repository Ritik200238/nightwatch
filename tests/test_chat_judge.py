"""Chat problems a second judge found on the live desk, each with the judge's own input."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nightwatch.api import intake, thesis_capture
from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

TICKERS = ["TSLA", "NVDA", "AAPL"]


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    monkeypatch.setenv("NIGHTWATCH_LLM_PROVIDER", "off")


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def say(client, *texts, ctx=None, equity=None):
    body = {"messages": [{"role": "user", "content": t} for t in texts]}
    if ctx:
        body["context_forecast_id"] = ctx
    if equity:
        body["account_equity_quote"] = equity
    r = client.post("/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# --- margin and leverage ----------------------------------------------------------------


def test_margin_times_leverage_is_the_position_and_never_the_account():
    p = intake.parse_message("yo thinking of aping into $TSLA long w 2k margin 5x, stop at 240", TICKERS)
    assert p.leverage == 5 and p.margin_quote == 2000 and p.notional_quote == 10000
    assert p.account_equity_quote is None


def test_a_size_that_disagrees_with_margin_and_leverage_is_flagged_not_dropped():
    p = intake.parse_message("buy 10k TSLA 3x with 2k margin", TICKERS)
    assert p.notional_quote == 6000 and p.leverage == 3
    assert any("6,000" in n for n in p.notes)


def test_a_size_and_a_margin_without_leverage_give_the_leverage():
    p = intake.parse_message("long 10k TSLA with 2k margin", TICKERS)
    assert p.notional_quote == 10000 and p.leverage == 5 and p.margin_quote == 2000


def test_chinese_margin_and_leverage():
    p = intake.parse_message("做多特斯拉 3倍杠杆 保证金2000", TICKERS)
    assert p.leverage == 3 and p.margin_quote == 2000 and p.notional_quote == 6000 and p.account_equity_quote is None


# --- "over earnings" ----------------------------------------------------------------------


@pytest.mark.parametrize("text", ["shrot Appl 5k ovr earnigns 🚀", "short AAPL 5k over earnings", "帮我 short 一下 AMD 5k, 过完 earnings 就走", "long TSLA 5k through the next report"])
def test_a_hold_through_earnings_is_read_even_typed_fast(text):
    assert intake.parse_message(text, TICKERS + ["AMD"]).through_earnings


def test_the_word_earnings_alone_is_not_a_hold_through_it():
    assert not intake.parse_message("long TSLA 5k, earnings are priced in", TICKERS).through_earnings


def test_a_followup_with_leverage_and_margin_sets_both_never_the_account(client):
    first = say(client, "long 10000 TSLA overnight, stop 300")
    got = say(client, "what about 3x with 2k margin", ctx=first["report"]["forecast_id"])
    t = got["ticket"]
    assert t["leverage"] == 3 and t["notional_quote"] == 6000
    assert t["account_equity_quote"] in (None, first["ticket"].get("account_equity_quote"))
    assert got["changed"].get("leverage") == 3


# --- a NO GO never sits beside "Size it at" ------------------------------------------------


def _fake(verdict, rec, req, rules=(), caps=()):
    return SimpleNamespace(
        ticket=SimpleNamespace(notional_quote=req),
        verdict=SimpleNamespace(verdict=SimpleNamespace(value=verdict), recommended_notional=rec, caps=[SimpleNamespace(name=n, notional=v, detail="") for n, v in caps]),
        gate=SimpleNamespace(rules=[SimpleNamespace(rule=r, decision=SimpleNamespace(value=d), reason=why) for r, d, why in rules]),
    )


def test_a_no_go_for_size_says_too_big_and_what_fits_without_a_contradiction():
    rep = _fake("NO_GO", 18913, 20000, [("risk_budget", "NO_GO", "risk 1.05% of equity (analog 5th-percentile loss) exceeds 1.0%")])
    en = intake._size_clause(rep, False)
    assert "Too big: 20,000 risks 1.05% of your account (limit 1%). 18,913 fits" in en and "Size it at" not in en
    zh = intake._size_clause(rep, True)
    assert "仓位过大" in zh and "1.05%" in zh and "18,913" in zh


def test_a_no_go_from_something_other_than_size_does_not_claim_a_smaller_size_fits():
    rep = _fake("NO_GO", 9000, 20000, [("market_posture", "NO_GO", "hostile")])
    got = intake._size_clause(rep, False)
    assert "Too big" not in got and "fits" not in got and "9,000" in got


@pytest.mark.parametrize(("rec", "req"), [(56, 10000), (0.4, 5000), (400, 10000)])
def test_a_sliver_of_a_size_is_not_offered(rec, req):
    rep = _fake("NO_GO", rec, req, [("risk_budget", "NO_GO", "risk 3.0% of equity (x) exceeds 1.0%")], caps=[("stress", rec)])
    en = intake._size_clause(rep, False)
    assert "No sensible size passes the limits right now" in en and "stress limit binds" in en and "Size it at" not in en and "fits" not in en
    assert "没有合适的仓位" in intake._size_clause(rep, True)


def test_a_reduce_still_says_size_it_at():
    assert "Size it at 9,000 instead" in intake._size_clause(_fake("REDUCE_TO", 9000, 20000), False)


def test_the_chat_reply_for_a_too_big_trade_reads_as_one_answer(client):
    r = say(client, "long 20000 TSLA overnight, account 50k")
    assert r["report"]["verdict"]["verdict"] == "NO_GO"
    head = r["reply"].split("\n")[0]
    assert "Too big: 20,000 is 40.0% of your account (limit 25%)" in head and "Size it at" not in r["reply"]


# --- the reason the desk asks for, typed back, clears the review ---------------------------

@pytest.mark.parametrize(("text", "thesis", "wrong"), [
    ("because AI demand is accelerating, wrong if it closes below 170", "AI demand is accelerating", "it closes below 170"),
    ("account 200k, because AI demand is accelerating, wrong if it closes below 170", "AI demand is accelerating", "it closes below 170"),
    ("because AI demand is strong, wrong if it closes below 170, account 200k", "AI demand is strong", "it closes below 170"),
    ("I'm wrong if the Fed hikes. because rates fall", "rates fall", "the Fed hikes"),
    ("我觉得会涨因为AI需求强，跌破170就算错", "AI需求强", "跌破170"),
    ("因为财报超预期，如果收盘跌破170就算错", "财报超预期", "收盘跌破170"),
])
def test_the_reason_and_the_wrong_if_line_are_cut_apart(text, thesis, wrong):
    got = thesis_capture.read(text)
    assert (got.thesis, got.invalidation) == (thesis, wrong)


@pytest.mark.parametrize("text", ["why?", "ovr earnigns 🚀", "halve it", "what if it gaps down 10%", "my account is 100k"])
def test_a_message_with_no_reason_reads_as_none(text):
    assert not thesis_capture.read(text)


def test_stray_words_are_not_a_reason():
    assert not thesis_capture.reads_as_reason("ovr earnigns rocket")
    assert not thesis_capture.reads_as_reason("🚀🚀")
    assert thesis_capture.reads_as_reason("AI demand is accelerating")
    assert thesis_capture.reads_as_reason("过完财报会涨")


def _blockers(report):
    return [(x["rule"], x["decision"]) for x in report["gate"]["rules"] if x["decision"] != "GO"]


def test_the_reply_the_desk_asks_for_clears_a_review_for_a_missing_plan(client):
    first = say(client, "long 5000 TSLA overnight, account 200k, stop 300")
    assert _blockers(first["report"]) == [("written_plan", "REVIEW_REQUIRED")] and first["report"]["verdict"]["verdict"] == "REVIEW"
    got = say(client, "because AI demand is accelerating, wrong if it closes below 280", ctx=first["report"]["forecast_id"])
    assert got["answer_kind"] == "thesis_saved"
    assert got["ticket"]["thesis"] == "AI demand is accelerating" and got["ticket"]["invalidation"] == "it closes below 280"
    assert _blockers(got["report"]) == [] and got["report"]["verdict"]["verdict"] == "GO"
    assert "moves from REVIEW" in got["reply"] and "to GO" in got["reply"]
    # the trade is the same one at the same moment: nothing the engine computes moved
    assert got["report"]["as_of"] == first["report"]["as_of"] and got["ticket"]["notional_quote"] == 5000
    assert got["report"]["forecast_id"] < 0  # a re-run, not a journalled forecast


def test_a_reason_and_an_account_size_in_one_message_both_land(client):
    first = say(client, "long 5000 TSLA overnight, stop 300")
    assert first["ticket"]["account_equity_quote"] is None
    got = say(client, "account 200k, because AI demand is accelerating, wrong if it closes below 280", ctx=first["report"]["forecast_id"])
    assert got["ticket"]["account_equity_quote"] == 200000 and got["ticket"]["thesis"] and got["ticket"]["invalidation"]
    assert _blockers(got["report"]) == []


def test_a_chinese_reason_clears_it_and_the_reply_is_chinese(client):
    first = say(client, "long 5000 TSLA overnight, account 200k, stop 300")
    got = say(client, "我觉得会涨因为AI需求强，跌破280就算错", ctx=first["report"]["forecast_id"])
    assert got["ticket"]["thesis"] == "AI需求强" and got["ticket"]["invalidation"] == "跌破280"
    assert _blockers(got["report"]) == [] and "已记在这笔交易上" in got["reply"]


def test_only_a_reason_says_what_is_still_missing(client):
    first = say(client, "long 5000 TSLA overnight, account 200k, stop 300")
    got = say(client, "because AI demand is accelerating", ctx=first["report"]["forecast_id"])
    assert got["report"]["verdict"]["verdict"] == "REVIEW" and "Still missing: what would prove you wrong" in got["reply"]


def test_is_my_reason_right_uses_the_reason_in_the_same_message(client):
    first = say(client, "long 5000 TSLA overnight, account 200k, stop 300")
    got = say(client, "is my reason right? because they beat earnings and raised guidance", ctx=first["report"]["forecast_id"])
    assert got["answer_kind"] == "thesis"
    assert got["ticket"]["thesis"] == "they beat earnings and raised guidance"
    assert "no written reason to check" not in got["reply"]


def test_a_question_is_not_taken_for_a_reason(client):
    first = say(client, "long 5000 TSLA overnight, account 200k, stop 300")
    got = say(client, "is it because of earnings?", ctx=first["report"]["forecast_id"])
    assert got.get("answer_kind") != "thesis_saved" and not (got.get("ticket") or {}).get("thesis")
