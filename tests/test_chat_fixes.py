"""Chat problems a judge hit on the live desk, each with the audit's exact input."""

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)


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


def test_the_account_prompt_is_not_repeated_once_the_account_is_known(client):
    """After "account 50k" the reply still said "tell me your account size": the check
    matched the word "equity" in "position is 100% of equity" and took it for a missing one."""
    known = say(client, "long 40000 TSLA overnight, account 50k")
    assert known["ticket"]["account_equity_quote"] == 50000
    assert "account size" not in known["reply"] and "账户规模" not in known["reply"]
    unknown = say(client, "long 40000 TSLA overnight")
    assert "account size" in unknown["reply"]
