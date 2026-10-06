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


def _since_zh(ts: Any) -> str:  # noqa: ANN401
    """Year and month in Chinese. Not strftime: a non-ASCII format string fails under a C/Windows locale."""
    return f"{ts.year} 年 {ts.month:02d} 月"


def _times(n: int) -> str:
    return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def _trade_bits(ticket: Any, lang: str) -> str:  # noqa: ANN401
    """The parts of a trade a trader would name: size, side, stop, leverage, account."""
    side = ticket.side.value
    size = f"{ticket.notional_quote:,.0f}"
    zh = lang == "zh"
    bits = [f"{size} USDT {'空头' if side == 'short' else '多头'}" if zh else f"{size} USDT {side}"]
    if ticket.stop_price:
        bits.append(f"止损 {ticket.stop_price:,.2f}" if zh else f"stop at {ticket.stop_price:,.2f}")
    if ticket.leverage and ticket.leverage > 1:
        bits.append(f"{ticket.leverage:g} 倍杠杆" if zh else f"{ticket.leverage:g}x leverage")
    if ticket.account_equity_quote:
        bits.append(f"账户 {ticket.account_equity_quote:,.0f} USDT" if zh else f"account {ticket.account_equity_quote:,.0f} USDT")
    return ("，" if zh else ", ").join(bits)


def answer(state: Any, q: BaseRateQuestion, *, as_of: datetime | None = None, lang: str = "en", context: dict[str, Any] | None = None) -> dict[str, Any]:  # noqa: ANN401, C901
    """``context`` is the report on screen, if any. When it is a trade in this same token, the
    stress test beside the rates is that trade - its size, side, account, stop, leverage and
    hold - not a default one, and the reply says which hold it was."""
    from nightwatch.api import whatif
    from nightwatch.api.intake import _horizon_phrase, brief
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from nightwatch.time_utils import utc_now

    ctx = state.ctx
    own = whatif.ticket_from(context) if context else None
    if own is not None and own.ticker != q.ticker:
        own = None  # the trade on screen is about another token
    if own is not None:
        as_of = whatif.as_of_of(context) or as_of
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
                f"基准概率：自 {_since_zh(w['start'].min())}以来的 {len(w)} 个{'周末' if q.weekend else '隔夜休市'}中，{q.ticker} 代币{'上涨' if q.up else '下跌'} {q.move_pct:g}% 或以上的有 "
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
    if own is not None:
        ticket = own
    elif not q.weekend:
        ticket = TradeTicket(ticker=q.ticker, side=Side.SHORT if q.up else Side.LONG, notional_quote=DEFAULT_NOTIONAL,
                             horizon_kind=HorizonKind.NEXT_OPEN, horizon_hours=None)
    else:
        from nightwatch.api.intake import horizon_fields

        hk, hh, label = horizon_fields("through_weekend", None, as_of)
        ticket = TradeTicket(ticker=q.ticker, side=Side.SHORT if q.up else Side.LONG, notional_quote=DEFAULT_NOTIONAL,
                             horizon_kind=hk, horizon_hours=hh, extra={"horizon_label": label})
    with state.lock:
        report = analyze(ctx, ticket, as_of=as_of, record=False)
        payload = report.to_dict()
    hold = _horizon_phrase(report, lang)
    facts["trade"] = {"own": own is not None, "notional_quote": ticket.notional_quote, "side": ticket.side.value, "hold": hold, "hold_hours": report.horizon_h}
    a = report.analog
    if a is not None and a.matches_outcomes:
        vals = [o.outcomes[report.primary_horizon].ret_pct for o in a.matches_outcomes
                if report.primary_horizon in o.outcomes and o.outcomes[report.primary_horizon].ret_pct is not None]
        if vals:
            v = np.asarray(vals, dtype=float)
            n_hit = int((v >= q.move_pct).sum() if q.up else (v <= -q.move_pct).sum())
            facts["conditional"] = {"n": int(len(v)), "hits": n_hit, "share": n_hit / len(v)}
            bits.append(f"在与现在最相似的 {len(v)} 个历史时刻中，有 {n_hit} 个（{n_hit / len(v):.0%}）在这笔交易的持有期内（{hold}）{'上涨' if q.up else '下跌'}了这么多。" if zh
                        else f"Among the {len(v)} past moments most like now, {n_hit} ({n_hit / len(v):.0%}) {word} that much over the hold used here ({hold}).")
    if own is not None:
        tail = (f"下面是你屏幕上这笔交易的完整压力测试：{_trade_bits(ticket, lang)}，{hold}。" if zh
                else f"Below is the full stress test of the trade on your screen: {_trade_bits(ticket, lang)}, held {hold}.")
    else:
        tail = (f"下面是按 {DEFAULT_NOTIONAL:,.0f} USDT {'空头' if ticket.side.value == 'short' else '多头'}、{hold} 的默认交易做的完整压力测试；告诉我你的仓位、止损和账户，我来给出具体仓位。" if zh
                else f"Below is the full stress test of a default {DEFAULT_NOTIONAL:,.0f} USDT {ticket.side.value} held {hold}, not your own trade; tell me your size, stop and account to size it.")
    bits.append(tail)
    text = ("" if zh else " ").join(bits)
    return {
        "intent": {"kind": "base_rate", "ticker": q.ticker, "missing_fields": [], "reply": text},
        "ticket": None, "report": payload, "narrative": text, "report_text": None, "unverified_numbers": [],
        "reply": text + "\n\n" + brief(report, lang), "mode": "base_rate", "language": lang, "base_rate": facts,
    }
