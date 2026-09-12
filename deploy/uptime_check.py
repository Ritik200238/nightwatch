"""Is the live demo actually usable right now?

Run against the public site. Exits non-zero with a plain reason when anything a judge
would notice is wrong: the desk not loading, the API not answering, the recorder having
stopped writing, or an analysis no longer returning a verdict.

    python deploy/uptime_check.py https://nightwatch-gules.vercel.app
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

TIMEOUT = 90
MAX_BOOK_AGE_S = 600  # the recorder writes every minute; ten minutes of silence is broken


def fetch(url: str, payload: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main(base: str) -> int:
    base = base.rstrip("/")
    problems: list[str] = []

    status, _ = fetch(base + "/")
    print(f"desk: HTTP {status}")
    if status != 200:
        problems.append(f"the desk returned HTTP {status}")

    status, body = fetch(base + "/api/health")
    if status != 200:
        problems.append(f"health returned HTTP {status}")
    else:
        h = json.loads(body)
        age = None
        if h.get("last_book_ts"):
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(h["last_book_ts"])).total_seconds()
        print(f"health: {h.get('bars'):,} bars, {h.get('tickers_with_data')} tokens, book {age / 60:.1f} min old" if age is not None else f"health: {h}")
        if not h.get("ok"):
            problems.append("health reports not ok")
        if (h.get("bars") or 0) < 500_000:
            problems.append(f"only {h.get('bars')} bars stored")
        if (h.get("tickers_with_data") or 0) < 20:
            problems.append(f"only {h.get('tickers_with_data')} tokens have data")
        if age is None:
            problems.append("no order book has ever been recorded")
        elif age > MAX_BOOK_AGE_S:
            problems.append(f"the recorder has written nothing for {age / 60:.0f} minutes")

    ticket = {
        "ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000,
        "horizon_kind": "next_open", "stop_price": 350, "thesis": "uptime check",
        "invalidation": "uptime check", "record": False,
    }
    status, body = fetch(base + "/api/analyze", ticket)
    if status != 200:
        problems.append(f"an analysis returned HTTP {status}: {body[:200].decode(errors='replace')}")
    else:
        r = json.loads(body)
        verdict = r["verdict"]["verdict"]
        print(f"analysis: {verdict} in {r['timings_ms']['total']} ms")
        if verdict not in ("GO", "REDUCE_TO", "HEDGE", "NO_GO", "REVIEW"):
            problems.append(f"unexpected verdict {verdict}")

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nall good")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "https://nightwatch-gules.vercel.app"))
