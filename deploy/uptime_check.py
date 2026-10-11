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
from datetime import UTC, datetime

TIMEOUT = 90
MAX_BOOK_AGE_S = 600  # the recorder writes every minute; ten minutes of silence is broken


# The web proxy's mark on an answer it served from its saved copy because the API did not answer.
SNAPSHOT_HEADER = "x-nightwatch-snapshot"


def fetch(url: str, payload: dict | None = None) -> tuple[int, bytes, dict[str, str]]:
    """(status, body, headers). A connection that fails outright is status 0 with the reason as
    the body, so the run reports it in a sentence instead of dying in a traceback."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in (e.headers or {}).items()}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, f"no answer: {getattr(e, 'reason', e)}".encode(), {}


def as_json(what: str, body: bytes, problems: list[str]) -> object | None:
    """The body as JSON, or None with the problem said: an error page in place of an answer."""
    try:
        return json.loads(body)
    except ValueError:
        problems.append(f"{what} did not answer with JSON: {body[:120].decode(errors='replace')!r}")
        return None


def saved_copy(what: str, headers: dict[str, str], problems: list[str]) -> bool:
    """True when the proxy answered from its saved copy: the API itself is not answering."""
    if SNAPSHOT_HEADER in headers:
        problems.append(f"the API is not answering: {what} came from the saved copy dated {headers[SNAPSHOT_HEADER]}")
        return True
    return False


# How old a pull may be before the log says so. Only bitget_bars fails the run.
FEED_MAX_AGE_H = {"bitget_bars": 2.0, "yahoo": 6.0, "nasdaq": 24.0, "fred": 24.0, "rss": 6.0, "sec_edgar": 12.0}


def main(base: str) -> int:
    base = base.rstrip("/")
    problems: list[str] = []

    status, body, _ = fetch(base + "/")
    print(f"desk: HTTP {status}")
    if status != 200:
        problems.append(f"the desk returned HTTP {status}" + (f" ({body[:120].decode(errors='replace')})" if status == 0 else ""))

    status, body, headers = fetch(base + "/api/health")
    h = None
    if status != 200:
        problems.append(f"health returned HTTP {status}: {body[:200].decode(errors='replace')}")
    elif not saved_copy("health", headers, problems):
        h = as_json("health", body, problems)
    if isinstance(h, dict):
        age = None
        if h.get("last_book_ts"):
            age = (datetime.now(UTC) - datetime.fromisoformat(h["last_book_ts"])).total_seconds()
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

    # Every feed, and how old each one is. Only the market data can break the demo, so
    # only that fails the run; the rest are printed so a look at the log shows a feed that
    # has quietly stopped without emailing about a news site having a bad afternoon.
    status, body, headers = fetch(base + "/api/sources")
    rows = None
    if status != 200:
        problems.append(f"sources returned HTTP {status}")
    elif not saved_copy("sources", headers, problems):
        rows = as_json("sources", body, problems)
    if isinstance(rows, list):
        now = datetime.now(UTC)
        for row in rows:
            if not row.get("last_update"):
                print(f"source {row['key']}: never pulled  STALE")
                continue
            hours = (now - datetime.fromisoformat(row["last_update"])).total_seconds() / 3600
            limit = FEED_MAX_AGE_H.get(row["key"], 24.0)
            mark = "  STALE" if hours > limit else ""
            print(f"source {row['key']}: {row['rows']:,} rows, pulled {hours:.1f}h ago (limit {limit:.0f}h){mark}")
            if mark and row["key"] == "bitget_bars":
                problems.append(f"the market-data feed has not been pulled for {hours:.1f} hours")

    ticket = {
        "ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000,
        "horizon_kind": "next_open", "stop_price": 350, "thesis": "uptime check",
        "invalidation": "uptime check", "record": False,
    }
    status, body, headers = fetch(base + "/api/analyze", ticket)
    r = None
    if status != 200:
        problems.append(f"an analysis returned HTTP {status}: {body[:200].decode(errors='replace')}")
    elif not saved_copy("the analysis", headers, problems):  # a saved example has a verdict too
        r = as_json("the analysis", body, problems)
    if isinstance(r, dict):
        verdict = (r.get("verdict") or {}).get("verdict")
        print(f"analysis: {verdict} in {(r.get('timings_ms') or {}).get('total')} ms")
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
