"""Regressions from the live user test of 2026-10-05, one section per finding."""

import pytest

from nightwatch.api import desk_help
from tests.test_api import AS_OF, client  # noqa: F401 - the fixture is used by name
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture client depends on

KNOWN = ["TSLA", "NVDA", "AAPL"]


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)


def _chat(client, messages, fid=None, account=None):  # noqa: F811
    return client.post("/chat", json={"messages": messages, "context_forecast_id": fid, "account_equity_quote": account}).json()


def _u(text):
    return {"role": "user", "content": text}


# 1. An unknown ticker is never swapped for the ticker on screen


@pytest.mark.parametrize("text", ["long 10k ZZZZ", "buy $ZZZZ 5k", "ZZZZ short 5k", "做多 ZZZZ 2万U", "short 10k of ZZZZ over the weekend"])
def test_an_unknown_named_token_is_found(text):
    assert desk_help.named_unknown_ticker(text, KNOWN) == "ZZZZ"


@pytest.mark.parametrize("text", ["long 10k TSLA", "long 10k over the weekend", "compare to just holding SPY", "buy USDT", "long 20k NVDA because AI demand", "周末做多特斯拉 2万U"])
def test_a_covered_or_tokenless_message_names_no_unknown_token(text):
    assert desk_help.named_unknown_ticker(text, KNOWN) is None


def test_an_unknown_ticker_with_a_report_on_screen_is_not_a_tsla_trade(client):  # noqa: F811
    first = _chat(client, [_u("long 20000 TSLA overnight")], account=200000)
    fid = first["report"]["forecast_id"]
    got = _chat(client, [_u("long 20000 TSLA overnight"), {"role": "assistant", "content": first["reply"]}, _u("long 10k ZZZZ")], fid=fid)
    assert got["report"] is None and got["ticket"] is None
    assert got["reply"].startswith("ZZZZ isn't one of the 3 tokenized stocks we cover: AAPL, NVDA, TSLA")
    assert got["intent"]["kind"] == "clarify"


def test_an_unknown_ticker_is_refused_in_chinese_too(client):  # noqa: F811
    first = _chat(client, [_u("long 20000 TSLA overnight")], account=200000)
    got = _chat(client, [_u("long 20000 TSLA overnight"), _u("做多 ZZZZ 1万U")], fid=first["report"]["forecast_id"])
    assert got["report"] is None and "ZZZZ 不在我们覆盖的 3 只" in got["reply"]
