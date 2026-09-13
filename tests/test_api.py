
import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    app = create_app(settings, warm=False)
    with TestClient(app) as c:
        yield c


def test_health_and_universe(client):
    h = client.get("/health").json()
    assert h["ok"] and h["bars"] > 0 and h["tickers_with_data"] == 3
    u = client.get("/universe").json()
    assert {e["ticker"] for e in u} == {"TSLA", "NVDA", "AAPL"} and all(e["has_data"] for e in u)


def test_snapshot_endpoint(client):
    r = client.get("/snapshot/TSLA", params={"as_of": AS_OF.isoformat()})
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "TSLA" and "basis_index_bps" in body["features"]
    assert client.get("/snapshot/NOPE").status_code == 404


def test_analyze_endpoint_json_and_text_and_journal(client):
    payload = {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 300, "thesis": "t", "invalidation": "i", "as_of": AS_OF.isoformat()}
    r = client.post("/analyze", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"]["verdict"] in ("GO", "REDUCE_TO", "HEDGE", "NO_GO", "REVIEW")
    assert body["forecast_id"] is not None
    t = client.post("/analyze", params={"text": "true"}, json=payload).json()
    assert "VERDICT:" in t["text"]
    f = client.get("/forecasts", params={"ticker": "TSLA"}).json()
    assert len(f) >= 2 and f[-1]["kind"] == "ticket"
    assert client.post("/analyze", json={**payload, "notional_quote": -1}).status_code == 422
    assert client.post("/analyze", json={**payload, "ticker": "NOPE"}).status_code == 404


def test_a_quiet_token_is_analysed_with_a_warning_not_refused(client, seeded_store, monkeypatch):  # noqa: F811
    """A thin token can go hours without a trade. Refusing hides the most useful fact."""
    from datetime import timedelta

    late = AS_OF + timedelta(hours=20)
    payload = {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 300,
               "thesis": "t", "invalidation": "i", "as_of": late.isoformat(), "record": False}
    r = client.post("/analyze", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert any(f.startswith("spot_has_not_traded_for_") for f in body["snapshot"]["quality_flags"])
    assert body["gate"]["decision"] == "REVIEW_REQUIRED"
    assert body["verdict"]["verdict"] == "REVIEW"


def test_calibration_endpoint_shape(client):
    r = client.get("/calibration").json()
    assert "coverage" in r and "tail" in r and r["tail"]["band"] in ("green", "amber", "red", "insufficient")


def test_chat_without_credentials_explains_itself(client, monkeypatch):
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "long 20k TSLA"}]})
    assert r.status_code == 503 and "ticket form" in r.json()["detail"]
    assert client.get("/health").json()["chat_ready"] in (True, False)


def test_the_book_is_judged_alongside_the_trade(client):
    """Given what the trader already holds, the report says what the trade adds to it."""
    payload = {
        "ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000,
        "stop_price": 300, "thesis": "t", "invalidation": "i", "as_of": AS_OF.isoformat(), "record": False,
        "open_positions": [{"ticker": "NVDA", "side": "long", "notional_quote": 30000}],
    }
    body = client.post("/analyze", json=payload).json()
    p = body["portfolio"]
    assert p is not None
    assert p["before"]["gross_quote"] == 30000 and p["after"]["gross_quote"] == 50000
    assert p["after"]["largest_name"] == "NVDA"
    assert any(c["a"] in ("NVDA", "TSLA") and c["b"] in ("NVDA", "TSLA") for c in p["correlations"])
    # Without a book, there is nothing to say.
    alone = client.post("/analyze", json={**payload, "open_positions": []}).json()
    assert alone["portfolio"] is None
