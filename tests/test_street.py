"""Street context from Bitget's data: what it says, and what it is not allowed to do.

The fixture is a trimmed copy of real responses for TSLA on 2026-09-24, so the parsing
is tested against the service's actual field names and rating vocabulary, not a guess
at them.
"""

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from nightwatch.data.bitget_mcp import BitgetMcpClient, _payload
from nightwatch.features import street
from nightwatch.time_utils import UTC
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture

FIXTURE = json.loads((Path(__file__).parent / "data" / "bitget_mcp_tsla_2026-09-24.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 24, 6, 0, tzinfo=UTC)


class FakeClient:
    def __init__(self, data=FIXTURE, fail=()):  # noqa: ANN001
        self.data, self.fail, self.calls = data, set(fail), []

    def query(self, entry_id, **params):  # noqa: ANN001, ANN003, ANN201
        self.calls.append(entry_id)
        return [] if entry_id in self.fail else list(self.data.get(entry_id, []))


def test_the_street_view_is_built_from_the_real_field_names():
    v = street.build(FakeClient(), "TSLA", now=NOW)
    assert v.last_price and v.prev_close
    assert v.n_firms > 0 and v.bullish + v.neutral + v.bearish <= v.n_firms
    assert v.median_target and v.target_gap_pct is not None
    assert v.mood_score is not None and v.mood_rating == "fear"


def test_one_firm_repeating_itself_is_one_opinion():
    rows = [
        {"published_date": "2026-09-10", "analyst_firm": "A", "rating_current": "买入", "price_target": 400.0, "action": "维持"},
        {"published_date": "2026-09-01", "analyst_firm": "A", "rating_current": "买入", "price_target": 390.0, "action": "维持"},
        {"published_date": "2026-09-05", "analyst_firm": "B", "rating_current": "卖出", "price_target": 200.0, "action": "下调评级"},
    ]
    v = street.StreetView(ticker="X", fetched_at="", last_price=300.0)
    street.summarise_ratings(v, rows, NOW)
    assert (v.n_firms, v.bullish, v.bearish) == (2, 1, 1)
    assert v.median_target == 300.0, "each firm's latest target, not every restatement"
    assert v.downgrades_recent == 1 and v.recent_changes[0].action == "downgraded"


def test_ratings_older_than_the_window_are_left_out():
    rows = [{"published_date": "2025-01-01", "analyst_firm": "A", "rating_current": "买入", "price_target": 1.0}]
    v = street.StreetView(ticker="X", fetched_at="")
    street.summarise_ratings(v, rows, NOW)
    assert v.n_ratings == 0 and v.median_target is None


def test_only_open_market_insider_trades_count():
    """Awards and option exercises are pay, not someone choosing to buy or sell."""
    rows = [
        {"transaction_date": "2026-09-08", "transaction_type": "S", "securities_transacted": 100, "transaction_price": 10.0, "owner_name": "CFO"},
        {"transaction_date": "2026-09-07", "transaction_type": "A", "securities_transacted": 9999, "transaction_price": 10.0},
        {"transaction_date": "2026-09-06", "transaction_type": "M", "securities_transacted": 9999, "transaction_price": 1.0},
        {"transaction_date": "2026-09-05", "transaction_type": "P", "securities_transacted": 10, "transaction_price": 10.0},
    ]
    v = street.StreetView(ticker="X", fetched_at="")
    street.summarise_insiders(v, rows, NOW)
    assert (v.insider_sells, v.insider_buys) == (1, 1)
    assert v.insider_sold_value == 1000.0 and v.insider_bought_value == 100.0


def test_a_part_that_fails_leaves_the_rest():
    """An ETF has no analyst coverage; its quote and the market mood still come through."""
    v = street.build(FakeClient(fail={"equity_estimates_price_target", "equity_ownership_insider_trading"}), "QQQ", now=NOW)
    assert v.last_price and v.mood_score is not None and v.n_ratings == 0 and not v.empty


def test_nothing_at_all_is_empty_not_an_error():
    assert street.build(FakeClient(data={}), "X", now=NOW).empty


# ---------------------------------------------------------------- the quote checks


def test_the_close_check_compares_like_with_like():
    """At night the desk's native price is the last close; comparing it with Bitget's
    live overnight price would call every quiet night a data error."""
    v = street.StreetView(ticker="X", fetched_at="", last_price=377.5, prev_close=380.19)
    assert street.quote_disagreement_bps(v, 380.12, native_age_h=9.0) == pytest.approx(-1.8, abs=0.1)
    # During the session both are current, so the live price is the right reference.
    assert street.quote_disagreement_bps(v, 377.6, native_age_h=0.2) == pytest.approx(2.6, abs=0.1)


def test_the_token_is_measured_against_the_live_price():
    v = street.StreetView(ticker="X", fetched_at="", last_price=377.5)
    assert street.token_vs_live_bps(v, 377.71) == pytest.approx(5.6, abs=0.1)
    assert street.token_vs_live_bps(None, 1.0) is None and street.token_vs_live_bps(v, None) is None


# -------------------------------------------------------------------- the client


def test_the_client_reads_server_sent_events_and_plain_json():
    assert _payload('event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n') == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert _payload('{"jsonrpc":"2.0","id":2,"result":{}}') == {"jsonrpc": "2.0", "id": 2, "result": {}}
    assert _payload("") is None and _payload("data: not json") is None


def _server(expire_first: bool = False):  # noqa: ANN202
    state = {"sessions": 0, "expired": expire_first}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            state["sessions"] += 1
            return httpx.Response(200, headers={"mcp-session-id": f"s{state['sessions']}"}, text="data: {}\n")
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if state["expired"]:
            state["expired"] = False
            return httpx.Response(404, text="session expired")
        doc = {"success": True, "data": {"results": [{"symbol": body["params"]["arguments"]["params"]["symbol"], "last_price": 1.0}]}}
        msg = {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": json.dumps(doc)}]}}
        return httpx.Response(200, text="event: message\ndata: " + json.dumps(msg) + "\n\n")

    return state, httpx.Client(transport=httpx.MockTransport(handler))


def test_the_client_opens_a_session_and_returns_rows():
    state, http = _server()
    rows = BitgetMcpClient(client=http).query("equity_price_quote", symbol="TSLA")
    assert rows == [{"symbol": "TSLA", "last_price": 1.0}] and state["sessions"] == 1


def test_an_expired_session_is_reopened_once():
    state, http = _server(expire_first=True)
    rows = BitgetMcpClient(client=http).query("equity_price_quote", symbol="NVDA")
    assert rows and state["sessions"] == 2


def test_an_outage_is_no_data_not_an_exception():
    """A context feed being down must never fail an analysis."""
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert BitgetMcpClient(client=http).query("equity_price_quote", symbol="TSLA") == []


# ------------------------------------------------------------------ in the report


def _analyse(store_path, monkeypatch, *, now):  # noqa: ANN001, ANN202
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from tests.test_pipeline import AS_OF, _ctx

    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: now)
    ctx = _ctx(store_path)
    ctx.street_client = FakeClient()
    ctx.street_for("TSLA")  # the warm-up's job: an analysis itself never waits on the feed
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
    return analyze(ctx, ticket, as_of=AS_OF, record=False).to_dict()


def test_an_analysis_of_today_carries_the_street(seeded_store, monkeypatch):  # noqa: F811
    from tests.test_pipeline import AS_OF

    r = _analyse(seeded_store, monkeypatch, now=AS_OF)
    assert r["street"] and r["street"]["n_firms"] > 0
    assert "token_vs_live_bps" in r["street"] and any(s["kind"] == "bitget_mcp" for s in r["sources"])


def test_a_past_moment_never_gets_todays_street(seeded_store, monkeypatch):  # noqa: F811
    """Today's analyst targets on a replay of last month would be lookahead."""
    from datetime import timedelta

    from tests.test_pipeline import AS_OF

    r = _analyse(seeded_store, monkeypatch, now=AS_OF + timedelta(days=30))
    assert r["street"] is None


def test_an_analysis_never_waits_on_the_street_feed(seeded_store, monkeypatch):  # noqa: F811
    """The analyst feed takes 1-9 s. A cold cache means no street section this time and a
    background refresh, not a request that sits waiting for a context feed."""
    import threading

    from tests.test_pipeline import _ctx

    gate = threading.Event()

    class Slow(FakeClient):
        def query(self, entry_id, **params):  # noqa: ANN001, ANN003, ANN201
            gate.wait(5)
            return super().query(entry_id, **params)

    ctx = _ctx(seeded_store)
    ctx.street_client = Slow()
    assert ctx.street_for("TSLA", fetch=False) is None, "returned at once, with nothing cached"
    assert "TSLA" in ctx._street_pending
    gate.set()
    for _ in range(100):
        if "TSLA" in ctx._street:
            break
        threading.Event().wait(0.05)
    assert ctx.street_for("TSLA", fetch=False) is not None, "the background refresh filled it"
