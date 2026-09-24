"""The desk as a tool other AI clients can call, over MCP.

A trader who already works inside Claude, Cursor or an Agent Hub setup should not have
to open another tab to ask whether a position survives the night. This exposes the
desk's own capabilities as Model Context Protocol tools, so that client's model can call
"stress-test this trade" the same way it calls anything else, and get back the same
numbers the desk page shows.

Stateless streamable HTTP: every request is a JSON-RPC message posted to one endpoint,
and every reply is plain JSON. No session is needed because no tool keeps state between
calls, and a stateless server is the one the protocol lets a proxy sit in front of.

The same rule holds here as everywhere else. The calling model chooses a tool and fills
in its arguments; every number in the reply is computed by the engine. And an analysis
requested through here is not journalled: it is an agent asking on someone's behalf, and
the calibration record is kept for analyses a person asked the desk for directly.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER = {"name": "nightwatch", "version": "1", "title": "Nightwatch - decision stress testing for tokenized US stocks"}
INSTRUCTIONS = (
    "Nightwatch stress-tests a position in a tokenized US stock (an rToken on Bitget) before it is opened: what happened "
    "after past moments like now, preset stress tests, the live cost of exiting, and a sized verdict. Call stress_test "
    "with the trade. Every number returned is computed from stored market data; none is estimated by a model."
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "stress_test",
        "title": "Stress-test a trade",
        "description": (
            "Stress-test a proposed position in a tokenized US stock before it is opened. Returns a sized verdict "
            "(GO, REDUCE, HEDGE, REVIEW or NO_GO), what followed the most similar past moments over the same holding "
            "period, the worst preset stress tests, the live cost of exiting, and the caveats. Use conditions to "
            "compare only against a kind of night, e.g. ['earnings_soon'] - see list_conditions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "US stock ticker, e.g. TSLA, NVDA, AAPL, SPY"},
                "side": {"type": "string", "enum": ["long", "short"]},
                "notional_usdt": {"type": "number", "exclusiveMinimum": 0, "description": "Position size in USDT"},
                "hold": {"type": "string", "enum": ["next_open", "window_end", "hours"], "default": "next_open",
                         "description": "next_open: until the next US regular open. window_end: to the end of the current closed window or session."},
                "hours": {"type": "number", "exclusiveMinimum": 0, "description": "Holding period in hours, when hold is 'hours'"},
                "stop_price": {"type": "number", "exclusiveMinimum": 0},
                "account_equity_usdt": {"type": "number", "exclusiveMinimum": 0},
                "thesis": {"type": "string", "description": "Why the trade; the desk's gate wants a written plan"},
                "invalidation": {"type": "string", "description": "What would prove the idea wrong"},
                "conditions": {"type": "array", "items": {"type": "string"}, "description": "Names from list_conditions"},
            },
            "required": ["ticker", "side", "notional_usdt"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "list_conditions",
        "title": "Conditions the search can be narrowed to",
        "description": "The named conditions stress_test can compare against, and how many past hours each leaves for a token.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "list_tokens",
        "title": "Tokens the desk covers",
        "description": "The tokenized US stocks with stored history, i.e. the tickers stress_test accepts.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


class ToolError(ValueError):
    """A call the desk understood and could not answer, said to the caller as a result."""


def _ok(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id: Any, code: int, message: str) -> dict[str, Any]:  # noqa: ANN401
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _text_result(text: str, structured: dict[str, Any] | None = None, *, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _stress_test(state: Any, args: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
    from nightwatch.analog import lens as lens_mod
    from nightwatch.api.intake import brief
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.features.snapshot import InsufficientData
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side

    ticker = str(args.get("ticker") or "").upper().strip()
    known = set(state.ctx.tickers_with_data())
    if ticker not in known:
        raise ToolError(f"{ticker or 'that'} is not a token the desk has history for. Covered: {', '.join(sorted(known))}.")
    side = str(args.get("side") or "long").lower()
    if side not in ("long", "short"):
        raise ToolError("side must be 'long' or 'short'")
    try:
        notional = float(args["notional_usdt"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("notional_usdt is required and must be a number") from exc
    hold = str(args.get("hold") or "next_open")
    if hold not in ("next_open", "window_end", "hours"):
        raise ToolError("hold must be next_open, window_end or hours")
    hours = args.get("hours")
    if hold == "hours" and not (isinstance(hours, int | float) and hours > 0):
        raise ToolError("hours must be a positive number when hold is 'hours'")
    try:
        ticket = TradeTicket(
            ticker=ticker, side=Side(side), notional_quote=notional,
            account_equity_quote=args.get("account_equity_usdt"),
            horizon_kind=HorizonKind(hold), horizon_hours=float(hours) if hold == "hours" else None,
            stop_price=args.get("stop_price"), thesis=str(args.get("thesis") or ""), invalidation=str(args.get("invalidation") or ""),
            lenses=tuple(x.name for x in lens_mod.resolve(list(args.get("conditions") or []))),
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    try:
        with state.lock:
            report = analyze(state.ctx, ticket, record=False)
    except InsufficientData as exc:
        raise ToolError(str(exc)) from exc
    payload = report.to_dict()
    a = payload.get("analog") or {}
    h = (a.get("horizons") or {}).get(payload.get("primary_horizon")) or {}
    c = h.get("cohort") or {}
    summary = {
        "ticker": ticker, "side": side, "notional_usdt": notional,
        "verdict": payload["verdict"]["verdict"], "recommended_notional_usdt": payload["verdict"].get("recommended_notional"),
        "reasons": payload["verdict"].get("reasons", []), "horizon_hours": payload.get("horizon_h"),
        "history": {"matches": c.get("n"), "median_pct": c.get("median_pct"), "p5_pct": h["p5_adjusted"] if h.get("p5_adjusted") is not None else c.get("p5"),
                    "scope": a.get("scope"), "narrowed_to": ((a.get("lens") or {}).get("description") or None)},
        "exit_cost_bps": ((payload.get("execution") or {}).get("exit_quote") or {}).get("total_cost_bps"),
        "warnings": payload.get("warnings", []),
        "as_of": payload.get("as_of"),
        "report_url": "https://nightwatch-gules.vercel.app",
    }
    return _text_result(brief(report), summary)


def _list_conditions(state: Any, args: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
    from nightwatch.analog import lens as lens_mod
    from nightwatch.time_utils import utc_now

    menu = lens_mod.menu()
    counts: dict[str, int] = {}
    ticker = str(args.get("ticker") or "").upper().strip()
    if ticker and ticker in set(state.ctx.tickers_with_data()):
        with state.lock:
            counts = lens_mod.sample_sizes(state.ctx.feature_frame(ticker, utc_now()))
    rows = [{**m, "past_hours": counts.get(m["name"])} for m in menu]
    text = "\n".join(f"{r['name']}: {r['label']} - {r['definition']}" + (f" ({r['past_hours']:,} past hours in {ticker})" if r["past_hours"] is not None else "") for r in rows)
    return _text_result(text, {"conditions": rows})


def _list_tokens(state: Any, args: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401, ARG001
    tickers = sorted(state.ctx.tickers_with_data())
    return _text_result(", ".join(tickers), {"tokens": tickers})


HANDLERS = {"stress_test": _stress_test, "list_conditions": _list_conditions, "list_tokens": _list_tokens}


def handle(state: Any, message: Any) -> dict[str, Any] | None:  # noqa: ANN401
    """One JSON-RPC message in, one reply out - or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _err(message.get("id") if isinstance(message, dict) else None, -32600, "invalid request")
    method, msg_id, params = message["method"], message.get("id"), message.get("params") or {}
    if msg_id is None:
        return None  # notifications/initialized and friends need no reply
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _ok(msg_id, {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER,
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _ok(msg_id, {})
    if method == "tools/list":
        return _ok(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            return _err(msg_id, -32602, f"unknown tool: {name}")
        try:
            return _ok(msg_id, handler(state, params.get("arguments") or {}))
        except ToolError as exc:
            # A refusal the caller's model should read and act on, not a protocol fault.
            return _ok(msg_id, _text_result(str(exc), is_error=True))
        except Exception:  # noqa: BLE001 - a tool failing must not take the endpoint down
            log.exception("mcp tool %s failed", name)
            return _ok(msg_id, _text_result("The desk failed to answer that call; the error is logged.", is_error=True))
    return _err(msg_id, -32601, f"method not found: {method}")


def handle_body(state: Any, raw: bytes) -> tuple[int, Any]:  # noqa: ANN401
    """A POSTed body - one message or a batch - to an HTTP status and a JSON reply."""
    try:
        body = json.loads(raw or b"null")
    except json.JSONDecodeError:
        return 400, _err(None, -32700, "parse error")
    if isinstance(body, list):
        replies = [r for r in (handle(state, m) for m in body) if r is not None]
        return (200, replies) if replies else (202, None)
    reply = handle(state, body)
    return (200, reply) if reply is not None else (202, None)
