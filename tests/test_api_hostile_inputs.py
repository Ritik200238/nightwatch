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


@pytest.mark.parametrize("method,path,body", [
    ("get", "/reports/99999999999999999999", None),
    ("get", "/verify/99999999999999999999", None),
    ("get", "/thesis-check/99999999999999999999", None),
    ("get", "/plan/99999999999999999999", None),
    ("get", "/tripwire/suggest/99999999999999999999", None),
    ("post", "/forecasts/99999999999999999999/taken", {}),
    ("post", "/feedback", {"forecast_id": 99999999999999999999, "useful": True}),
    ("post", "/watch", {"forecast_id": 99999999999999999999}),
])
def test_an_id_too_big_for_the_database_is_a_404_not_a_500(client, method, path, body):
    r = client.get(path) if method == "get" else client.post(path, json=body)
    assert r.status_code == 404, (path, r.status_code, r.text)
    assert "Traceback" not in r.text and "SQLite" not in r.text



def test_holdings_that_could_not_be_measured_are_said_not_silently_dropped(client, monkeypatch):
    """If the book view fails, the gate used to claim 'the book's history is measured' for holdings
    nobody had measured, and the verdict quietly ignored them."""
    def boom(*a, **k):
        raise RuntimeError("portfolio exploded")

    monkeypatch.setattr("nightwatch.pipeline.analyze.evaluate_portfolio", boom)
    body = {**GOOD, "thesis": "t", "invalidation": "i", "open_positions": [{"ticker": "NVDA", "side": "long", "notional_quote": 30000}]}
    r = client.post("/analyze", json=body)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert any("holdings could not be measured" in w for w in rep["warnings"])
    book = next(x for x in rep["gate"]["rules"] if x["rule"] == "book_tail")
    assert "no stored history for NVDA" in book["reason"] and "is measured; its limit" not in book["reason"]
    assert rep["portfolio"] is None


@pytest.mark.parametrize("path", ["/forecasts?limit=-1", "/forecasts?limit=0", "/lessons?limit=-1", "/lessons?limit=0"])
def test_a_list_limit_below_one_is_refused_not_read_as_no_limit(client, path):
    """A negative limit used to mean 'everything': tail(-1) of the whole journal, or SQL LIMIT -1."""
    assert client.get(path).status_code == 422
    assert client.get(path.replace("-1", "1").replace("=0", "=1")).status_code == 200


# ---------------------------------------------------- no raw exception text reaches a visitor


def test_plain_message_passes_the_desks_own_sentences_and_hides_the_rest():
    from nightwatch.api.guard import GENERIC_PROBLEM, plain_message

    assert plain_message(ValueError("a hold can be at most 720 hours (30 days)")) == "a hold can be at most 720 hours (30 days)"
    assert plain_message(KeyError("FOO is not in the universe")) == "FOO is not in the universe"
    for raw in (KeyError("close"), RuntimeError("boom"), ValueError("invalid literal for int() with base 10: 'x'"),
                TypeError("'NoneType' object is not subscriptable"), RuntimeError('File "/app/nightwatch/x.py", line 3, in f'),
                RuntimeError("x " * 400)):
        assert plain_message(raw) == GENERIC_PROBLEM, raw
    assert plain_message(raw, "custom words") == "custom words"


def test_an_unknown_ticker_is_a_plain_404_on_the_ticker_routes(client):
    for path in ("/snapshot/ZZZZ", "/closed-hours/ZZZZ"):
        r = client.get(path)
        assert r.status_code == 404, path
        detail = r.json()["detail"]
        assert "ZZZZ" in detail and "Traceback" not in detail and "KeyError" not in detail


def test_an_internal_key_error_in_analyze_does_not_leak_its_key(client, monkeypatch):
    def boom(*a, **k):
        raise KeyError("spot_close")

    monkeypatch.setattr("nightwatch.api.app.analyze", boom)
    r = client.post("/analyze", json=GOOD)
    assert r.status_code == 404
    assert "spot_close" not in r.text and "missing data" in r.json()["detail"]


def test_missing_price_history_is_said_in_plain_words(client):
    """Before the data starts the real pipeline raises InsufficientData; it must read as a sentence."""
    r = client.post("/analyze", json={**GOOD, "as_of": "2020-01-01T00:00:00+00:00"})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "TSLA" in detail and "USDT" not in detail and "[" not in detail and "as_of" not in detail


def test_the_chat_stream_hides_an_unexpected_exception(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret trace at /srv/nightwatch/api/app.py line 99")

    monkeypatch.setattr("nightwatch.api.baserate.detect", boom)
    r = client.post("/chat/stream", json={"messages": [{"role": "user", "content": "long 10k TSLA overnight"}]})
    assert "secret" not in r.text and "app.py" not in r.text
    assert '"status": 500' in r.text and "Internal Server Error" in r.text


def test_the_plain_chat_hides_an_unexpected_exception_too(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret trace at /srv/nightwatch/api/app.py line 99")

    monkeypatch.setattr("nightwatch.api.baserate.detect", boom)
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "long 10k TSLA overnight"}]})
    assert r.status_code == 500 and "secret" not in r.text and "app.py" not in r.text
