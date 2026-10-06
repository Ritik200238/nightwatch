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


# --- a request that carries the account is honoured by follow-ups ---------------------------


def test_a_followup_uses_the_account_the_request_carries(client):
    first = say(client, "long 5000 TSLA overnight, stop 300")
    assert first["ticket"]["account_equity_quote"] is None
    got = say(client, "why?", ctx=first["report"]["forecast_id"], equity=100000)
    assert "account equity not provided" not in got["reply"] and "Judged against your account of 100,000 USDT" in got["reply"]
    assert got["report"]["ticket"]["account_equity_quote"] == 100000
    # the same question again does not pay for a second analysis
    again = say(client, "why?", ctx=first["report"]["forecast_id"], equity=100000)
    assert again["report"]["forecast_id"] == got["report"]["forecast_id"]


def test_a_followup_without_an_account_in_the_request_is_unchanged(client):
    first = say(client, "long 5000 TSLA overnight, stop 300")
    got = say(client, "why?", ctx=first["report"]["forecast_id"])
    assert "Judged against your account" not in got["reply"] and got["report"] is None


def test_a_report_that_already_has_an_account_is_not_rerun(client):
    first = say(client, "long 5000 TSLA overnight, account 200k, stop 300")
    got = say(client, "why?", ctx=first["report"]["forecast_id"], equity=100000)
    assert got["report"] is None


# --- "I read this as" -----------------------------------------------------------------------


def test_the_first_reply_says_how_the_message_was_read(client):
    r = say(client, "long 20000 TSLA overnight, stop 300, because momentum, wrong if it closes below 290")
    echo = next(p for p in r["reply"].split("\n\n") if p.startswith("I read this as:"))
    assert "long 20,000 USDT of TSLA" in echo and "until the next US open" in echo and "account: not given" in echo
    assert "stop 300.00" in echo and 'reason "momentum"' in echo and 'wrong if "it closes below 290"' in echo


def test_the_echo_names_leverage_and_margin(client):
    r = say(client, "long TSLA 3x with 2k margin")
    assert "6,000 USDT of TSLA, 3x leverage (margin 2,000)" in r["reply"]
    assert r["ticket"]["leverage"] == 3 and r["ticket"]["notional_quote"] == 6000 and r["ticket"]["account_equity_quote"] is None


def test_the_echo_lists_what_it_could_not_use(client):
    r = say(client, "short AAPL 5k ovr earnigns 🚀")
    echo = next(p for p in r["reply"].split("\n\n") if p.startswith("I read this as:"))
    assert "Not used:" in echo and "holding over earnings" in echo and '"🚀" (reads bullish, but you said short' in echo
    assert not r["ticket"]["thesis"]  # the typed fragments were never a reason


def test_a_hold_carried_over_from_an_earlier_ticker_is_said_out_loud(client):
    r = say(client, "long 5000 NVDA for 40 hours, account 100k", "short 5k TSLA")
    echo = next(p for p in r["reply"].split("\n\n") if p.startswith("I read this as:"))
    assert "short 5,000 USDT of TSLA" in echo and 'for 40h - typed earlier, in "long 5000 NVDA for 40 hours, account 100k"' in echo


def test_the_echo_is_in_chinese_for_a_chinese_message(client):
    r = say(client, "周末做多特斯拉 2万U")
    assert any(p.startswith("我的理解：做多 TSLA 20,000 USDT") for p in r["reply"].split("\n\n"))


# --- the headline --------------------------------------------------------------------------


def test_the_reply_opens_with_a_two_line_headline_then_the_rest_after_a_blank_line(client):
    r = say(client, "long 5000 TSLA overnight, account 200k, stop 300")
    headline, *rest = r["reply"].split("\n\n")
    lines = headline.split("\n")
    assert len(lines) == 2 and lines[0].startswith("REVIEW on long 5,000 USDT of TSLA") and lines[1].startswith("Next: tell me why you want it")
    assert rest[0].startswith("I read this as:")
    # the sentence the headline says is not repeated below it, and nothing else was dropped
    assert not any(p.startswith("To clear the review") for p in rest)
    assert any(p.startswith("History:") for p in rest) and rest[-1].startswith("Ask me:")


