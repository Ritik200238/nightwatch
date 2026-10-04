"""Bitget's ``bitget-signal`` research Skill backend, over MCP: a checked perception input.

The Skill's data server is unreliable. Probed on 30 Sep, news, earnings, sentiment, macro,
rates and prices mostly time out or return empty errors; ``technical_analysis`` answers, and
its RSI matched the desk's own RSI14 from Bitget candles. Its Bollinger output was seen
inverted (upper below lower), so nothing here reads Bollinger.

So this client is built to be distrusted:

* **Fresh session per fetch.** Late or mismatched replies arrive after timeouts on a
  shared session; a new session each call, and a reply is used only if its JSON-RPC id
  is the one asked for.
* **It never raises.** Every failure is "no reading" (``None``).
* The reading is context; ``nightwatch.features.signal`` cross-checks it against the
  desk's own candles before it is shown.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

URL = "https://datahub.noxiaohao.com/mcp"
PROTOCOL = "2025-06-18"
CLIENT = {"name": "nightwatch", "version": "1"}
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
# What health() tries: (tool, arguments). A reply with usable JSON counts. These are the
# calls the desk actually makes. Three earlier probes named tools the server does not have
# (full_analysis, market_sentiment, news), which made a working feed read "mostly failing";
# on 4 Oct the server's other tools (sentiment_index, tradfi_news, news_feed, macro,
# rates) all timed out at 15 s, so the desk does not use them.
HEALTH_PROBES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("technical_analysis", {"action": "rsi", "symbol": "TSLA"}),
    ("technical_analysis", {"action": "macd", "symbol": "TSLA"}),
    ("technical_analysis", {"action": "full_analysis", "symbol": "TSLA"}),
)


def _message(text: str, want_id: int) -> dict[str, Any] | None:
    """The JSON-RPC message in a body (SSE or plain JSON) whose id is ``want_id``."""
    lines = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")] or [text.strip()]
    for raw in reversed(lines):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("id") == want_id:
            return msg
    return None


class BitgetSignalClient:
    def __init__(self, *, url: str = URL, timeout_s: float = 6.0, client: httpx.Client | None = None):
        self.url = url
        self.timeout_s = timeout_s
        self._http = client or httpx.Client(timeout=timeout_s)

    def _post(self, body: dict[str, Any], session: str | None) -> httpx.Response:
        headers = dict(HEADERS)
        if session:
            headers["mcp-session-id"] = session
            headers["mcp-protocol-version"] = PROTOCOL
        return self._http.post(self.url, json=body, headers=headers, timeout=self.timeout_s)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """One tool call on its own session; the parsed JSON it returned, or None."""
        try:
            r = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT}}, None)
            r.raise_for_status()
            session = r.headers.get("mcp-session-id")
            if not session:
                return None
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
            r = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}}, session)
            r.raise_for_status()
            msg = _message(r.text, 2)
            result = (msg or {}).get("result") or {}
            if not msg or result.get("isError"):
                return None
            text = "".join(p.get("text", "") for p in result.get("content", []) if isinstance(p, dict))
            doc = json.loads(text)
            return doc if isinstance(doc, dict) and "error" not in doc else None
        except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
            log.info("bitget signal %s %s failed: %s", name, arguments, exc)
            return None

    def rsi(self, ticker: str) -> dict[str, Any] | None:
        """{"rsi", "timeframe", "signal", "period"} or None."""
        doc = self.call("technical_analysis", {"action": "rsi", "symbol": ticker})
        if not doc or isinstance(doc.get("rsi"), bool) or not isinstance(doc.get("rsi"), (int, float)) or not 0 <= doc["rsi"] <= 100:
            return None
        return doc

    def macd(self, ticker: str) -> dict[str, Any] | None:
        """{"macd", "signal", "histogram", "cross", "timeframe"} or None."""
        doc = self.call("technical_analysis", {"action": "macd", "symbol": ticker})
        if not doc or not all(isinstance(doc.get(k), (int, float)) for k in ("macd", "signal", "histogram")):
            return None
        return doc

    def health(self) -> dict[str, Any]:
        """Try a few cheap tools: how many answered."""
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=len(HEALTH_PROBES)) as pool:
            docs = list(pool.map(lambda p: self.call(*p), HEALTH_PROBES))
        return {"answering": sum(d is not None for d in docs), "tried": len(HEALTH_PROBES)}

    def close(self) -> None:
        self._http.close()
