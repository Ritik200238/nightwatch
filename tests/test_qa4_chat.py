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
