"""Run the closed-hours study against a Nightwatch database and write the result JSON.

    python research/closed_hours.py --db data/nightwatch.sqlite --out nightwatch/journal/closed_hours.json

Read-only: the database is opened with mode=ro and nothing is written to it. The questions
and the choices made before looking are in the docstring of nightwatch/journal/closed_hours.py.

The script is light on memory on purpose (it ran on a 1 GB box beside the live recorder):
one token's bars at a time, and the order-book archive is read from the covering index
as three columns, one symbol at a time.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


def load_module(path: str | None):
    """Import the study from a file when given (the box has an older checkout), else normally."""
    if path:
        spec = importlib.util.spec_from_file_location("closed_hours", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["closed_hours"] = mod
        spec.loader.exec_module(mod)
        return mod
    from nightwatch.journal import closed_hours

    return closed_hours


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--module", help="path to closed_hours.py, if not importable")
    ap.add_argument("--no-books", action="store_true")
    args = ap.parse_args()
    ch = load_module(args.module)
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=1")

    symbols = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM bars WHERE venue='bitget_spot' AND interval='1h' AND kind='trade'")]
    spot, daily, earnings, books = {}, {}, {}, {}
    for sym in sorted(symbols):
        m = re.fullmatch(r"R([A-Z]+)USDT", sym)
        if not m:
            continue
        t = m.group(1)
        df = pd.read_sql_query("SELECT ts, close FROM bars WHERE venue='bitget_spot' AND symbol=? AND interval='1h' AND kind='trade' ORDER BY ts", con, params=(sym,))
        if len(df) < 500:
            continue
        spot[t] = pd.Series(df["close"].to_numpy(dtype=float), index=pd.to_datetime(df["ts"], unit="ms", utc=True))
        dd = pd.read_sql_query("SELECT ts, open, close FROM bars WHERE venue='yahoo' AND symbol=? AND interval='1d' AND kind='trade' ORDER BY ts", con, params=(t,))
        daily[t] = pd.DataFrame({"open": dd["open"].to_numpy(dtype=float), "close": dd["close"].to_numpy(dtype=float)}, index=pd.to_datetime(dd["ts"], unit="ms", utc=True))
        ed = [r[0] for r in con.execute("SELECT report_date FROM earnings WHERE ticker=?", (t,))]
        earnings[t] = {pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert(et).date() for ms in ed}
        if not args.no_books:
            b = pd.read_sql_query(
                "SELECT ts, spread_bps, depth_bid_25bps AS depth FROM orderbook_snapshots WHERE venue='bitget_spot' AND symbol=? ORDER BY ts", con, params=(sym,))
            if len(b):
                books[t] = b
        print(f"{t}: {len(df)} hourly bars, {len(dd)} daily, {len(earnings[t])} earnings, {len(books.get(t, []))} snapshots", flush=True)

    result = ch.run(ch.Inputs(spot_close=spot, daily=daily, earnings=earnings, books=books))
    result["source"] = {"db": Path(args.db).name, "bar_venue": "bitget_spot", "reference": "yahoo daily"}

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating, float)):
            return None if not np.isfinite(o) else round(float(o), 6)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, date):
            return str(o)
        return o

    Path(args.out).write_text(json.dumps(clean(result), indent=1, sort_keys=False), encoding="utf-8")
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
