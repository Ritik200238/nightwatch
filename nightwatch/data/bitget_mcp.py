"""Bitget's US-stock data service, over MCP.

The hackathon's recommended information layer for a research workbench is
``bitget-mcp-server``: a read-only Model Context Protocol endpoint with US quotes,
fundamentals, analyst estimates, ownership, news and a market sentiment index. It needs
no account and no key.

The protocol surface is small and this client speaks only the part of it the desk uses:
open a session (``initialize``, then ``notifications/initialized``), then call the
server's ``do_query`` tool with a catalogue entry id and its parameters. Replies come
back as server-sent events; the last ``data:`` line carries the JSON-RPC result, whose
text content is itself a JSON document with ``success`` and ``data.results``.

Two properties matter more than coverage:

* **It never blocks an analysis.** Every call has a short timeout and every failure is
  reported as "no data" rather than raised, because a sized verdict must not depend on
  an optional context feed being up.
* **It re-opens its session by itself.** Sessions expire; a request refused for that
  reason is retried once on a fresh one rather than surfacing as an outage.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import httpx

log = logging.getLogger(__name__)

URL = "https://agent.bitget.com/mcp"
PROTOCOL = "2025-06-18"
CLIENT = {"name": "nightwatch", "version": "1"}
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


class BitgetMcpError(RuntimeError):
    """The service answered, but not with data."""


def _payload(text: str) -> dict[str, Any] | None:
    """The JSON-RPC message in a response body, whether it came as SSE or plain JSON."""
    lines = [ln[6:] for ln in text.splitlines() if ln.startswith("data: ")]
    raw = lines[-1] if lines else text.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


class BitgetMcpClient:
    """A small, thread-safe client for the read-only data catalogue."""

    def __init__(self, *, url: str = URL, timeout_s: float = 6.0, client: httpx.Client | None = None):
        self.url = url
        self.timeout_s = timeout_s
        self._http = client or httpx.Client(timeout=timeout_s)
        self._session: str | None = None
        self._lock = threading.Lock()
        self._next_id = 1

    # ------------------------------------------------------------------ protocol

    def _post(self, body: dict[str, Any], *, session: str | None) -> httpx.Response:
        headers = dict(HEADERS)
        if session:
            headers["mcp-session-id"] = session
            headers["mcp-protocol-version"] = PROTOCOL
        return self._http.post(self.url, json=body, headers=headers, timeout=self.timeout_s)

    def _open(self) -> str:
        r = self._post(
            {"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT}},
            session=None,
        )
        r.raise_for_status()
        session = r.headers.get("mcp-session-id")
        if not session:
            raise BitgetMcpError("the server opened no session")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session=session)
        return session

    def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._session is None:
                self._session = self._open()
            session = self._session
            self._next_id += 1
            call_id = self._next_id
        body = {"jsonrpc": "2.0", "id": call_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        r = self._post(body, session=session)
        if r.status_code in (400, 404):
            # An expired session is refused with one of these; open a new one and retry once.
            with self._lock:
                self._session = self._open()
                session = self._session
            r = self._post(body, session=session)
        r.raise_for_status()
        msg = _payload(r.text)
        if not msg or "result" not in msg:
            raise BitgetMcpError(f"no result in reply to {name}: {(msg or {}).get('error')}")
        text = "".join(part.get("text", "") for part in msg["result"].get("content", []) if isinstance(part, dict))
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise BitgetMcpError(f"{name} returned text that is not JSON") from exc

    # ------------------------------------------------------------------ data

    def query(self, entry_id: str, **params: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        """Rows from one catalogue entry, or an empty list if there are none or it failed."""
        try:
            doc = self._call("do_query", {"entry_id": entry_id, "params": {k: v for k, v in params.items() if v is not None}})
        except (httpx.HTTPError, BitgetMcpError) as exc:
            log.info("bitget mcp %s %s failed: %s", entry_id, params, exc)
            return []
        if not doc.get("success"):
            log.info("bitget mcp %s %s unsuccessful: %s", entry_id, params, str(doc)[:200])
            return []
        results = (doc.get("data") or {}).get("results")
        return results if isinstance(results, list) else []

    def close(self) -> None:
        self._http.close()
