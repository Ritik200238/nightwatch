"""A blind check of the chat reader: messy sentences, answers fixed before the reader ran.

Each case is (text, expected) where expected holds only what a trader plainly said:
ticker, side, notional (USDT), leverage, and whether the hold is a weekend. A field that is
absent from `expected` is not scored for that case. The cases were written as a trader
would type them (typos, slang, mixed English and Chinese, k/m/万, "x"/倍 leverage), and
include sentences other desks misread. The reader is NOT tuned to this file: a miss is
printed, counted, and published, and only then fixed, with the fix tested elsewhere.

    python research/intake_blind_eval.py            # prints a report, writes the JSON
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from nightwatch.api.intake import parse_message

TICKERS = "AAPL AMD AMZN AVGO BABA COIN CRCL GOOGL HOOD INTC META MSFT MSTR MU NFLX NVDA PLTR QQQ SMCI SPY SQQQ TQQQ TSLA TSM".split()

L, S = "long", "short"
CASES: list[tuple[str, dict]] = [
    # Plain English, k / m suffixes
    ("long 15k tsla over the weekend", dict(ticker="TSLA", side=L, notional=15_000, weekend=True)),
    ("Long 15k TSLA, stress test it", dict(ticker="TSLA", side=L, notional=15_000)),
    ("short 2.5m spy tonight", dict(ticker="SPY", side=S, notional=2_500_000)),
    ("buy 40k worth of nvda", dict(ticker="NVDA", side=L, notional=40_000)),
    ("sell $12,000 of AMD", dict(ticker="AMD", side=S, notional=12_000)),
    ("going long coin 8k", dict(ticker="COIN", side=L, notional=8_000)),
    ("im thinking of shorting 30k of meta", dict(ticker="META", side=S, notional=30_000)),
    ("can i buy 500 usdt of tsm", dict(ticker="TSM", side=L, notional=500)),
    ("put 100k into qqq long", dict(ticker="QQQ", side=L, notional=100_000)),
    ("short mstr 75k hold till monday", dict(ticker="MSTR", side=S, notional=75_000, weekend=True)),
    ("yo should i long aapl 20k over the weekend", dict(ticker="AAPL", side=L, notional=20_000, weekend=True)),
    ("bearish on netflix, short 18k", dict(ticker="NFLX", side=S, notional=18_000)),
    ("long 3k hood", dict(ticker="HOOD", side=L, notional=3_000)),
    ("short $250k tqqq", dict(ticker="TQQQ", side=S, notional=250_000)),
    ("long sqqq 5k", dict(ticker="SQQQ", side=L, notional=5_000)),
    ("buy 60,000 USDT PLTR", dict(ticker="PLTR", side=L, notional=60_000)),
    ("0.5m long amzn", dict(ticker="AMZN", side=L, notional=500_000)),
    ("long google 22k", dict(ticker="GOOGL", side=L, notional=22_000)),
    ("short intel 9k overnight", dict(ticker="INTC", side=S, notional=9_000)),
    ("long micron 14k", dict(ticker="MU", side=L, notional=14_000)),
    # Leverage
    ("long 10k nvda 5x", dict(ticker="NVDA", side=L, notional=10_000, leverage=5)),
    ("short 20k tsla at 10x leverage", dict(ticker="TSLA", side=S, notional=20_000, leverage=10)),
    ("long coin 5k 3x over the weekend", dict(ticker="COIN", side=L, notional=5_000, leverage=3, weekend=True)),
    ("20x long mstr 2k", dict(ticker="MSTR", side=L, notional=2_000, leverage=20)),
    ("long 8k aapl, 2x", dict(ticker="AAPL", side=L, notional=8_000, leverage=2)),
    ("short spy 50k leverage 4", dict(ticker="SPY", side=S, notional=50_000, leverage=4)),
    ("long 12k amd with 7x", dict(ticker="AMD", side=L, notional=12_000, leverage=7)),
    ("short 1k pltr 25x", dict(ticker="PLTR", side=S, notional=1_000, leverage=25)),
    # Slang, typos, shouting
    ("LONG NVDA 25K", dict(ticker="NVDA", side=L, notional=25_000)),
    ("longg tsla 10k", dict(ticker="TSLA", side=L, notional=10_000)),
    ("shrot 5k meta", dict(ticker="META", side=S, notional=5_000)),
    ("ape 2k into smci", dict(ticker="SMCI", side=L, notional=2_000)),
    ("dump 40k of my coin short", dict(ticker="COIN", side=S, notional=40_000)),
    ("nvda long, 15k, weekend", dict(ticker="NVDA", side=L, notional=15_000, weekend=True)),
    ("tsla 15k long fri to mon", dict(ticker="TSLA", side=L, notional=15_000, weekend=True)),
    ("$TSLA short 10k", dict(ticker="TSLA", side=S, notional=10_000)),
    ("long $nvda $30k", dict(ticker="NVDA", side=L, notional=30_000)),
    ("short 7.5k of tesla", dict(ticker="TSLA", side=S, notional=7_500)),
    ("long apple 11k", dict(ticker="AAPL", side=L, notional=11_000)),
    ("long microsoft 16k", dict(ticker="MSFT", side=L, notional=16_000)),
    ("short broadcom 6k", dict(ticker="AVGO", side=S, notional=6_000)),
    ("long alibaba 4k", dict(ticker="BABA", side=L, notional=4_000)),
    ("long circle 9k", dict(ticker="CRCL", side=L, notional=9_000)),
    ("long robinhood 13k", dict(ticker="HOOD", side=L, notional=13_000)),
    ("long palantir 21k", dict(ticker="PLTR", side=L, notional=21_000)),
    ("short facebook 8k", dict(ticker="META", side=S, notional=8_000)),
    ("long amazon 17k", dict(ticker="AMZN", side=L, notional=17_000)),
    ("long taiwan semi 19k", dict(ticker="TSM", side=L, notional=19_000)),
    # Chinese
    ("周末做多特斯拉 2万U", dict(ticker="TSLA", side=L, notional=20_000, weekend=True)),
    ("做空英伟达 5万", dict(ticker="NVDA", side=S, notional=50_000)),
    ("做多苹果 1万U", dict(ticker="AAPL", side=L, notional=10_000)),
    ("想空特斯拉 3000U", dict(ticker="TSLA", side=S, notional=3_000)),
    ("开多 nvda 2万 5倍", dict(ticker="NVDA", side=L, notional=20_000, leverage=5)),
    ("空 mstr 1.5万 10倍杠杆", dict(ticker="MSTR", side=S, notional=15_000, leverage=10)),
    ("做多coin 8千U 周末", dict(ticker="COIN", side=L, notional=8_000, weekend=True)),
    ("买入 500U 的 spy", dict(ticker="SPY", side=L, notional=500)),
    ("做空 qqq 10万U 过周末", dict(ticker="QQQ", side=S, notional=100_000, weekend=True)),
    ("看多英伟达 两万u 3倍", dict(ticker="NVDA", side=L, notional=20_000, leverage=3)),
    ("我想做多 amd 1万", dict(ticker="AMD", side=L, notional=10_000)),
    ("做空 meta 2.5万U", dict(ticker="META", side=S, notional=25_000)),
    ("今晚做多微软 5000U", dict(ticker="MSFT", side=L, notional=5_000)),
    ("周末空 pltr 1万U 2倍", dict(ticker="PLTR", side=S, notional=10_000, leverage=2, weekend=True)),
    ("多 tsla 30000u", dict(ticker="TSLA", side=L, notional=30_000)),
    # Stops, targets and other noise that must not become the size
    ("long 10k nvda stop 120", dict(ticker="NVDA", side=L, notional=10_000)),
    ("long tsla 15k, stop at 200, target 300", dict(ticker="TSLA", side=L, notional=15_000)),
    ("short 20k aapl, stop 5% above", dict(ticker="AAPL", side=S, notional=20_000)),
    ("long 5k coin with a 10% stop", dict(ticker="COIN", side=L, notional=5_000)),
    ("long 25k mstr, my account is 100k", dict(ticker="MSTR", side=L, notional=25_000)),
    ("long 12k nvda, risking 2% of 80k", dict(ticker="NVDA", side=L, notional=12_000)),
    ("buy 3k tsla at 250", dict(ticker="TSLA", side=L, notional=3_000)),
    ("short 9k amd at 160 tomorrow", dict(ticker="AMD", side=S, notional=9_000)),
    ("long nvda 30k after earnings on 28 aug", dict(ticker="NVDA", side=L, notional=30_000)),
    ("long 4k tsla for 2 days", dict(ticker="TSLA", side=L, notional=4_000)),
    ("short 6k meta until the close", dict(ticker="META", side=S, notional=6_000)),
    # No trade yet: the reader must not invent one
    ("what is the weather", dict(ticker=None)),
    ("hello", dict(ticker=None)),
    ("how does this work?", dict(ticker=None)),
    ("is nvda a good stock", dict(side=None, notional=None)),
    ("tell me about tsla", dict(side=None, notional=None)),
    ("what do you think about aapl?", dict(side=None, notional=None)),
    ("long tsla", dict(ticker="TSLA", side=L, notional=None)),
    ("short nvda", dict(ticker="NVDA", side=S, notional=None)),
    ("15k", dict(ticker=None, side=None)),
    ("buy", dict(ticker=None, notional=None)),
    # Names that look like other things
    ("long 5k meta over the weekend", dict(ticker="META", side=L, notional=5_000, weekend=True)),
    ("short 10k mu", dict(ticker="MU", side=S, notional=10_000)),
    ("long 10k spy", dict(ticker="SPY", side=L, notional=10_000)),
    ("long 7k it", dict(ticker=None, notional=7_000)),
    ("buy the dip on amd 12k", dict(ticker="AMD", side=L, notional=12_000)),
    ("sell my nvda position 20k", dict(ticker="NVDA", side=S, notional=20_000)),
    # Size shapes
    ("long nvda for 1,200,000", dict(ticker="NVDA", side=L, notional=1_200_000)),
    ("long tsla 15 000 usdt", dict(ticker="TSLA", side=L, notional=15_000)),
    ("long tsla 15000", dict(ticker="TSLA", side=L, notional=15_000)),
    ("long tsla 1.5k", dict(ticker="TSLA", side=L, notional=1_500)),
    ("long tsla 2 million", dict(ticker="TSLA", side=L, notional=2_000_000)),
    ("long tsla two thousand", dict(ticker="TSLA", side=L, notional=2_000)),
    ("long tsla 25 grand", dict(ticker="TSLA", side=L, notional=25_000)),
    ("short nvda 1k usdt", dict(ticker="NVDA", side=S, notional=1_000)),
    ("long nvda $750", dict(ticker="NVDA", side=L, notional=750)),
    ("long nvda 10 K", dict(ticker="NVDA", side=L, notional=10_000)),
    ("short tsla, size 45k", dict(ticker="TSLA", side=S, notional=45_000)),
    ("long nvda position of 33k usdt", dict(ticker="NVDA", side=L, notional=33_000)),
]


def _weekend(p) -> bool:
    return p.horizon_kind in ("weekend", "through_weekend") or (p.horizon_kind or "").startswith("weekend")


def score() -> dict:
    rows, tot, hit = [], 0, 0
    for text, exp in CASES:
        p = parse_message(text, TICKERS, None)
        got = dict(ticker=p.ticker, side=p.side, notional=p.notional_quote, leverage=p.leverage, weekend=_weekend(p))
        bad = {}
        for k, v in exp.items():
            tot += 1
            if (k == "notional" and v is not None and got[k] is not None and abs(got[k] - v) < 0.5) or got[k] == v:
                hit += 1
            else:
                bad[k] = (v, got[k])
        rows.append(dict(text=text, ok=not bad, wrong=bad))
    cases_ok = sum(r["ok"] for r in rows)
    return dict(cases=len(rows), cases_ok=cases_ok, fields=tot, fields_ok=hit, rows=rows)


def main() -> int:
    r = score()
    for row in r["rows"]:
        if not row["ok"]:
            print("MISS", repr(row["text"]), row["wrong"])
    print(f"\n{r['cases_ok']}/{r['cases']} sentences fully right; {r['fields_ok']}/{r['fields']} fields right")
    out = Path(__file__).resolve().parent.parent / "nightwatch" / "journal" / "chat_check.json"
    body = {k: r[k] for k in ("cases", "cases_ok", "fields", "fields_ok")}
    body |= {"ran_at": datetime.now(UTC).isoformat(), "misses": [x for x in r["rows"] if not x["ok"]]}
    out.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