def test_a_review_waiting_on_the_account_keeps_its_two_line_opening(client):
    r = say(client, "long 20000 TSLA overnight")
    headline = r["reply"].split("\n\n")[0]
    assert headline.startswith("REVIEW: tell the desk your account size") and "\n" in headline


def test_a_go_says_what_to_do_next(client):
    r = say(client, "long 5000 TSLA overnight, account 200k, stop 300, because AI demand, wrong if it closes below 290")
    assert r["report"]["verdict"]["verdict"] == "GO"
    assert r["reply"].split("\n")[1].startswith("Next: before you place it")


# --- over earnings, dated from the calendar ---------------------------------------------------


def test_a_hold_over_earnings_is_stretched_to_the_report_when_it_can_be_dated():
    from nightwatch.api import reading
    from nightwatch.api.whatif import AFTER_REPORT_OPEN_H

    state = SimpleNamespace(ctx=SimpleNamespace(
        spec=lambda t: t, snapshot_at=lambda spec, at: SimpleNamespace(features={"hours_to_earnings": 20.0}),
    ))
    intent = intake.parse_message("short AAPL 5k ovr earnigns", TICKERS)
    applied, note = reading.apply_earnings_hold(state, intent)
    assert applied and note is None and intent.horizon_kind == "hours" and intent.horizon_hours == 20.0 + AFTER_REPORT_OPEN_H


def test_a_hold_length_in_the_message_wins_over_earnings():
    from nightwatch.api import reading

    state = SimpleNamespace(ctx=SimpleNamespace(spec=lambda t: t, snapshot_at=lambda spec, at: SimpleNamespace(features={"hours_to_earnings": 20.0})))
    intent = intake.parse_message("short AAPL 5k for 6 hours over earnings", TICKERS)
    assert reading.apply_earnings_hold(state, intent) == (False, None) and intent.horizon_hours == 6.0


def test_an_undatable_report_is_not_guessed_at_and_is_said():
    from nightwatch.api import reading

    state = SimpleNamespace(ctx=SimpleNamespace(spec=lambda t: t, snapshot_at=lambda spec, at: SimpleNamespace(features={"hours_to_earnings": 720.0})))
    intent = intake.parse_message("long TSLA 5k, 过完 earnings 就走", TICKERS)
    applied, note = reading.apply_earnings_hold(state, intent, "zh")
    assert not applied and "没有拉长持有期" in note and intent.horizon_kind is None


# --- the model's reading is checked against the rules' --------------------------------------


def test_a_model_reading_cannot_turn_margin_into_an_account_or_typed_words_into_a_reason():
    from nightwatch.api.llm import ParsedIntent, _guard_model_reading

    rules = intake.parse_message("yo thinking of aping into $TSLA long w 2k margin 5x, stop at 240", TICKERS)
    model = ParsedIntent(kind="analyze", ticker="TSLA", side="long", notional_quote=2000, account_equity_quote=2000, thesis="ovr earnigns rocket", missing_fields=[], reply="")
    got, dropped = _guard_model_reading(model, rules, None)
    assert got.account_equity_quote is None and got.notional_quote == 10000
    assert got.thesis is None and dropped == "ovr earnigns rocket"
    # an account the request carries is still used
    assert _guard_model_reading(model, rules, 100000)[0].account_equity_quote == 100000
    # a reason the trader marked with "because" stands
    because = intake.parse_message("long TSLA 5k because momentum", TICKERS)
    kept, none = _guard_model_reading(model.model_copy(update={"thesis": "momentum"}), because, None)
    assert kept.thesis == "momentum" and none is None
