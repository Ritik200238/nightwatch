""""I took this trade" is one visitor's own record, not the whole desk's.

The circuit breaker reads the trades marked taken. On a desk everyone shares, a breaker fed by
anyone's click lets one visitor (or a script walking the forecast ids) put every other visitor
into COOLDOWN or HALTED. These tests pin both halves: only the visitor who ran an analysis can
mark it, and the breaker a visitor sees counts only what that visitor marked.
"""

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_api import _frozen_clock  # noqa: F401 - autouse fixture
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

ALICE = {"x-nw-client": "alice-browser-0001"}
BOB = {"x-nw-client": "bob-browser-00002"}
BODY = {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "as_of": AS_OF.isoformat()}


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def test_only_the_visitor_who_ran_an_analysis_can_mark_it_taken(client):
    fid = client.post("/analyze", json=BODY, headers=ALICE).json()["forecast_id"]
    assert client.post(f"/forecasts/{fid}/taken", headers=BOB).status_code == 403
    assert client.post(f"/forecasts/{fid}/taken", headers=ALICE).json() == {"forecast_id": fid, "taken": True}
    # Bob's refused attempt changed nothing: Alice can still take it back.
    assert client.post(f"/forecasts/{fid}/taken", params={"taken": "false"}, headers=ALICE).json()["taken"] is False


def test_a_forecast_nobody_ran_cannot_be_marked(client):
    assert client.post("/forecasts/987654/taken", headers=ALICE).status_code == 404


def test_the_breaker_counts_only_the_visitors_own_taken_trades(client):
    fid = client.post("/analyze", json=BODY, headers=ALICE).json()["forecast_id"]
    client.post(f"/forecasts/{fid}/taken", headers=ALICE)
    mine = client.post("/analyze", json=BODY, headers=ALICE).json()["breaker"]
    theirs = client.post("/analyze", json=BODY, headers=BOB).json()["breaker"]
    assert mine["n_taken"] == 1 and theirs["n_taken"] == 0
    assert client.get("/breaker", headers=ALICE).json()["n_taken"] == 1
    assert client.get("/breaker", headers=BOB).json()["n_taken"] == 0


def test_a_taken_trade_nobody_owns_does_not_reach_a_visitor(tmp_path):
    """Rows from before visitors were tracked, or the operator's own, stay out of every visitor's breaker."""
    from datetime import UTC, datetime

    from nightwatch.data.store import Store
    from nightwatch.journal import engagement
    from nightwatch.journal.journal import Journal

    now = datetime(2026, 10, 1, tzinfo=UTC)
    with Store(tmp_path / "j.sqlite") as store:
        store._conn.executescript(engagement.SCHEMA)
        j = Journal(store)
        ids = [
            j.record_forecast(
                kind="ticket", ticker="TSLA", side="long", notional=1000.0, as_of=now, bar_ts=now, horizon_h=24.0, entry_price=100.0,
                snapshot_hash=f"h{i}", analog_n=10, analog_scope="same_ticker", quantiles={"p5": -3.0, "p25": -1.0, "p50": 0.0, "p75": 1.0, "p95": 3.0},
                es5=-4.0, mc_p5=-3.0, mc_p95=3.0, verdict="GO", recommended_notional=1000.0, payload={},
            )
            for i in range(3)
        ]
        mine, theirs, nobodys = ids
        engagement.mark_verdict(store._conn, mine, lang="en", client="me", internal=False)
        engagement.mark_verdict(store._conn, theirs, lang="en", client="them", internal=False)
        for fid in ids:
            assert j.mark_taken(fid)
        assert set(j.taken_trades(matured_only=False, client="me")["id"]) == {mine}
        assert set(j.taken_trades(matured_only=False, client="them")["id"]) == {theirs}
        assert set(j.taken_trades(matured_only=False)["id"]) == {nobodys}  # no client: only the unowned one
        assert j.taken_trades(matured_only=False, client="stranger").empty
        assert j.owner_of(mine) == "me" and j.owner_of(nobodys) is None
