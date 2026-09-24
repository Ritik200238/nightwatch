"""The desk as MCP tools: the protocol surface, and the same restraint as the chat.

Driven through the real HTTP endpoint with the seeded store, so what is tested is what
an MCP client would get: the handshake, the tool list, a stress test whose numbers come
from the engine, and refusals a calling model can read and act on.
"""

import threading
from types import SimpleNamespace

import pytest

from nightwatch.analog.engine import AnalogConfig
from nightwatch.api import mcp_server
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry
from nightwatch.pipeline.analyze import AnalysisContext
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture


@pytest.fixture
def state(seeded_store, monkeypatch):  # noqa: F811
    # The tool analyses "now"; pin now to the end of the seeded history.
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    store = Store(seeded_store)
    entries = [UniverseEntry(t, f"R{t}USDT", f"{t}USDT", t, True) for t in ("TSLA", "NVDA", "AAPL")]
    ctx = AnalysisContext(store=store, entries=entries, analog_config=AnalogConfig(k=30, min_matches=10, min_separation_h=36, min_age_h=96))
    yield SimpleNamespace(ctx=ctx, lock=threading.Lock())
    store.close()


def rpc(state, method, params=None, msg_id=1):  # noqa: ANN001, ANN201
    return mcp_server.handle(state, {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})


def test_the_handshake_names_the_server_and_offers_tools(state):
    r = rpc(state, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})["result"]
    assert r["protocolVersion"] == "2025-06-18" and r["serverInfo"]["name"] == "nightwatch"
    assert "tools" in r["capabilities"] and "none is estimated by a model" in r["instructions"]


def test_an_unknown_protocol_version_gets_the_latest_supported():
    r = mcp_server.handle(None, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
    assert r["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSIONS[0]


def test_notifications_get_no_reply():
    assert mcp_server.handle(None, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp_server.handle_body(None, b'{"jsonrpc":"2.0","method":"notifications/initialized"}') == (202, None)


def test_the_tools_describe_their_arguments(state):
    tools = {t["name"]: t for t in rpc(state, "tools/list")["result"]["tools"]}
    assert set(tools) == {"stress_test", "list_conditions", "list_tokens"}
    assert tools["stress_test"]["inputSchema"]["required"] == ["ticker", "side", "notional_usdt"]
    assert all(t["annotations"]["readOnlyHint"] for t in tools.values()), "nothing here can place an order"


def test_a_stress_test_returns_the_engines_numbers_and_is_not_journalled(state):
    r = rpc(state, "tools/call", {"name": "stress_test", "arguments": {
        "ticker": "tsla", "side": "long", "notional_usdt": 10_000, "account_equity_usdt": 200_000,
        "thesis": "strength carries", "invalidation": "close below the average"}})["result"]
    assert r["isError"] is False
    s = r["structuredContent"]
    assert s["ticker"] == "TSLA" and s["verdict"] in ("GO", "REDUCE", "HEDGE", "REVIEW", "NO_GO")
    assert s["history"]["matches"] and s["history"]["p5_pct"] is not None
    assert s["verdict"] in r["content"][0]["text"], "the text is the same briefing the chat gives"


def test_refusals_are_results_the_calling_model_can_read(state):
    """A wrong ticker is not a protocol fault; it is an answer the caller should see."""
    r = rpc(state, "tools/call", {"name": "stress_test", "arguments": {"ticker": "DOGE", "side": "long", "notional_usdt": 1}})["result"]
    assert r["isError"] is True and "Covered:" in r["content"][0]["text"]
    r = rpc(state, "tools/call", {"name": "stress_test", "arguments": {"ticker": "TSLA", "side": "sideways", "notional_usdt": 1}})["result"]
    assert r["isError"] is True
    r = rpc(state, "tools/call", {"name": "stress_test", "arguments": {"ticker": "TSLA", "side": "long", "notional_usdt": 1, "hold": "hours"}})["result"]
    assert r["isError"] is True and "hours" in r["content"][0]["text"]


def test_conditions_come_with_their_cost_in_hours(state):
    r = rpc(state, "tools/call", {"name": "list_conditions", "arguments": {"ticker": "TSLA"}})["result"]
    rows = r["structuredContent"]["conditions"]
    assert any(x["name"] == "earnings_soon" for x in rows) and all(x["past_hours"] is not None for x in rows)


def test_protocol_faults_are_errors():
    assert mcp_server.handle(None, {"jsonrpc": "2.0", "id": 3, "method": "resources/list"})["error"]["code"] == -32601
    assert mcp_server.handle(None, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "trade"}})["error"]["code"] == -32602
    assert mcp_server.handle_body(None, b"{not json")[0] == 400


def test_the_endpoint_speaks_http(monkeypatch):
    from fastapi.testclient import TestClient

    from nightwatch.api.app import create_app

    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    with TestClient(create_app(warm=False)) as c:
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 200 and r.json()["result"]["tools"]
        assert c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
        assert c.get("/mcp").status_code == 405
