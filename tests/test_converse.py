"""The turns a judge typed that used to dead-end: thanks, compare, flip, plain words."""

import pytest

from nightwatch.api import converse, followup, followup_zh
from tests.test_api import AS_OF, client  # noqa: F401 - the fixture is used by name
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture client depends on


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)


def _first(client):  # noqa: F811
    first = client.post("/chat", json={"messages": [{"role": "user", "content": "long 20000 TSLA overnight"}], "account_equity_quote": 200000}).json()
    return first, first["report"]["forecast_id"]


def _ask(client, fid, text):  # noqa: F811
    return client.post("/chat", json={"messages": [{"role": "user", "content": text}], "context_forecast_id": fid}).json()


@pytest.mark.parametrize("text", ["thanks", "thanks, that helps", "ok cool", "got it", "Thank you!", "谢谢", "好的", "明白了"])
def test_an_acknowledgement_is_read_as_one(text):
    assert converse.is_ack(text)


@pytest.mark.parametrize("text", ["ok halve it", "thanks, now long 20k NVDA", "cool, what if it gaps 10%", "好的，仓位减半"])
def test_an_acknowledgement_with_a_request_in_it_is_not(text):
    assert not converse.is_ack(text)


def test_thanks_does_not_restart_the_conversation(client):  # noqa: F811
    _, fid = _first(client)
    got = _ask(client, fid, "thanks, that helps")
    assert got["answer_kind"] == "ack" and got["report"] is None and "TSLA" in got["reply"]
    assert "which token" not in got["reply"].lower()
    assert "特斯拉" not in _ask(client, fid, "谢谢")["reply"] and "TSLA" in _ask(client, fid, "谢谢")["reply"]


@pytest.mark.parametrize("text", ["compare to just holding AAPL", "is this better than NVDA?", "what about AAPL instead", "NVDA?"])
def test_another_token_without_a_size_carries_the_trade(client, text):  # noqa: F811
    first, fid = _first(client)
    got = _ask(client, fid, text)
    assert got["mode"] == "what_if", got.get("reply")
    t = got["ticket"]
    assert t["ticker"] in ("AAPL", "NVDA") and t["notional_quote"] == 20000 and t["side"] == "long"
    assert got["report"]["as_of"] == first["report"]["as_of"]


def test_another_token_with_its_own_size_is_a_new_idea():
    ctx = {"ticket": {"ticker": "TSLA", "side": "long", "notional_quote": 20000}}
    assert not converse.carries_the_trade("long 5k NVDA overnight", ctx, ["TSLA", "NVDA"])


@pytest.mark.parametrize("text", ["short it instead", "flip it", "what if I short it", "反过来呢"])
def test_a_flip_reruns_the_same_trade_the_other_way(client, text):  # noqa: F811
    _, fid = _first(client)
    got = _ask(client, fid, text)
    assert got["mode"] == "what_if" and got["ticket"]["side"] == "short" and got["ticket"]["ticker"] == "TSLA", got.get("reply")


def test_plain_words_decide_data_and_options_are_answered_from_the_report(client):  # noqa: F811
    first, _ = _first(client)
    r = first["report"]
    plain = followup.answer(r, "explain like I'm new")
    assert plain.kind == "plain" and "In plain words" in plain.text and "you decide" in plain.text
    decide = followup.answer(r, "should I buy?")
    assert decide.kind == "decide" and "no edge on direction" in decide.text
    assert followup.answer(r, "what data do you use").kind == "data"
    opts = followup.answer(r, "what about using options instead")
    assert opts.kind == "hedge" and "no options data" in opts.text
    assert followup.answer(r, "what are my options?") is None or followup.answer(r, "what are my options?").kind != "hedge"


def test_the_same_answers_in_chinese(client):  # noqa: F811
    first, _ = _first(client)
    r = first["report"]
    assert followup_zh.answer(r, "简单解释一下").kind == "plain"
    assert followup_zh.answer(r, "要不要买？").kind == "decide"
    assert followup_zh.answer(r, "数据从哪来？").kind == "data"
    assert followup_zh.answer(r, "用期权呢").kind == "hedge"


def test_a_reduce_verdict_is_named_in_chinese_not_as_a_code():
    assert followup_zh.VERDICT_ZH["REDUCE_TO"] == "建议减仓"
