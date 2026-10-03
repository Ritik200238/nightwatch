"""Price tripwires: which side fires, firing once, what is recorded, and the API."""

from datetime import timedelta

import pytest

from nightwatch.journal import tripwires, watches
from nightwatch.time_utils import to_epoch_ms, utc_now
from tests import test_api
from tests.test_api import AS_OF
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture the client fixture depends on

client = test_api.client

PAYLOAD = {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 300,
           "thesis": "t", "invalidation": "wrong if it closes below 290", "as_of": AS_OF.isoformat()}
ME = {"x-nw-client": "abcdefgh12345678"}


@pytest.fixture(autouse=True)
def _clean(client):
    conn = client.app.state.nw.store._conn
    with conn:
        conn.execute("DELETE FROM tripwires")
    yield


def _fid(client, **over) -> int:
    r = client.post("/analyze", json={**PAYLOAD, **over}, headers=ME)
    assert r.status_code == 200
    return r.json()["forecast_id"]


def _bar(minutes_from_now: float, low: float, high: float):
    return (to_epoch_ms(utc_now() + timedelta(minutes=minutes_from_now)), low, high)


def test_crossed_both_sides():
    assert tripwires.crossed("below", 300, 299.9, 310) and not tripwires.crossed("below", 300, 300.1, 400)
    assert tripwires.crossed("above", 300, 200, 300.0) and not tripwires.crossed("above", 300, 100, 299.9)


def test_direction_comes_from_the_line_against_the_price_then_the_side():
    assert tripwires.direction_for(300, 350, "long") == "below"
    assert tripwires.direction_for(400, 350, "short") == "above"
    assert tripwires.direction_for(400, 350, "long") == "above"  # an upside line on a long is honoured
    assert tripwires.direction_for(300, None, "long") == "below" and tripwires.direction_for(300, None, "short") == "above"


def test_suggestions_hold_the_stop_and_the_written_level_and_the_tail(client):
    fid = _fid(client)
    got = client.get(f"/tripwire/suggest/{fid}").json()["suggestions"]
    by = {s["label"]: s for s in got}
    assert by["stop"]["level"] == 300 and by["stop"]["direction"] == "below"
    assert "p5" in by and by["p5"]["direction"] == "below"
    assert client.get("/tripwire/suggest/424242").status_code == 404


def test_short_p5_is_above_the_entry(client):
    fid = _fid(client, side="short", stop_price=400)
    by = {s["label"]: s for s in client.get(f"/tripwire/suggest/{fid}").json()["suggestions"]}
    assert by["stop"]["direction"] == "above" and by["p5"]["direction"] == "above"


def _arm(client, fid, level, **kw):
    r = client.post("/tripwire", json={"forecast_id": fid, "level": level, **kw}, headers=ME)
    assert r.status_code == 200, r.text
    return r.json()


def _run(client, bars, rerun=None):
    s = client.app.state.nw
    return tripwires.run_armed(s.store._conn, lambda t, since: bars, rerun or (lambda rep: rep), s.reports.get)


def test_long_stop_fires_below_once_and_records_when_and_where(client):
    fid = _fid(client)
    w = _arm(client, fid, 300, label="stop")
    assert w["direction"] == "below" and w["status"] == "armed" and w["fired_at"] is None
    assert _run(client, [_bar(1, 301, 320)]) == 0  # above the line: nothing
    assert client.get(f"/tripwire/{w['id']}").json()["status"] == "armed"
    bar = _bar(2, 298.5, 305)
    assert _run(client, [bar]) == 1
    got = client.get(f"/tripwire/{w['id']}").json()
    assert got["status"] == "fired" and got["fired_price"] == 298.5 and got["after"]["verdict"] and got["fired_at"]
    assert _run(client, [_bar(3, 100, 110)]) == 0  # fired once, never again
    assert client.get(f"/tripwire/{w['id']}").json()["fired_price"] == 298.5


