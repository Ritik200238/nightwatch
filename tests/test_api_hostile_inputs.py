"""Hostile and extreme request bodies must answer a clean 4xx, never a 500.

A 500 is worse than it looks on this deployment: the web proxy answers a backend 5xx with
a saved example report, so a bad request would be shown to the visitor as if it were
the answer to their trade.
"""

import json

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_api import _frozen_clock  # noqa: F401 - autouse fixture
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

GOOD = {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "as_of": AS_OF.isoformat(), "record": False}


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False), raise_server_exceptions=False) as c:
        yield c


def _post(client, body: bytes):
    return client.post("/analyze", content=body, headers={"content-type": "application/json"})


def test_a_nan_in_the_body_is_a_422_not_a_server_error(client):
    """Python's JSON parser accepts the bare token NaN; echoing it back in the error body
    used to fail the response encoder and answer 500."""
    r = _post(client, b'{"ticker":"TSLA","notional_quote":NaN}')
    assert r.status_code == 422, r.text
    r = _post(client, b'{"ticker":"TSLA","notional_quote":20000,"account_equity_quote":Infinity}')
    assert r.status_code == 422, r.text


def test_validation_errors_do_not_echo_the_input_back(client):
    r = client.post("/analyze", json={**GOOD, "notional_quote": -5, "thesis": "x"})
    assert r.status_code == 422
    items = r.json()["detail"]
    assert items and all("input" not in it for it in items)
    assert items[0]["loc"][-1] == "notional_quote" and items[0]["type"] == "greater_than"


@pytest.mark.parametrize("hours", [1e9, 1e300, 8761, -3, 0])
def test_an_absurd_hold_is_refused_cleanly(client, hours):
    r = client.post("/analyze", json={**GOOD, "horizon_kind": "hours", "horizon_hours": hours})
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("field", ["entry_price", "stop_price", "target_price"])
@pytest.mark.parametrize("value", [-5, 0, 1e300])
def test_a_price_must_be_a_positive_price(client, field, value):
    r = client.post("/analyze", json={**GOOD, field: value})
    assert r.status_code == 422, (field, value, r.text)


def test_a_normal_request_still_works(client):
    r = client.post("/analyze", json={**GOOD, "horizon_kind": "hours", "horizon_hours": 72})
    assert r.status_code == 200, r.text
    assert json.loads(r.text)["horizon_h"] == 72
