"""Receipts: a past verdict cannot be changed or deleted without the chain saying so."""

from datetime import UTC, datetime

import pytest

from nightwatch.data.store import Store
from nightwatch.journal import receipts
from nightwatch.journal.journal import Journal
from tests.test_api import AS_OF, client  # noqa: F401 - fixture
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture client depends on


def _record(j: Journal, n: int) -> int:
    return j.record_forecast(
        kind="ticket", ticker="TSLA", side="long", notional=20_000.0 + n, as_of=datetime(2026, 9, 1, n, tzinfo=UTC),
        bar_ts=datetime(2026, 9, 1, n, tzinfo=UTC), horizon_h=12.0, entry_price=350.0, snapshot_hash=f"h{n}", analog_n=40,
        analog_scope="same_ticker", quantiles={"p5": -3.0, "p25": -1.0, "p50": 0.1, "p75": 1.0, "p95": 3.0},
        es5=-4.0, mc_p5=-3.2, mc_p95=3.1, verdict="GO", recommended_notional=20_000.0, payload={"n": n},
    )


@pytest.fixture
def journal(tmp_path):
    store = Store(tmp_path / "j.sqlite")
    yield Journal(store)
    store.close()


def test_every_forecast_gets_a_receipt_chained_to_the_one_before(journal):
    ids = [_record(journal, n) for n in range(5)]
    got = [receipts.receipt(journal._conn, i) for i in ids]
    assert all(g is not None for g in got)
    assert got[0]["prev"] == receipts.GENESIS and all(got[k]["prev"] == got[k - 1]["digest"] for k in range(1, 5))
    v = receipts.verify(journal._conn)
    assert v["ok"] and v["checked"] == 5 and v["head"] == got[-1]["digest"] and v["unchained"] == 0


def test_an_edited_verdict_breaks_the_chain_at_that_row(journal):
    ids = [_record(journal, n) for n in range(5)]
    with journal._conn:
        journal._conn.execute("UPDATE forecasts SET p5=-1.0 WHERE id=?", (ids[2],))
    v = receipts.verify(journal._conn)
    assert not v["ok"] and v["first_break"]["forecast_id"] == ids[2] and "no longer matches" in v["first_break"]["reason"]
    assert v["checked"] == 2


def test_a_deleted_verdict_breaks_the_chain(journal):
    import sqlite3

    ids = [_record(journal, n) for n in range(3)]
    # The database refuses outright while foreign keys are on...
    with pytest.raises(sqlite3.IntegrityError), journal._conn:
        journal._conn.execute("DELETE FROM forecasts WHERE id=?", (ids[1],))
    # ...and with them switched off, the chain still finds it.
    journal._conn.execute("PRAGMA foreign_keys=OFF")
    with journal._conn:
        journal._conn.execute("DELETE FROM forecasts WHERE id=?", (ids[1],))
    v = receipts.verify(journal._conn)
    assert not v["ok"] and v["first_break"]["forecast_id"] == ids[1] and "deleted" in v["first_break"]["reason"]


def test_marking_a_trade_taken_is_not_an_edit(journal):
    ids = [_record(journal, n) for n in range(3)]
    journal.mark_taken(ids[1])
    assert receipts.verify(journal._conn)["ok"]


def test_rows_without_a_receipt_are_chained_after_the_existing_ones(journal):
    ids = [_record(journal, n) for n in range(2)]
    with journal._conn:
        journal._conn.execute("DELETE FROM receipts WHERE forecast_id=?", (ids[1],))
    assert receipts.verify(journal._conn)["unchained"] == 1
    assert receipts.chain_pending(journal._conn) == 1
    assert receipts.verify(journal._conn)["ok"] and receipts.verify(journal._conn)["checked"] == 2


def test_the_api_verifies_the_chain_and_lists_misses(client):  # noqa: F811
    first = client.post("/analyze", json={"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000,
                                          "thesis": "t", "invalidation": "i", "as_of": AS_OF.isoformat()}).json()
    assert first["receipt"] and len(first["receipt"]) == 64
    v = client.get("/verify").json()
    assert v["ok"] and v["checked"] >= 1 and v["unchained"] == 0
    one = client.get(f"/verify/{first['forecast_id']}").json()
    assert one["digest"] == first["receipt"] and one["chain_ok_through_it"]
    m = client.get("/misses").json()
    assert set(m) >= {"totals", "misses", "target_rate"}



def test_the_ledger_lists_every_scored_forecast_with_the_same_totals_as_misses(client):  # noqa: F811
    client.post("/analyze", json={"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000,
                                  "thesis": "t", "invalidation": "i", "as_of": AS_OF.isoformat()})
    led = client.get("/ledger").json()
    assert set(led) >= {"rows", "scored", "target_rate"} and led["scored"] == len(led["rows"])
    totals = client.get("/misses").json()["totals"]
    for kind in ("replay", "ticket"):
        mine = [r for r in led["rows"] if r["kind"] == kind]
        assert len(mine) == totals.get(kind, {"scored": 0})["scored"]
        assert sum(r["missed"] for r in mine) == totals.get(kind, {"missed": 0})["missed"]
    assert all(set(r) >= {"id", "as_of", "ticker", "stated_p5_pct", "outcome_pct", "missed", "receipt"} for r in led["rows"])
