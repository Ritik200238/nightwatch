"""Feedback, usage counts and watches: what is kept, what is not, and who is excluded."""

from datetime import UTC, datetime, timedelta

import pytest

from nightwatch.journal import engagement, watches
from tests import test_api
from tests.test_api import AS_OF
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture the client fixture depends on

client = test_api.client  # the same app fixture, without redefining the name in every test

@pytest.fixture(autouse=True)
def _clean_tables(client):
    """The seeded database outlives a test; these counts must start from nothing."""
    conn = client.app.state.nw.store._conn
    with conn:
        for t in ("feedback", "verdict_marks", "chat_counts", "watches"):
            conn.execute(f"DELETE FROM {t}")
    yield


PAYLOAD = {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 300,
           "thesis": "t", "invalidation": "i", "as_of": AS_OF.isoformat()}
ME = {"x-nw-client": "abcdefgh12345678"}


def _verdict(client, headers=None) -> int:
    r = client.post("/analyze", json=PAYLOAD, headers=headers or ME)
    assert r.status_code == 200
    return r.json()["forecast_id"]


def _all_text(client) -> str:
    conn = client.app.state.nw.store._conn
    out = []
    for t in ("feedback", "verdict_marks", "chat_counts", "watches"):
        out += [str(r) for r in conn.execute(f"SELECT * FROM {t}")]
    return "\n".join(out)


def test_feedback_once_per_report_and_counts(client):
    fid = _verdict(client)
    ok = client.post("/feedback", json={"forecast_id": fid, "useful": True, "note": "mail me a@b.com see https://x.io/y ok", "lang": "zh"}, headers=ME)
    assert ok.status_code == 200
    assert client.post("/feedback", json={"forecast_id": fid, "useful": False}, headers=ME).status_code == 409
    assert client.post("/feedback", json={"forecast_id": 99999, "useful": True}, headers=ME).status_code == 404
    u = client.get("/usage").json()
    assert u["feedback"] == {"useful": 1, "not_useful": 0}
    assert u["live_verdicts"] == 1 and u["distinct_anonymous_clients"] == 1 and u["by_language"] == {"en": 1}
    note = u["last_notes"][0]["note"]
    assert "a@b.com" not in note and "https" not in note and "ok" in note


def test_feedback_is_rate_limited_per_client(client):
    conn = client.app.state.nw.store._conn
    busy = {"x-nw-client": "busybusy12345678"}
    fid = _verdict(client)
    for i in range(engagement.FEEDBACK_PER_HOUR):
        engagement.add_feedback(conn, forecast_id=1000 + i, useful=True, note="", lang="en", client=engagement.hash_client(busy["x-nw-client"], None), internal=False)
    assert client.post("/feedback", json={"forecast_id": fid, "useful": True}, headers=busy).status_code == 429
    other = {"x-nw-client": "zzzzzzzz99999999"}
    assert client.post("/feedback", json={"forecast_id": fid, "useful": True}, headers=other).status_code == 200


def test_internal_requests_are_excluded(client):
    fid = _verdict(client, {**ME, "x-nw-internal": "1"})
    client.post("/feedback", json={"forecast_id": fid, "useful": True, "note": "mine"}, headers={**ME, "x-nw-internal": "1"})
    u = client.get("/usage").json()
    assert u["live_verdicts"] == 0 and u["distinct_anonymous_clients"] == 0
    assert u["feedback"] == {"useful": 0, "not_useful": 0} and u["last_notes"] == []


def test_no_raw_ip_or_browser_id_is_stored(client):
    fid = _verdict(client)
    client.post("/feedback", json={"forecast_id": fid, "useful": True}, headers={**ME, "x-forwarded-for": "203.0.113.77"})
    client.post("/analyze", json={**PAYLOAD, "record": True}, headers={"x-forwarded-for": "198.51.100.9"})
    client.post("/watch", json={"forecast_id": fid}, headers=ME)
    text = _all_text(client)
    for raw in ("203.0.113.77", "198.51.100.9", "testclient", ME["x-nw-client"]):
        assert raw not in text
    assert engagement.hash_client("abcdefgh12345678", None) in text


