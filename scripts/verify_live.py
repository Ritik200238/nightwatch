"""Check the public claims against the live desk in about a minute. Standard library only.

    python scripts/verify_live.py [https://nightwatch-gules.vercel.app]

Every line is a claim the README makes, recomputed from the production API at the time you
run it. Exit code 0 only if all of them hold; a failed line prints what the desk said.
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://nightwatch-gules.vercel.app").rstrip("/")


def get(path: str):
    with urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/{path}", headers={"accept": "application/json"}), timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def verdict_chain():
    v = get("verify")
    ok = v["ok"] and v["first_break"] is None and not v["anchors_broken"]
    return ok, f"{v['checked']:,} verdicts hash-chained, no break; {v['anchored_in_bitcoin']} of {v['anchors']} daily heads anchored in Bitcoin"


def reader_check():
    c = get("chat-check")
    return c["available"] and c["fields_ok"] / c["fields"] > 0.95, f"{c['cases_ok']}/{c['cases']} blind chat cases, {c['fields_ok']}/{c['fields']} fields; {len(c['misses'])} misses listed"


def quote_closer_near_open():
    q = get("quote-trust/NVDA")
    rows = q["pooled"]
    near, far = rows[0], next(r for r in rows if r["from_h"] == 12.0)
    ok = near["token_ci"][1] < near["last_close_ci"][0]
    return ok, (f"last hour before the open: token quote {near['token_bps']:.0f} bps from the real open vs {near['last_close_bps']:.0f} for last close; "
                f"12-24h before: {far['token_bps']:.0f} vs {far['last_close_bps']:.0f}")


def deep_record():
    d = get("deep-history/NVDA")
    w = d["windows"]["weekend_gap"]
    return d["available"] and w["n"] > 500, f"{w['n']:,} NVDA weekends since {d['first'][:4]} in the long record"


CHECKS = [("verdict log is unbroken", verdict_chain), ("chat reader blind check", reader_check),
          ("token quote vs last close, by hours before the open", quote_closer_near_open), ("long weekend record present", deep_record)]

if __name__ == "__main__":
    bad = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001 - a failed fetch is a failed check, not a crash
            ok, detail = False, f"could not check: {exc}"
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    print("ALL CLAIMS HOLD" if not bad else f"{bad} CHECK(S) FAILED")
    sys.exit(1 if bad else 0)
