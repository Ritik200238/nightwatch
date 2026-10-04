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
    monkeypatch.setenv("NIGHTWATCH_LLM_PROVIDER", "off")  # the analyst's background take must not reach a real model


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


# --- 1. amounts written the Chinese way -------------------------------------------------

AMOUNTS = [
    ("周末做多特斯拉 2万U", 20000), ("周末做多特斯拉 2万", 20000), ("周末做多特斯拉 2w", 20000), ("做多特斯拉 2W", 20000),
    ("周末做多特斯拉 两万", 20000), ("周末做多特斯拉 1.5万U", 15000), ("周末做多特斯拉 3千U", 3000),
    ("做多特斯拉 2万美金", 20000), ("周末做多特斯拉 ２万Ｕ", 20000), ("long tsla 2w overnight", 20000),
    ("long tsla 10k", 10000), ("long tsla 20K", 20000),
]


@pytest.mark.parametrize(("text", "size"), AMOUNTS)
def test_amounts_and_names_are_read_exactly(client, text, size):
    r = say(client, text)
    assert r["ticket"]["ticker"] == "TSLA" and r["ticket"]["notional_quote"] == size, r["reply"]
    assert r["ticket"]["side"] == "long"


def test_a_duration_in_weeks_is_not_a_size():
    from nightwatch.api import intake

    assert intake.parse_message("long tsla for 2w", ["TSLA"]).notional_quote is None


class _Fake:
    name, model, narrates = "fake", "fake", False

    def __init__(self, parsed=None):
        self.parsed, self.calls = parsed, 0

    def parse(self, messages, *, system, schema, max_tokens=2000):
        self.calls += 1
        return self.parsed

    def write(self, **kw):
        return None


def test_the_standard_chinese_prompt_never_waits_for_the_model(client, monkeypatch):
    fake = _Fake()
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: True)
    monkeypatch.setattr("nightwatch.api.llm.select", lambda *a, **k: fake)
    r = say(client, "周末做多特斯拉 2万U")
    assert fake.calls == 0 and r["ticket"]["notional_quote"] == 20000 and r["ticket"]["ticker"] == "TSLA"


def test_when_the_model_misreads_the_amount_the_rules_reading_stands(client, monkeypatch):
    """The audit saw Qwen answer "Which ticker and side?" to this text."""
    from nightwatch.api.llm import ParsedIntent

    wrong = ParsedIntent(kind="clarify", notional_quote=2.0, missing_fields=["ticker", "side"], reply="Which ticker and side?")
    fake = _Fake(wrong)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: True)
    monkeypatch.setattr("nightwatch.api.llm.select", lambda *a, **k: fake)
    r = say(client, "周末做多特斯拉 2万U，只对比周末")  # "只" asks to narrow, so the model is consulted
    assert fake.calls == 1
    assert r["ticket"]["notional_quote"] == 20000 and r["ticket"]["ticker"] == "TSLA"