def test_short_stop_fires_above_not_below(client):
    fid = _fid(client, side="short", stop_price=400)
    w = _arm(client, fid, 400, label="stop")
    assert w["direction"] == "above"
    assert _run(client, [_bar(1, 100, 399)]) == 0  # a crash is the short's gain, not its stop
    assert _run(client, [_bar(2, 390, 402.5)]) == 1
    got = client.get(f"/tripwire/{w['id']}").json()
    assert got["status"] == "fired" and got["fired_price"] == 402.5


def test_a_failed_rerun_still_records_the_alert(client):
    fid = _fid(client)
    w = _arm(client, fid, 300)

    def boom(_):
        raise RuntimeError("desk down")

    assert _run(client, [_bar(1, 290, 305)], rerun=boom) == 1
    got = client.get(f"/tripwire/{w['id']}").json()
    assert got["status"] == "fired" and got["after"] is None and "desk down" in got["error"]


def test_webhook_gets_the_alert_with_price_and_verdict(client, monkeypatch):
    fid = _fid(client)
    monkeypatch.setattr(tripwires, "check_webhook", lambda u: u)
    monkeypatch.setattr(watches, "check_webhook", lambda u: u)
    w = _arm(client, fid, 300, webhook="https://hooks.example.com/secret")
    assert w["webhook_host"] == "hooks.example.com" and "secret" not in str(w)
    sent = {}

    class R:
        status_code = 200

    monkeypatch.setattr("httpx.post", lambda url, json, **kw: sent.update(url=url, body=json) or R())
    _run(client, [_bar(1, 295, 305)])
    assert sent["url"].endswith("/secret") and sent["body"]["fired_price"] == 295 and sent["body"]["after"]["verdict"]
    assert client.get(f"/tripwire/{w['id']}").json()["webhook_status"] == "http 200"


def test_api_validation_dedupe_and_caps(client):
    fid = _fid(client)
    assert client.post("/tripwire", json={"forecast_id": 424242, "level": 300}, headers=ME).status_code == 404
    assert client.post("/tripwire", json={"forecast_id": fid, "level": -5}, headers=ME).status_code == 422
    assert client.post("/tripwire", json={"forecast_id": fid, "level": 300, "webhook": "http://x.io/h"}, headers=ME).status_code == 422
    assert client.get("/tripwire/nope").status_code == 404
    a = _arm(client, fid, 300)
    assert _arm(client, fid, 300)["id"] == a["id"]  # asked twice, one tripwire
    mine = client.get(f"/tripwire/report/{fid}", headers=ME).json()["tripwires"]
    assert [t["id"] for t in mine] == [a["id"]]
    assert client.get(f"/tripwire/report/{fid}", headers={"x-nw-client": "someoneelse123456"}).json()["tripwires"] == []
    # Straight at the module: the HTTP burst limit would trip first and hide the per-hour cap.
    s = client.app.state.nw
    rep = s.reports.get(fid)
    from nightwatch.journal import engagement

    me = engagement.hash_client(ME["x-nw-client"], None)
    for i in range(tripwires.PER_HOUR - 1):
        tripwires.create(s.store._conn, forecast_id=fid, report=rep, level=200 + i, label="custom", webhook=None, lang="en", client=me)
    with pytest.raises(tripwires.TooMany):
        tripwires.create(s.store._conn, forecast_id=fid, report=rep, level=150, label="custom", webhook=None, lang="en", client=me)


def test_old_tripwires_expire(client):
    fid = _fid(client)
    w = _arm(client, fid, 300)
    s = client.app.state.nw
    n = tripwires.run_armed(s.store._conn, lambda t, since: [_bar(1, 1, 2)], lambda r: r, s.reports.get, now=utc_now() + timedelta(days=31))
    assert n == 0 and client.get(f"/tripwire/{w['id']}").json()["status"] == "expired"
