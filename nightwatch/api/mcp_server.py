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
import math
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
            "(GO, REDUCE_TO, HEDGE, REVIEW or NO_GO), what followed the most similar past moments over the same holding "
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
                "leverage": {"type": "number", "minimum": 1, "maximum": 125,
                             "description": "Leverage on the stock's Bitget perpetual; the report adds the liquidation price and how often history reached it"},
                "account_equity_usdt": {"type": "number", "exclusiveMinimum": 0},
                "thesis": {"type": "string", "description": "Why the trade; the desk's gate wants a written plan"},
                "invalidation": {"type": "string", "description": "What would prove the idea wrong"},
                "holdings": {"type": "array", "maxItems": 12,
                             "description": "What you already hold. With account_equity_usdt the report measures the whole book (one-in-twenty loss, crash replays, rebalance plans if it breaches its limit, reverse stress)",
                             "items": {"type": "object", "properties": {"ticker": {"type": "string"}, "side": {"type": "string", "enum": ["long", "short"]},
                                                                          "notional_usdt": {"type": "number", "exclusiveMinimum": 0}},
                                       "required": ["ticker", "side", "notional_usdt"], "additionalProperties": False}},
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


MAX_HOLDINGS = 12
MAX_TEXT = 4000


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


def _number(args: dict[str, Any], key: str, *, required: bool = False, low: float | None = None, high: float | None = None,
            positive: bool = True, exclusive_high: bool = False) -> float | None:
    """A numeric argument, or a ToolError a calling model can read and fix.

    JSON numbers and numeric strings are taken (models often quote them); a bool, NaN or
    infinity is not a number, and a value past the same bounds the HTTP API enforces is
    refused here rather than reaching the engine."""
    if args.get(key) is None:
        if required:
            raise ToolError(f"{key} is required and must be a number")
        return None
    v = args[key]
    if isinstance(v, bool) or not isinstance(v, int | float | str):
        raise ToolError(f"{key} must be a number")
    try:
        x = float(v)
    except ValueError as exc:
        raise ToolError(f"{key} must be a number") from exc
    if not math.isfinite(x):
        raise ToolError(f"{key} must be a finite number")
    if positive and x <= 0:
        raise ToolError(f"{key} must be greater than 0")
    if low is not None and x < low:
        raise ToolError(f"{key} must be at least {low:g}")
    if high is not None and (x >= high if exclusive_high else x > high):
        raise ToolError(f"{key} must be at most {high:g}")
    return x


