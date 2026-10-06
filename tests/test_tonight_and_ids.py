"""Tonight's book.

Found live: the same token listed twice came back as two identical rows, and a book whose
only token had no data was told "Nothing held".
"""

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from nightwatch.decision import tonight as tonight_mod
from tests.test_api import _frozen_clock  # noqa: F401 - autouse fixture
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False), raise_server_exceptions=False) as c:
        yield c


def test_the_same_position_listed_twice_is_one_row_of_the_summed_size(client):
    r = client.post("/tonight", json={"positions": [
        {"ticker": "TSLA", "side": "long", "notional_quote": 1000},
        {"ticker": "tsla", "side": "long", "notional_quote": 2000},
    ]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["ticker"] == "TSLA" and items[0]["notional_quote"] == 3000
    assert r.json()["gross_quote"] == 3000


def test_a_long_and_a_short_in_the_same_token_stay_separate(client):
    r = client.post("/tonight", json={"positions": [
        {"ticker": "TSLA", "side": "long", "notional_quote": 1000},
        {"ticker": "TSLA", "side": "short", "notional_quote": 1000},
    ]})
    assert r.status_code == 200, r.text
    assert sorted(i["side"] for i in r.json()["items"]) == ["long", "short"]


def test_a_book_of_unknown_tokens_is_not_told_it_is_empty(client):
    r = client.post("/tonight", json={"positions": [{"ticker": "ZZZZ", "side": "long", "notional_quote": 5000}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert "Nothing held" not in body["summary"]
    assert "could be judged" in body["summary"]
    assert "ZZZZ" in body["note"]


def test_an_empty_book_still_says_nothing_held(client):
    r = client.post("/tonight", json={"positions": []})
    assert r.status_code == 200
    assert r.json()["summary"].startswith("Nothing held")


@pytest.mark.parametrize("hours,word", [(1.3, "1 hour"), (1.0, "1 hour"), (2.4, "2 hours"), (11.6, "12 hours")])
def test_the_window_is_said_in_the_singular_when_it_is_one_hour(hours, word):
    from nightwatch.decision.tonight import Watch

    w = Watch(ticker="TSLA", side="long", notional_quote=1000, p5_pct=-1, p5_quote=-10, worst_preset=None, worst_preset_quote=None,
              exit_cost_bps=None, exit_fills=True, thin_share=None, regime_label=None)
    said = tonight_mod.summarise([w], hours, True)
    assert f"over the next {word}," in said or f"over the next {word}." in said
