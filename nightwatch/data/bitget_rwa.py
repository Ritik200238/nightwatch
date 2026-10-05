"""Bitget Wallet's tokenized-stock (RWA) market data, from the ``bitget-wallet-skill``.

Read-only, no account and no key. The skill's own docs (docs/rwa.md in
github.com/bitget-wallet-ai-lab/bitget-wallet-skill) call ``/market/v2/rwa/StockInfo`` on
``copenapi.bgwapi.io`` with the shared public agent identity (``toc_agent``) and a request
hash ``X-SIGN = "0x" + sha256(METHOD + PATH_WITH_QUERY + BODY + TIMESTAMP)``. The hash is
not a secret; it is an integrity stamp over the request. Probed live on 5 Oct 2026: TSLAon
and NVDAon answered 200 / status 0 in 0.35 s, three times in three.

What the desk reads is only what a pre-trade check needs: whether the token is online and
in which session, any pause or alert text, and the per-order size limits.

This is not a documented stable contract, so the client is built to be distrusted: it never
raises, a reply that is not the expected shape is "no reading", and callers cache it and
refresh it in the background.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE = "https://copenapi.bgwapi.io"
PATH = "/market/v2/rwa/StockInfo"
HEADERS = {"Content-Type": "application/json", "channel": "toc_agent", "brand": "toc_agent", "clientversion": "10.0.0", "language": "en", "token": "toc_agent"}


def token_symbol(ticker: str) -> str:
    """The wallet's symbol for a stock: Ondo's ``<TICKER>on``."""
    return f"{ticker.upper()}on"


def signed_headers(path_with_query: str, *, ts_ms: int | None = None) -> dict[str, str]:
    ts = str(ts_ms if ts_ms is not None else int(time.time() * 1000))
    sign = "0x" + hashlib.sha256(("GET" + path_with_query + "" + ts).encode()).hexdigest()
    return {**HEADERS, "X-TIMESTAMP": ts, "X-SIGN": sign}


class BitgetRwaClient:
    def __init__(self, *, base: str = BASE, timeout_s: float = 6.0, client: httpx.Client | None = None):
        self.base = base
        self._http = client or httpx.Client(timeout=timeout_s)
        self.timeout_s = timeout_s

    def stock_info(self, ticker: str) -> dict[str, Any] | None:
        """The ``data`` object for a ticker, or None for any failure or an unexpected shape."""
        path = f"{PATH}?ticker={token_symbol(ticker)}"
        try:
            r = self._http.get(self.base + path, headers=signed_headers(path), timeout=self.timeout_s)
            r.raise_for_status()
            doc = r.json()
            data = doc.get("data") if isinstance(doc, dict) else None
            if not isinstance(doc, dict) or doc.get("status") != 0 or not isinstance(data, dict) or data.get("ticker") != token_symbol(ticker):
                return None
            return data
        except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
            log.info("bitget rwa %s failed: %s", ticker, exc)
            return None

    def health(self) -> dict[str, Any]:
        """One cheap call on a name that always exists: how many answered."""
        ok = self.stock_info("TSLA") is not None
        return {"answering": int(ok), "tried": 1}

    def close(self) -> None:
        self._http.close()
