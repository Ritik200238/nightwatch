"""Build nightwatch/stress/crash_replays.json from each stock's own daily history.

For every named crisis, the days the whole market broke are found from SPY: its worst
overnight gap (open against the previous close) and its worst three-session move (close
against the close three sessions earlier), in each direction. Every stock is then read
on those same dates. Taking each stock's own worst day inside the window instead would
have picked up company news - META's and NFLX's 2022 earnings collapses, Intel's August
2024 report - and labelled them as the crisis. These become the "replay" stress presets:
what this stock did on the days the market broke, applied to today's position.

Source: Yahoo Finance daily chart API, split-adjusted closes and opens. Re-run with
    python research/build_crash_replays.py
when a window is added or a stock joins the universe. The output is committed, so an
analysis never waits on a network call for it.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

WINDOWS = {
    "covid_2020": ("COVID crash", "2020-02-19", "2020-03-23"),
    "banks_2023": ("March 2023 bank failures", "2023-03-08", "2023-03-17"),
    "rates_2022": ("2022 inflation shock", "2022-01-03", "2022-10-14"),
    "carry_2024": ("August 2024 carry-trade unwind", "2024-07-16", "2024-08-07"),
    "tariffs_2025": ("April 2025 tariff shock", "2025-04-02", "2025-04-10"),
}
TICKERS = ("AAPL", "AMD", "AMZN", "AVGO", "BABA", "COIN", "CRCL", "GOOGL", "HOOD", "INTC", "META", "MSFT", "MSTR", "MU",
           "NFLX", "NVDA", "PLTR", "QQQ", "SMCI", "SPY", "SQQQ", "TQQQ", "TSLA", "TSM")
OUT = Path(__file__).resolve().parents[1] / "nightwatch" / "stress" / "crash_replays.json"


def daily(symbol: str) -> list[tuple[str, float, float]]:
    """(date, open, close) per session, split-adjusted, Jan 2020 to May 2025."""
    p1 = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    p2 = int(datetime(2025, 5, 1, tzinfo=UTC).timestamp())
    res = None
    for attempt in range(6):
        host = ("query1", "query2")[attempt % 2]
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d&events=split"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            body = urllib.request.urlopen(req, timeout=30).read()
        except urllib.error.HTTPError as exc:
            body = exc.read()  # Yahoo answers 404 with a JSON body for a range before listing
        except OSError:
            time.sleep(2 + attempt * 2)
            continue
        chart = json.loads(body).get("chart") or {}
        if not chart.get("result"):
            return []  # not listed in the range: no crash moves to report
        res = chart["result"][0]
        break
    if res is None:
        raise RuntimeError(f"Yahoo unreachable for {symbol}")
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    out = []
    for i, t in enumerate(ts):
        o, c = q["open"][i], q["close"][i]
        if o is None or c is None:
            continue
        # Scale the open by the same split factor as the adjusted close, so a gap is not
        # read across a split.
        f = (adj[i] / c) if adj and adj[i] and c else 1.0
        out.append((datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d"), o * f, c * f))
    return out


def market_days(spy: list[tuple[str, float, float]], start: str, end: str) -> dict[str, str] | None:
    """The dates SPY gapped and ran worst, each way, inside a window."""
    idx = [i for i, (d, _, _) in enumerate(spy) if start <= d <= end and i >= 3]
    if len(idx) < 3:
        return None
    gap = {i: spy[i][1] / spy[i - 1][2] - 1 for i in idx}
    d3 = {i: spy[i][2] / spy[i - 3][2] - 1 for i in idx}
    return {"gap_down": spy[min(gap, key=gap.get)][0], "gap_up": spy[max(gap, key=gap.get)][0],
            "d3_down": spy[min(d3, key=d3.get)][0], "d3_up": spy[max(d3, key=d3.get)][0]}


def moves_on(bars: list[tuple[str, float, float]], days: dict[str, str]) -> dict | None:
    pos = {d: i for i, (d, _, _) in enumerate(bars)}
    out = {}
    for key, day in days.items():
        i = pos.get(day)
        if i is None or i < 3:
            return None  # not listed yet on the day the market broke
        v = (bars[i][1] / bars[i - 1][2] - 1) if key.startswith("gap") else (bars[i][2] / bars[i - 3][2] - 1)
        out[f"{key}_pct"], out[f"{key}_date"] = round(v * 100, 2), day
    return out


def main() -> None:
    spy = daily("SPY")
    days = {k: d for k, (_, st, en) in WINDOWS.items() if (d := market_days(spy, st, en))}
    data: dict = {"_meta": {"source": "Yahoo Finance daily chart, split-adjusted; dates from SPY", "built": datetime.now(UTC).strftime("%Y-%m-%d"),
                            "windows": {k: {"name": n, "start": st, "end": en, "market_days": days.get(k)} for k, (n, st, en) in WINDOWS.items()}}}
    for t in TICKERS:
        bars = spy if t == "SPY" else daily(t)
        data[t] = {k: m for k, d in days.items() if (m := moves_on(bars, d))}
        print(t, {k: (v["gap_down_pct"], v["d3_down_pct"], v["gap_up_pct"], v["d3_up_pct"]) for k, v in data[t].items()})
        time.sleep(0.5)
    print("market days:", days)
    OUT.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
