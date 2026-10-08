"""Measure open-session versus shut-session beta and write nightwatch/stress/session_beta.json.

    python scripts/session_beta_sweep.py --db data/nightwatch.sqlite

Reads the hourly spot bars the desk already stores (read only). Method and controls are
described in ``nightwatch/stress/session_beta.py``.
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

from nightwatch.stress import session_beta as sb  # noqa: E402
from nightwatch.time_utils import classify_session, utc_now  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "nightwatch.sqlite"))
    ap.add_argument("--out", default=str(sb.RESULT_PATH))
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    rows = con.execute("SELECT symbol, ts, close FROM bars WHERE venue='bitget_spot' AND interval='1h' AND kind='trade' AND close > 0").fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "ts", "close"])
    # Spot tokens are the "r" tokens: RTSLAUSDT is TSLA.
    df = df[df["symbol"].str.startswith("R") & df["symbol"].str.endswith("USDT")]
    df["ticker"] = df["symbol"].str[1:-4]
    df["when"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    closes = {t: g.drop_duplicates("when").set_index("when")["close"].sort_index() for t, g in df.groupby("ticker")}
    union = pd.DatetimeIndex(sorted(set().union(*[set(s.index) for s in closes.values()])))
    flag = pd.Series([classify_session(t.to_pydatetime()).is_closed for t in union], index=union)
    res = sb.summarize(closes, flag)
    out = {
        "ran_at": utc_now().isoformat(), "proxy": sb.PROXY, "since": union.min().isoformat(), "until": union.max().isoformat(),
        "method": "slope of hourly log return on the QQQ token's, by regime; day-resampled 95% interval; one-hour steps only",
        "tickers": res,
    }
    Path(a.out).write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    for t, r in sorted(res.items()):
        print(f"{t:6s} open {r['open']['beta']:+.2f}  shut {r['closed']['beta']:+.2f}  diff {r['diff']['est']:+.2f} [{r['diff']['ci'][0]:+.2f},{r['diff']['ci'][1]:+.2f}]  n={r['open']['n']}/{r['closed']['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