def test_follow_up_counter_by_answer_kind(client):
    fid = _verdict(client)
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "why not bigger?"}], "context_forecast_id": fid}, headers=ME)
    assert r.status_code == 200
    kinds = client.get("/usage").json()["follow_ups_by_answer_kind"]
    assert sum(kinds.values()) == 1


def test_next_us_close_rules():
    fri_open = datetime(2026, 9, 25, 14, 0, tzinfo=UTC)  # 10:00 ET, Friday
    assert watches.next_us_close(fri_open) == datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
    fri_after = datetime(2026, 9, 25, 21, 0, tzinfo=UTC)
    assert watches.next_us_close(fri_after) == datetime(2026, 9, 28, 20, 0, tzinfo=UTC)  # Monday
    assert watches.next_us_close(datetime(2026, 11, 27, 15, 0, tzinfo=UTC)) == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)  # early close


def test_webhook_must_be_public_https():
    for bad in ("http://example.com/x", "https://127.0.0.1/x", "https://user:pw@example.com/x", "ftp://x.io"):
        try:
            watches.check_webhook(bad)
        except watches.BadWebhook:
            continue
        raise AssertionError(bad)
    assert watches.check_webhook("") is None


def test_watch_created_then_rechecked_with_before_and_after(client, monkeypatch):
    fid = _verdict(client)
    assert client.post("/watch", json={"forecast_id": fid, "webhook": "http://x.io/h"}, headers=ME).status_code == 422
    assert client.post("/watch", json={"forecast_id": 424242}, headers=ME).status_code == 404
    w = client.post("/watch", json={"forecast_id": fid}, headers=ME).json()
    assert w["status"] == "pending" and w["before"]["verdict"] and w["after"] is None and w["email"] == "not implemented"
    assert client.post("/watch", json={"forecast_id": fid}, headers=ME).json()["id"] == w["id"]  # asked twice, one watch
    assert client.get("/watch/nope").status_code == 404

    s = client.app.state.nw
    count = "SELECT COUNT(*) FROM forecasts WHERE kind='ticket'"
    journaled = s.store._conn.execute(count).fetchone()[0]
    assert watches.run_due(s.store._conn, watches.make_rerun(s.ctx), s.reports.get) == 0  # not yet due
    later = datetime.now(UTC) + timedelta(days=5)
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF + timedelta(hours=1))
    assert watches.run_due(s.store._conn, watches.make_rerun(s.ctx), s.reports.get, now=later) == 1
    done = client.get(f"/watch/{w['id']}").json()
    assert done["status"] == "done" and done["after"]["verdict"] and done["before"]["verdict"] == w["before"]["verdict"]
    assert s.store._conn.execute(count).fetchone()[0] == journaled  # re-check journals nothing


def test_watch_webhook_gets_a_short_post(client, monkeypatch):
    fid = _verdict(client)
    monkeypatch.setattr(watches, "check_webhook", lambda u: u)
    w = client.post("/watch", json={"forecast_id": fid, "webhook": "https://hooks.example.com/abc"}, headers=ME).json()
    assert w["webhook_host"] == "hooks.example.com" and "abc" not in str(w)
    sent = {}

    class R:
        status_code = 200

    monkeypatch.setattr("httpx.post", lambda url, json, **kw: sent.update(url=url, body=json) or R())
    s = client.app.state.nw
    watches.run_due(s.store._conn, lambda rep: rep, s.reports.get, now=datetime.now(UTC) + timedelta(days=5))
    assert sent["url"].endswith("/abc") and sent["body"]["watch_id"] == w["id"] and sent["body"]["moved"] is False


def test_a_webhook_with_a_bad_port_is_refused_not_a_server_error():
    import pytest as _pytest

    from nightwatch.journal.watches import BadWebhook, check_webhook

    for url in ("https://example.com:99999/hook", "https://example.com:abc/hook"):
        with _pytest.raises(BadWebhook):
            check_webhook(url)
