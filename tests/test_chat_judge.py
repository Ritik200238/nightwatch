"""Chat problems a second judge found on the live desk, each with the judge's own input."""

import pytest
from fastapi.testclient import TestClient

from nightwatch.api import intake
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
