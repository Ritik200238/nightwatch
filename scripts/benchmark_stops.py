"""Our one-in-twenty line against plain stop rules, on the same scored history.

Uses only the public API, so anyone can rerun it:

    python scripts/benchmark_stops.py [base_url]

Every matured long-side forecast in the journal (replays and live tickets) carries the loss
line the desk drew at the time (p5) and the return that followed. For each rule below we
count how often the return went past that rule's line:

* the desk's stated line (p5, from similar past moments, before the tail correction the desk
  applies afterwards; the public API exposes this line, and the Method page also shows the
  corrected line in force),
* the same engine's unconditioned line (base_p5, no similar-moment filter),
* flat stops a trader would type: -2%, -3%, -5%,
* a flat stop tuned afterwards so its overall breach rate equals the desk's. This is the best
  case for a flat rule: it is given the answer for free.

The question is not only "how often", it is "how evenly". A one-in-twenty line should be
crossed about one time in twenty on every stock. A flat stop cannot do that: the same -3%
is a rare event on an index fund and a routine one on a volatile name.

The count differs slightly from the Method page: that page scores only forecasts made after enough
earlier ones had matured to fit the tail correction, and this script has no such cut.

Read-only. It changes nothing and feeds no verdict.
"""

from __future__ import annotations

import json
import statistics
import sys
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://nightwatch-gules.vercel.app/api").rstrip("/")
if not BASE.endswith("/api"):
    BASE += "/api"
MIN_PER_TICKER = 30


def get(path: str):
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": "nightwatch-benchmark/1"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - fixed https base
        return json.load(r)


def load_rows() -> list[dict]:
    tickers = sorted({u["ticker"] for u in get("/universe") if u.get("has_data")})
    rows: list[dict] = []
    for t in tickers:
        for r in get(f"/forecasts?ticker={t}&limit=1000"):
            if r.get("ret_pct") is None or r.get("p5") is None or r.get("side") != "long":
                continue
            rows.append({"ticker": t, "night": str(r["as_of"])[:10], "ret": float(r["ret_pct"]), "p5": float(r["p5"]), "base": r.get("base_p5")})
    return rows


def rate(rows: list[dict], line) -> float:
    return sum(1 for r in rows if r["ret"] < line(r)) / len(rows)


def by_ticker(rows: list[dict], line) -> list[tuple[float, str]]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["ticker"], []).append(r)
    return sorted((rate(g, line), t) for t, g in groups.items() if len(g) >= MIN_PER_TICKER)


def main() -> None:
    rows = load_rows()
    if not rows:
        sys.exit("no scored forecasts came back")
    nights = len({r["night"] for r in rows})
    desk = rate(rows, lambda r: r["p5"])
    with_base = [r for r in rows if r["base"] is not None]
    out = {"n": len(rows), "nights": nights, "tickers": len({r["ticker"] for r in rows}), "arms": []}

    def add(name: str, sample: list[dict], line) -> None:
        bt = by_ticker(sample, line)
        out["arms"].append(
            {
                "rule": name,
                "n": len(sample),
                "overall_breach": round(rate(sample, line), 4),
                "ticker_min": round(bt[0][0], 4),
                "ticker_median": round(statistics.median(x[0] for x in bt), 4),
                "ticker_max": round(bt[-1][0], 4),
                "most_breached": bt[-1][1],
                "least_breached": bt[0][1],
            }
        )

    add("Stated line (p5, similar past moments)", rows, lambda r: r["p5"])
    if len(with_base) >= 0.5 * len(rows):
        add("Same engine, no similar-moment filter (base p5)", with_base, lambda r: float(r["base"]))
    for x in (2.0, 3.0, 5.0):
        add(f"Flat -{x:g}% stop", rows, lambda r, x=x: -x)
    # Best case for a flat rule: the one level that gives the desk's overall rate, chosen after the fact.
    level = min((abs(rate(rows, lambda r, m=m / 100: m) - desk), m / 100) for m in range(-3000, 1))[1]
    add(f"Flat {level:.1f}% stop, tuned afterwards to the desk's overall rate", rows, lambda r, m=level: m)

    print(f"{out['n']} scored long-side forecasts, {out['nights']} nights, {out['tickers']} stocks (public API, {BASE})")
    print(f"Target: one in twenty = 5.0%. Stated line overall: {desk * 100:.1f}%\n")
    head = f"{'Rule':<62}{'overall':>9}{'low':>8}{'median':>8}{'high':>8}"
    print(head)
    print("-" * len(head))
    for a in out["arms"]:
        print(f"{a['rule']:<62}{a['overall_breach'] * 100:>8.1f}%{a['ticker_min'] * 100:>7.1f}%{a['ticker_median'] * 100:>7.1f}%{a['ticker_max'] * 100:>7.1f}%")
    print(f"\nlow / median / high = breach rate by stock, stocks with at least {MIN_PER_TICKER} scored forecasts.")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
