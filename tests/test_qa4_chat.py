"""QA round 4, end to end through /chat with the audit's exact inputs."""

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture


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


def test_a_holdings_sentence_is_the_book_and_the_long_clause_is_the_trade(client):
    out = say(client, "I hold 30k AAPL and 10k NVDA. Long 20k TSLA overnight")
    assert (out["ticket"]["ticker"], out["ticket"]["side"], out["ticket"]["notional_quote"]) == ("TSLA", "long", 20_000.0)
    assert {t for t, _, _ in out["ticket"]["open_positions"]} == {"AAPL", "NVDA"}


def test_nonsense_after_a_trade_runs_nothing_and_never_flips_the_side(client):
    first = say(client, "short 10k NVDA overnight")
    assert first["ticket"]["side"] == "short"
    for ctx in (None, first["report"]["forecast_id"]):
        out = say(client, "short 10k NVDA overnight", "asdf qwerty lorem", ctx=ctx)
        assert out["report"] is None and out["ticket"] is None
        assert out["intent"]["kind"] == "clarify"
        assert "didn't catch a trade or a question about this one" in out["reply"]
        assert "earlier message" not in out["reply"]


def test_a_follow_up_that_changes_something_is_still_not_nonsense(client):
    out = say(client, "long 10k NVDA overnight", "make it 20k")
    assert out["ticket"]["notional_quote"] == 20_000.0 and out["ticket"]["side"] == "long"


def _tiers(monkeypatch, max_leverage):
    from nightwatch.execution.leverage import MarginTier
    from nightwatch.pipeline.analyze import AnalysisContext

    monkeypatch.setattr(AnalysisContext, "margin_tiers", lambda self, sym: [MarginTier(0.0, 1e9, max_leverage, 0.01)])

    monkeypatch.setattr(AnalysisContext, "spec", _with_perp(AnalysisContext.spec))


def _with_perp(real):
    from dataclasses import replace

    def spec(self, ticker):
        s = real(self, ticker)
        return s if getattr(s, "perp_symbol", None) else replace(s, perp_symbol=f"{ticker}USDT")
    return spec


@pytest.mark.parametrize("asked", [100, 500])
def test_leverage_above_the_bitget_cap_runs_at_the_cap_and_says_so(client, monkeypatch, asked):
    _tiers(monkeypatch, 20.0)
    out = say(client, f"{asked}x long NVDA 5k overnight account 50k")
    assert out["ticket"]["leverage"] == 20.0
    assert "Bitget allows at most 20x on a position this size" in out["reply"]
    assert "could not match" not in out["reply"]


def test_leverage_within_the_cap_is_left_alone(client, monkeypatch):
    _tiers(monkeypatch, 20.0)
    out = say(client, "5x long NVDA 5k overnight account 50k")
    assert out["ticket"]["leverage"] == 5.0 and "allows at most" not in out["reply"]


def test_a_what_if_for_an_impossible_leverage_is_capped_not_refused(client, monkeypatch):
    _tiers(monkeypatch, 20.0)
    first = say(client, "long 5k NVDA overnight account 50k")
    out = say(client, "what about 500x?", ctx=first["report"]["forecast_id"])
    assert "could not match" not in out["reply"]
    assert "Bitget allows at most 20x on a position this size" in out["reply"]
    assert out["ticket"]["leverage"] == 20.0


def test_a_size_the_desk_chose_is_not_labelled_as_carried_from_an_earlier_message(client):
    out = say(client, "long 20k NVDA overnight, because earnings", "5x long TSLA overnight, account 50k")
    assert out["ticket"]["ticker"] == "TSLA"
    assert "earlier message" not in out["reply"]


def test_the_search_size_and_the_full_run_do_not_both_claim_to_be_the_allowed_size(client, monkeypatch):
    """The reply said the desk allows 6,200 while the analyst said 3,100: the first was found by a
    search at a probe position, the second is the full run of that size. One number is stated."""
    monkeypatch.setattr("nightwatch.api.desk_help.largest_size", lambda state, intent, equity: (40_000.0, "largest_go"))
    out = say(client, "5x long TSLA overnight, account 50k")
    rec = out["report"]["verdict"]["recommended_notional"]
    assert out["ticket"]["notional_quote"] == 40_000.0
    assert rec is not None and rec < 39_999, rec
    assert f"allows at most {rec:,.0f} USDT" in out["reply"]
    assert "largest size the desk allows" not in out["reply"]
    assert out["size_assumed"]["note"] in out["reply"]
