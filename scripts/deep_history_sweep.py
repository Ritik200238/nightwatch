"""Measure the long record and write nightwatch/stress/deep_history.json.

    python scripts/deep_history_sweep.py                 # every ticker the live desk lists
    python scripts/deep_history_sweep.py --tickers NVDA TSLA

Fetches each stock's daily bars from Yahoo Finance (the same provider the desk already
uses, split-adjusted) back to 1990 or the listing date, whichever is later, and stores
the summary described in ``nightwatch/stress/deep_history.py``. Nothing is estimated or
filled in: a ticker the provider has no bars for is left out and listed under ``skipped``.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nightwatch.data.models import Interval  # noqa: E402
from nightwatch.data.sync import YAHOO_TICKER_OVERRIDES  # noqa: E402
from nightwatch.data.yahoo import YahooChartClient  # noqa: E402
from nightwatch.stress import deep_history as dh  # noqa: E402
from nightwatch.time_utils import UTC, utc_now  # noqa: E402

LEVERAGED = {"TQQQ", "SQQQ", "SOXL", "SOXS", "TSLL", "NVDL", "UVXY", "SPXL", "SPXS"}  # left out of the pooled line
UNIVERSE_URL = "https://nightwatch-gules.vercel.app/api/universe"


def live_tickers() -> list[str]:
    with urllib.request.urlopen(UNIVERSE_URL, timeout=30) as r:  # noqa: S310 - fixed https URL
        rows = json.load(r)
    return sorted({x["ticker"] for x in rows})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--out", default=str(dh.RESULT_PATH))
    a = ap.parse_args()
    tickers = [t.upper() for t in a.tickers] if a.tickers else live_tickers()

    y = YahooChartClient()
    per: dict[str, dict] = {}
    raw: dict[str, dict[str, pd.Series]] = {}
    skipped: dict[str, str] = {}
    start, end = datetime(1990, 1, 1, tzinfo=UTC), utc_now()
    for t in tickers:
        ys = YAHOO_TICKER_OVERRIDES.get(t, t)
        try:
            bars = y.get_bars(ys, Interval.D1, start, end)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop the sweep
            skipped[t] = f"{type(exc).__name__}: {exc}"[:160]
            continue
        if not bars:
            skipped[t] = "provider returned no daily bars"
            continue
        df = pd.DataFrame([{"ts": b.ts, "open": b.open, "close": b.close} for b in bars])
        fx = dh.SERIES_FIXES.get(t)
        s = dh.summarize_ticker(df, fx)
        if s is None:
            skipped[t] = f"only {len(df)} sessions"
            continue
        per[t] = s
        raw[t] = dh.window_returns(df, fx)
        print(f"{t:6s} {s['first']}  {s['sessions']:5d} sessions", flush=True)
    y.close()

    result = {
        "ran_at": utc_now().isoformat(),
        "source": "Yahoo Finance daily bars, split-adjusted, requested from 1990-01-01",
        "grid_percentiles": list(dh.GRID),
        "windows": {k: {kk: vv for kk, vv in v.items() if kk != "hours"} | {"hours": v["hours"]} for k, v in dh.WINDOWS.items()},
        "series_fixes": dh.SERIES_FIXES,
        "tickers": per,
        "pooled": dh.pool(per, raw, LEVERAGED),
        "pooled_excludes": sorted(LEVERAGED),
        "skipped": skipped,
    }
    Path(a.out).write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {a.out}: {len(per)} tickers, {len(skipped)} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
