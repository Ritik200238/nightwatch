"""The base rate: how often has this stock moved this much while the market was shut?

"What's the base rate of TSLA falling 5% over a weekend?" is the sub-theme's own
question - retrieve the historical distribution - asked without a trade attached. It used
to be read as a TSLA short with a size missing, so the desk asked for a size and answered
nothing. It is answered here directly, twice: across every past closed window of that
kind (the unconditional rate), and across the past moments most like now (the
conditional one), with a full stress test of a default-sized position beside it so the
trader can go straight on to "and at my size?".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from nightwatch.analog.outcomes import WEEKEND_H, closed_windows, weekend_windows

_ASK = re.compile(
    r"\b(?:base[\s-]?rate|how often|how many times|odds|chances?|probability|likelihood|how likely|historically|history says)\b"
    r"|概率|几率|多常|历史上|多少次",
    re.I,
)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|％|per ?cent)", re.I)
_UP = re.compile(r"\b(?:rise|rises|rising|rally|rallies|up|gain|gains|jump|jumps|pump|pumps|gap up|higher|climb|climbs)\b|涨|上涨|暴涨", re.I)
_WEEKEND = re.compile(r"weekend|周末", re.I)
DEFAULT_NOTIONAL = 10_000.0


@dataclass(frozen=True)
class BaseRateQuestion:
    ticker: str
    move_pct: float  # always positive
    up: bool
    weekend: bool


def detect(text: str, tickers: list[str]) -> BaseRateQuestion | None:
    if not _ASK.search(text):
        return None
    pct = _PCT.search(text)
    if not pct:
        return None
    from nightwatch.api import intake

    parsed = intake.parse_message(text, tickers)
    if not parsed.ticker:
        return None
    return BaseRateQuestion(parsed.ticker.upper(), float(pct.group(1)), bool(_UP.search(text)), bool(_WEEKEND.search(text)))


def _times(n: int) -> str:
    return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def answer(state: Any, q: BaseRateQuestion, *, as_of: datetime | None = None, lang: str = "en") -> dict[str, Any]:  # noqa: ANN401, C901
    from nightwatch.api.intake import brief
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from nightwatch.time_utils import utc_now

    ctx = state.ctx
    frame = ctx.feature_frame(q.ticker, as_of or utc_now())
    w = closed_windows(frame)
    kind = "weekends" if q.weekend else "overnight closes"
    if not w.empty:
        w = weekend_windows(w) if q.weekend else w[w["hours"] < WEEKEND_H]
    zh = lang == "zh"
    word = "rose" if q.up else "fell"
    bits = []
    facts: dict[str, Any] = {"ticker": q.ticker, "move_pct": q.move_pct, "up": q.up, "weekend": q.weekend, "windows": None, "conditional": None}
    if len(w):
        hit = w["ret_pct"] >= q.move_pct if q.up else w["ret_pct"] <= -q.move_pct
        worst = w.loc[w["ret_pct"].idxmax() if q.up else w["ret_pct"].idxmin()]
        facts["windows"] = {"n": int(len(w)), "hits": int(hit.sum()), "share": float(hit.mean()), "since": f"{w['start'].min():%Y-%m}", "biggest_pct": float(worst["ret_pct"])}
        if zh:
            bits.append(
                f"基准概率：自 {w['start'].min():%Y 年 %m 月}以来的 {len(w)} 个{'周末' if q.weekend else '隔夜休市'}中，{q.ticker} 代币{'上涨' if q.up else '下跌'} {q.move_pct:g}% 或以上的有 "
                f"{int(hit.sum())} 次（{hit.mean():.1%}）。最大一次为 {worst['ret_pct']:+.1f}%（{worst['start']:%Y-%m-%d} 开始的那段休市）。"
            )
        else:
            bits.append(
                f"Base rate: across {len(w)} past {kind} since {w['start'].min():%b %Y}, {q.ticker}'s token {word} {q.move_pct:g}% or more "
                f"{_times(int(hit.sum()))} ({hit.mean():.1%}). The biggest was {worst['ret_pct']:+.1f}%, over the window that began {worst['start']:%d %b %Y}."
            )
    else:
        bits.append(f"{q.ticker} 的历史休市样本不足，无法给出基准概率。" if zh else f"There are not enough past {kind} for {q.ticker} to give a base rate.")

    # The conditional rate: the same question asked of the moments most like now.
    ticket = TradeTicket(
        ticker=q.ticker, side=Side.SHORT if q.up else Side.LONG, notional_quote=DEFAULT_NOTIONAL,
        horizon_kind=HorizonKind.HOURS if q.weekend else HorizonKind.NEXT_OPEN,
        horizon_hours=None,
    ) if not q.weekend else None
    if ticket is None:
        from nightwatch.api.intake import horizon_fields

        hk, hh, label = horizon_fields("through_weekend", None)
        ticket = TradeTicket(ticker=q.ticker, side=Side.SHORT if q.up else Side.LONG, notional_quote=DEFAULT_NOTIONAL,
                             horizon_kind=hk, horizon_hours=hh, extra={"horizon_label": label})
    with state.lock:
        report = analyze(ctx, ticket, as_of=as_of, record=False)
        payload = report.to_dict()
    a = report.analog
    if a is not None and a.matches_outcomes:
        vals = [o.outcomes[report.primary_horizon].ret_pct for o in a.matches_outcomes
                if report.primary_horizon in o.outcomes and o.outcomes[report.primary_horizon].ret_pct is not None]
        if vals:
            v = np.asarray(vals, dtype=float)
            n_hit = int((v >= q.move_pct).sum() if q.up else (v <= -q.move_pct).sum())
            facts["conditional"] = {"n": int(len(v)), "hits": n_hit, "share": n_hit / len(v)}
            bits.append(f"在与现在最相似的 {len(v)} 个历史时刻中，有 {n_hit} 个（{n_hit / len(v):.0%}）在同样的持有期内{'上涨' if q.up else '下跌'}了这么多。" if zh
                        else f"Among the {len(v)} past moments most like now, {n_hit} ({n_hit / len(v):.0%}) {word} that much over the same hold.")
    bits.append(f"下面是按 {DEFAULT_NOTIONAL:,.0f} USDT {'空头' if q.up else '多头'}同样持有的完整压力测试；告诉我你的仓位和止损，我来给出具体仓位。" if zh
                else f"Below is the full stress test for a {DEFAULT_NOTIONAL:,.0f} USDT {'short' if q.up else 'long'} held the same way; tell me your size and stop to size it.")
    text = ("" if zh else " ").join(bits)
    return {
        "intent": {"kind": "base_rate", "ticker": q.ticker, "missing_fields": [], "reply": text},
        "ticket": None, "report": payload, "narrative": text, "report_text": None, "unverified_numbers": [],
        "reply": text + "\n\n" + brief(report, lang), "mode": "base_rate", "language": lang, "base_rate": facts,
    }