def _stress_test(state: Any, args: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
    from nightwatch.analog import lens as lens_mod
    from nightwatch.api.intake import brief
    from nightwatch.decision.ticket import MAX_HOLD_HOURS, MAX_NOTIONAL, MAX_PRICE, HorizonKind, TradeTicket, stop_side_problem
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
    notional = _number(args, "notional_usdt", required=True, high=MAX_NOTIONAL)
    equity = _number(args, "account_equity_usdt", high=MAX_NOTIONAL * 100)
    stop = _number(args, "stop_price", high=MAX_PRICE, exclusive_high=True)
    leverage = _number(args, "leverage", low=1.0, high=125.0, positive=False)
    hold = str(args.get("hold") or "next_open")
    if hold not in ("next_open", "window_end", "hours"):
        raise ToolError("hold must be next_open, window_end or hours")
    hours = _number(args, "hours", high=MAX_HOLD_HOURS) if args.get("hours") is not None else None
    if hold == "hours" and hours is None:
        raise ToolError("hours must be a positive number when hold is 'hours'")
    raw_holdings = args.get("holdings") or []
    if not isinstance(raw_holdings, list):
        raise ToolError("holdings must be a list of {ticker, side, notional_usdt}")
    if len(raw_holdings) > MAX_HOLDINGS:
        # Dropping the rest would quietly measure a different book than the one described.
        raise ToolError(f"at most {MAX_HOLDINGS} holdings can be measured; {len(raw_holdings)} were given")
    held: list[tuple[str, str, float]] = []
    for h in raw_holdings:
        try:
            ht, hs, hn = str(h["ticker"]).upper().strip(), str(h["side"]).lower(), _number(h, "notional_usdt", required=True, high=MAX_NOTIONAL)
        except (KeyError, TypeError) as exc:
            raise ToolError("each holding needs ticker, side and notional_usdt") from exc
        if hs not in ("long", "short"):
            raise ToolError("each holding needs side long or short and a positive notional_usdt")
        held.append((ht, hs, hn))
    thesis, invalidation = str(args.get("thesis") or ""), str(args.get("invalidation") or "")
    if len(thesis) > MAX_TEXT or len(invalidation) > MAX_TEXT:
        raise ToolError(f"thesis and invalidation are limited to {MAX_TEXT} characters each")
    conditions = args.get("conditions") or []
    if not isinstance(conditions, list):
        raise ToolError("conditions must be a list of names from list_conditions")
    try:
        ticket = TradeTicket(
            ticker=ticker, side=Side(side), open_positions=tuple(held), notional_quote=notional,
            account_equity_quote=equity,
            horizon_kind=HorizonKind(hold), horizon_hours=hours if hold == "hours" else None,
            stop_price=stop, thesis=thesis, invalidation=invalidation,
            leverage=leverage,
            lenses=tuple(x.name for x in lens_mod.resolve([str(c) for c in conditions])),
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    problem = stop_side_problem(ticket, state.ctx.latest_spot_close(ticker, None))
    if problem:
        raise ToolError(problem)
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
        "history": {"matches": c.get("n"), "median_pct": c.get("median_pct"), "loss_p5_pct": h.get("loss_p5_pct"), "position_median_pct": h.get("pnl_median_pct"),
                    "scope": a.get("scope"), "narrowed_to": ((a.get("lens") or {}).get("description") or None)},
        "exit_cost_bps": ((payload.get("execution") or {}).get("exit_quote") or {}).get("total_cost_bps"),
        "leverage": {k: (payload.get("leverage") or {}).get(k) for k in ("leverage", "liquidation_price", "liquidation_distance_pct", "analog_hits", "analog_of", "mc_share", "presets_hit")} if payload.get("leverage") else None,
        "book": _book_summary(payload.get("portfolio")),
        "warnings": payload.get("warnings", []),
        "as_of": payload.get("as_of"),
        "provenance": payload.get("provenance"),
        "report_url": "https://nightwatch-gules.vercel.app",
    }
    return _text_result(brief(report), summary)


def _book_summary(port: dict[str, Any] | None) -> dict[str, Any] | None:
    """The whole-book numbers an agent can act on: tail before/after, crashes, plans, reverse stress."""
    if not port:
        return None
    st = port.get("stress") or {}
    return {
        "tail_loss_before": (port.get("before") or {}).get("tail_loss_quote"), "tail_loss_after": (port.get("after") or {}).get("tail_loss_quote"),
        "windows": port.get("windows"), "limit": st.get("limit_quote"), "breached": st.get("breached"),
        "crash_replays": [{"name": c["name"], "date": c.get("date"), "held": c.get("held_quote"), "with_trade": c.get("asked_quote"), "worst_ticker": c.get("worst_ticker")} for c in st.get("crashes") or []],
        "rebalance_plans": [{"lever": p["lever"], "ticker": p["ticker"], "amount": p["amount_quote"], "cost": p["cost_quote"], "achieves_limit": p["achieves_limit"],
                             "detail": p["detail"], "tail_before": p["before"]["tail_quote"], "tail_after": p["after"]["tail_quote"],
                             "worst_crash_before": p["before"].get("worst_crash_quote"), "worst_crash_after": p["after"].get("worst_crash_quote")} for p in st.get("plans") or []],
        "reverse_stress": st.get("reverse"), "liquidation": st.get("liquidation"),
    }


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
    if not isinstance(params, dict):
        return _err(msg_id, -32602, "params must be an object")
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
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _ok(msg_id, _text_result("arguments must be an object", is_error=True))
        try:
            return _ok(msg_id, handler(state, arguments))
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
        if not body:
            return 400, _err(None, -32600, "invalid request: an empty batch")
        replies = [r for r in (handle(state, m) for m in body) if r is not None]
        return (200, replies) if replies else (202, None)
    reply = handle(state, body)
    return (200, reply) if reply is not None else (202, None)
