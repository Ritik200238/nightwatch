"""Bitget's US-stock data going down must read as an outage, never as a quiet stock or a live feed.

All HTTP is a mock transport or a fake client: nothing here touches the network.
"""

import json
from datetime import timedelta

import httpx

from nightwatch.api.sources import street_row
from nightwatch.data import bitget_mcp
from nightwatch.data.bitget_mcp import BitgetMcpClient
from nightwatch.features import street
from nightwatch.time_utils import UTC, utc_now
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture
from tests.test_street import FIXTURE, FakeClient

DOWN = {"ok": False, "down_since": "2026-10-05T08:00:00+00:00", "last_ok": "2026-10-05T07:00:00+00:00", "http_status": 503, "error": "HTTP 503"}
UP = {"ok": True, "down_since": None, "last_ok": None, "http_status": None, "error": None}


class StatusFake(FakeClient):
    """A client whose health is set by the test, like the real one's."""

    def __init__(self, status, **kw):  # noqa: ANN001, ANN003
        super().__init__(**kw)
        self.state = status

    def status(self):  # noqa: ANN201
        return self.state


# ---------------------------------------------------------------- the client


def _counting(status: int):  # noqa: ANN202
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status)

    return calls, httpx.Client(transport=httpx.MockTransport(handler))


def test_two_failures_in_a_row_mark_the_service_down_with_its_status_code():
    calls, http = _counting(503)
    c = BitgetMcpClient(client=http)
    assert c.status()["ok"] is None, "no call yet: unknown, not up"
    c.query("equity_price_quote", symbol="TSLA")
    assert c.status()["ok"] is None, "one failure is not yet an outage"
    c.query("equity_price_quote", symbol="TSLA")
    s = c.status()
    assert s["ok"] is False and s["http_status"] == 503 and s["down_since"] and s["last_ok"] is None


def test_a_service_known_to_be_down_is_not_called_again_during_the_cooldown():
    calls, http = _counting(503)
    c = BitgetMcpClient(client=http)
    for _ in range(2):
        c.query("equity_price_quote", symbol="TSLA")
    n = calls["n"]
    for _ in range(10):
        assert c.query("equity_price_quote", symbol="TSLA") == []
    assert calls["n"] == n, "96 calls in a warm-up must not each wait out a timeout"


