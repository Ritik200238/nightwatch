"""Measure how close the token's overnight quote is to the real opening print.

    python scripts/quote_trust_sweep.py --db data/nightwatch.sqlite

Reads the stored hourly stock and token bars (read only) and writes
nightwatch/stress/quote_trust.json. Method: ``nightwatch/stress/quote_trust.py``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nightwatch.stress import quote_trust as qt  # noqa: E402
from nightwatch.time_utils import utc_now  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "nightwatch.sqlite"))
    ap.add_argument("--out", default=str(qt.RESULT_PATH))
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    y = pd.DataFrame(con.execute("SELECT symbol, ts, open, close FROM bars WHERE venue='yahoo' AND interval='1h' AND kind='trade'").fetchall(), columns=["s", "ts", "o", "c"])
    s = pd.DataFrame(con.execute("SELECT symbol, ts, open FROM bars WHERE venue='bitget_spot' AND interval='1h' AND kind='trade' AND open > 0").fetchall(), columns=["s", "ts", "o"])
    s = s[s["s"].str.startswith("R") & s["s"].str.endswith("USDT")].copy()
    s["t"] = s["s"].str[1:-4]
    df = qt.observations(y, s)
    res = qt.summarize(df)
    res |= {"ran_at": utc_now().isoformat(), "since": pd.to_datetime(y["ts"].min(), unit="ms", utc=True).isoformat(),
            "until": pd.to_datetime(y["ts"].max(), unit="ms", utc=True).isoformat(),
            "method": "token quote at each whole hour vs the real 09:30 ET open, against holding the last close; night-resampled 95% interval"}
    Path(a.out).write_text(json.dumps(res, separators=(",", ":")), encoding="utf-8")
    for r in res["pooled"]:
        print(f"{r['from_h']:>3.0f}-{r['to_h']:<3.0f}h  token {r['token_bps']:5.1f} [{r['token_ci'][0]:.0f},{r['token_ci'][1]:.0f}]  last close {r['last_close_bps']:5.1f} [{r['last_close_ci'][0]:.0f},{r['last_close_ci'][1]:.0f}]  closer {r['token_closer']:.0%}  nights={r['nights']}")
    print(res["rows"], res["nights"], res["tickers"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
