"""'Same trade, different book': the page runs one ticket twice through /analyze, alone and
on an example book, and explains the size from these fields. They must exist and the
book must reach the answer, or the contrast would show two identical cards."""

from tests import test_api
from tests.test_api import AS_OF
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture the client fixture depends on

client = test_api.client

BASE = {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000,
        "thesis": "t", "invalidation": "wrong if it opens below 340", "as_of": AS_OF.isoformat(), "record": False}
BOOK = [{"ticker": "TSLA", "side": "long", "notional_quote": 60000}, {"ticker": "NVDA", "side": "long", "notional_quote": 40000}]


def test_same_ticket_alone_and_on_a_book(client):
    alone = client.post("/analyze", json={**BASE, "open_positions": []}).json()
    held = client.post("/analyze", json={**BASE, "open_positions": BOOK, "as_of": alone["as_of"]}).json()
    assert alone["forecast_id"] is None and held["forecast_id"] is None  # neither is journaled
    assert alone["portfolio"] is None and held["portfolio"] is not None
    for r in (alone, held):
        assert r["verdict"]["verdict"] and "reasons" in r["verdict"] and "binding_cap" in r["sizing"]
    p = held["portfolio"]
    assert "book_cap_binds" in p and "book_cap_quote" in p and p["after"]["tail_loss_quote"] is not None
    # the book adds a cap that the lone trade does not have
    assert any(c["name"] == "book_tail" for c in held["sizing"]["caps"])
    assert alone["as_of"] == held["as_of"]