def test_a_good_answer_ends_the_outage():
    state = {"up": False}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if not state["up"]:
            return httpx.Response(503)
        if body["method"] == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "s"}, text="data: {}\n")
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        doc = {"success": True, "data": {"results": []}}
        msg = {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": json.dumps(doc)}]}}
        return httpx.Response(200, text="data: " + json.dumps(msg) + "\n")

    c = BitgetMcpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    c.query("x"), c.query("x")
    assert c.status()["ok"] is False
    state["up"], c._cool_until = True, 0.0  # the cooldown has passed
    assert c.query("equity_price_quote", symbol="ETF") == []
    s = c.status()
    assert s["ok"] is True and s["down_since"] is None and s["last_ok"], "an empty answer is the service working (an ETF has no analysts)"


def test_the_cooldown_constants_are_short_enough_to_recover_within_a_minute_or_two():
    assert bitget_mcp.COOLDOWN_S <= 120 and bitget_mcp.DOWN_AFTER >= 2


# ---------------------------------------------------------------- /sources


def test_the_count_ignores_blank_views_and_the_outage_is_named():
    now = utc_now()
    full = street.build(FakeClient(), "TSLA", now=now)
    blank = street.StreetView(ticker="NVDA", fetched_at=now.isoformat())
    row = street_row([(now, full), (now, blank)], UP, now)
    assert row["rows"] == 1 and row["latest_label"] == "1 tokens with current street data" and row["status"] == "ok"

    down = street_row([(now - timedelta(hours=3), full), (now, blank)], DOWN, now)
    assert down["status"] == "unavailable" and down["http_status"] == 503
    assert down["latest_label"].startswith("Bitget US-stock data: unavailable since 08:00 UTC (HTTP 503)")
    assert "3.0 h ago" in down["latest_label"], "what it still holds is labelled with its age"


def test_a_cold_cache_during_an_outage_says_unavailable_not_zero_tokens_current():
    now = utc_now()
    row = street_row([], DOWN, now)
    assert row["rows"] == 0 and "unavailable" in row["latest_label"] and "current street data" not in row["latest_label"]


def test_outage_words():
    assert street.outage_clause(DOWN) == " since 08:00 UTC (HTTP 503)"
    assert street.outage_clause(UP) == "" and street.outage_clause(None) == ""
    assert street.last_good_label(3 * 3600) == "last good 3.0 h ago"
    assert street.last_good_label(20 * 60) == "last good 20 min ago"
    assert street.last_good_label(14 * 3600) == "last good 14 h ago"


# ---------------------------------------------------------------- the cache


def test_a_failed_refresh_keeps_the_last_good_view_and_a_healthy_blank_is_cached(seeded_store):  # noqa: F811
    from tests.test_pipeline import _ctx

    ctx = _ctx(seeded_store)
    ctx.street_client = StatusFake(UP)
    good = ctx.street_for("TSLA")
    assert good is not None and not good.empty
    # The service goes down and every part comes back empty.
    ctx.street_client = StatusFake(DOWN, data={})
    ctx._street["TSLA"] = (utc_now() - timedelta(hours=3), good)
    got = ctx.street_for("TSLA", fetch=True)
    assert got is good, "served as last good, not overwritten by a blank"
    assert ctx._street["TSLA"][1] is good
    # Up and genuinely empty (an ETF): the blank is the answer and is cached.
    ctx.street_client = StatusFake(UP, data={})
    blank = ctx.street_for("QQQ")
    assert blank is not None and blank.empty and "QQQ" in ctx._street


def test_last_good_is_not_served_past_a_day(seeded_store):  # noqa: F811
    from tests.test_pipeline import _ctx

    ctx = _ctx(seeded_store)
    ctx.street_client = StatusFake(UP)
    good = ctx.street_for("TSLA")
    ctx._street["TSLA"] = (utc_now() - timedelta(hours=30), good)
    ctx.street_client = StatusFake(DOWN, data={})
    assert ctx.street_for("TSLA", fetch=False) is None


# ---------------------------------------------------------------- in the report


def _analyse(store_path, monkeypatch, client, *, cached_age_h=None):  # noqa: ANN001, ANN202
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from tests.test_pipeline import AS_OF, _ctx

    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    ctx = _ctx(store_path)
    if cached_age_h is not None:
        ctx.street_client = StatusFake(UP)
        view = street.build(FakeClient(), "TSLA", now=AS_OF - timedelta(hours=cached_age_h))
        view.fetched_at = (AS_OF - timedelta(hours=cached_age_h)).astimezone(UTC).isoformat()
        ctx._street["TSLA"] = (AS_OF - timedelta(hours=cached_age_h), view)
    ctx.street_client = client
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
    return analyze(ctx, ticket, as_of=AS_OF, record=False).to_dict()


def test_an_outage_with_nothing_cached_puts_a_warning_and_a_provenance_note_on_the_report(seeded_store, monkeypatch):  # noqa: F811
    r = _analyse(seeded_store, monkeypatch, StatusFake(DOWN, data=FIXTURE))
    assert r["street"] is None
    assert any("unavailable since 08:00 UTC (HTTP 503)" in w and "no street section" in w for w in r["warnings"])
    row = next(s for s in r["sources"] if s["kind"] == "bitget_mcp")
    assert row["status"] == "unavailable" and row["rows_used"] == 0 and row["last_ts"] is None
    assert r["provenance"]["items"]["street"]["unavailable"] is True


def test_no_outage_and_nothing_cached_is_not_called_an_outage(seeded_store, monkeypatch):  # noqa: F811
    r = _analyse(seeded_store, monkeypatch, StatusFake(UP, data=FIXTURE))
    assert not any("US-stock data" in w for w in r["warnings"])
    assert not any(s["kind"] == "bitget_mcp" for s in r["sources"])


def test_a_cached_view_served_during_an_outage_is_labelled_with_its_age_and_never_live(seeded_store, monkeypatch):  # noqa: F811
    r = _analyse(seeded_store, monkeypatch, StatusFake(DOWN, data={}), cached_age_h=3)
    s = r["street"]
    assert s and s["stale"] is True and s["age_label"] == "last good 3.0 h ago"
    assert s["token_vs_live_bps"] is None and s["quote_gap_bps"] is None, "a 3 h old price must not stand in for the live one"
    assert any("last good 3.0 h ago since 08:00 UTC (HTTP 503)" in w for w in r["warnings"])
    row = next(x for x in r["sources"] if x["kind"] == "bitget_mcp")
    assert row["status"] == "last_good" and row["note"] == "last good 3.0 h ago"
    assert r["provenance"]["items"]["street"]["stale"] is True


def test_a_fresh_view_from_a_healthy_service_is_live(seeded_store, monkeypatch):  # noqa: F811
    r = _analyse(seeded_store, monkeypatch, StatusFake(UP, data=FIXTURE), cached_age_h=0.2)
    s = r["street"]
    assert s and s["stale"] is False and s["age_label"] is None
    assert not any("US-stock data" in w for w in r["warnings"])
