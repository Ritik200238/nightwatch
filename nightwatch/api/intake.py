"""Understanding a trade idea, and briefing the answer, without a model.

The language layer is a convenience, not a dependency: the desk has to work when there
is no API key, when the key runs out, and when the provider is having a bad afternoon.
So the same two jobs the model does - turn a sentence into a ticket, turn a report into
a paragraph - are also done here by rules.

The rules are deliberately narrow. They read what a trader actually types on a desk
("long 25k TSLA overnight, stop 340") and they never invent a field: no thesis the
trader did not write, no stop that was not given, no size that was not stated. When a
required field is missing they say which one. The model, when present, does the same
job with more range; this is the floor, not the ceiling.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.stress.scenarios import Side

log = logging.getLogger(__name__)

# A company's ordinary name is how people talk about these tokens.
ALIASES: dict[str, str] = {
    "tesla": "TSLA", "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL", "meta": "META", "facebook": "META", "netflix": "NFLX",
    "palantir": "PLTR", "coinbase": "COIN", "robinhood": "HOOD", "micron": "MU", "intel": "INTC",
    "broadcom": "AVGO", "alibaba": "BABA", "super micro": "SMCI", "supermicro": "SMCI",
    "microstrategy": "MSTR", "taiwan semi": "TSM", "tsmc": "TSM", "circle": "CRCL",
    "nasdaq": "QQQ", "s&p": "SPY", "sp500": "SPY", "spx": "SPY",
}

_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9}

# "short term" is a horizon, not a direction. Same for "shorter" and "short-dated".
_SHORT = re.compile(r"\bshort(?!\s*[-\s]?(?:term|dated|dur|er\b))\b|\bsell\b|\bbearish\b|\bfade\b", re.I)
# "hold 20k of TSLA overnight" is a long position; a trader saying it would be surprised
# to be asked which way round they meant it.
_LONG = re.compile(r"\blong(?!\s*[-\s]?(?:term|dated|er\b))\b|\bbuy\b|\bbullish\b|\bhold(?:ing)?\b|\bcarry\b|\bkeep\b", re.I)
_STOP = re.compile(r"\bstop(?:[-\s]?loss)?\b\s*(?:is|at|of|:|=)?\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I)
_TARGET = re.compile(r"\b(?:target|take[-\s]?profit|tp)\b\s*(?:is|at|of|:|=)?\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I)
_EQUITY = re.compile(r"\b(?:equity|account|portfolio|book|capital|aum)\b[^.\d]{0,20}\$?\s*([\d,]+(?:\.\d+)?)\s*([kmb])?", re.I)
_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([kmb])?|\b([\d,]+(?:\.\d+)?)\s*([kmb])\b|\b([\d,]+(?:\.\d+)?)\s*(?:usdt|usd|dollars?)\b", re.I)
# "long 20000 TSLA" states a size as plainly as "long 20k TSLA" does. A bare number is
# read as one only when nothing else has claimed it and it is not a price: "long TSLA at
# 350" is a level, and nobody sizes a position at fifty dollars.
_BARE_MONEY = re.compile(r"(?<![$\d.])\b(\d[\d,]{2,})\b(?!\s*(?:%|bps))", re.I)
_PRICE_WORD = re.compile(r"\b(?:at|@|price|near|around|above|below|under|over)\s*$", re.I)
BARE_MONEY_FLOOR = 100.0
_HOURS = re.compile(r"\b([\d.]+)\s*(?:hours?|hrs?|h)\b", re.I)
_DAYS = re.compile(r"\b([\d.]+)\s*(?:days?|d)\b", re.I)
_NEXT_OPEN = re.compile(r"\bovernight\b|\b(?:until|till|to|through)\s+(?:the\s+)?(?:us\s+)?open\b|\bnext\s+open\b", re.I)
# "Through the weekend" said on a Thursday is until Monday's open, not Thursday's.
_WEEKEND = re.compile(r"\b(?:through|over|across|for|into)\s+the\s+weekend\b|\b(?:into|until|till|to)\s+monday\b|\bmonday(?:'s)?\s+open\b|\bweekend\s+hold\b", re.I)
_WINDOW_END = re.compile(r"\b(?:until|till|to|by|into)\s+(?:the\s+)?close\b|\bsession\s+end\b", re.I)
_HEDGE_PCT = re.compile(r"\bhedge\b[^.\d]{0,15}(\d{1,3})\s*%", re.I)
_HEDGE = re.compile(r"\bhedge\b|\bdelta[-\s]?neutral\b", re.I)
_THESIS = re.compile(r"\b(?:because|since|thesis\s*:|on the view that|reason\s*:|the idea is)\s+(.+?)(?:[.;!?]|$)", re.I)
_INVALID = re.compile(
    r"\b(?:invalidat\w*\s*(?:is|if|when|:)|(?:(?:i.m|it.s|this is|that.s)\s+)?wrong\s+if|abort\s+if|bail\s+if|proves?\s+(?:it|me)\s+wrong\s+if)\s*(.+?)(?:[.;!?]|$)",
    re.I,
)


@dataclass
class RuleIntent:
    """The same shape the model's parse produces, so one caller serves both."""

    kind: str = "clarify"
    ticker: str | None = None
    side: str | None = None
    notional_quote: float | None = None
    account_equity_quote: float | None = None
    horizon_kind: str | None = None
    horizon_hours: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    thesis: str | None = None
    invalidation: str | None = None
    hedge_ratio: float | None = None
    missing_fields: list[str] = field(default_factory=list)
    reply: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "ticker": self.ticker, "side": self.side, "notional_quote": self.notional_quote,
            "account_equity_quote": self.account_equity_quote, "horizon_kind": self.horizon_kind,
            "horizon_hours": self.horizon_hours, "stop_price": self.stop_price, "target_price": self.target_price,
            "thesis": self.thesis, "invalidation": self.invalidation, "hedge_ratio": self.hedge_ratio,
            "missing_fields": self.missing_fields, "reply": self.reply,
        }


ASKS = {"ticker": "which token", "side": "long or short", "notional_quote": "what size in USDT"}
# A holding period both parsers can name but the ticket does not carry as a kind: it is
# turned into hours when the ticket is built, because it depends on when that is.
THROUGH_WEEKEND = "through_weekend"


def horizon_fields(kind: str | None, hours: float | None) -> tuple[HorizonKind, float | None, str | None]:
    """A parsed holding period as the ticket's (kind, hours, label)."""
    if kind == THROUGH_WEEKEND:
        from nightwatch.analog.outcomes import hours_through_weekend
        from nightwatch.time_utils import utc_now

        return HorizonKind.HOURS, round(hours_through_weekend(utc_now()), 2), "through the weekend, to the next open after it"
    if kind in ("next_open", "window_end", "hours"):
        return HorizonKind(kind), hours, None
    return HorizonKind.NEXT_OPEN, hours, None


def _money(groups: tuple) -> float | None:
    """One match of ``_MONEY`` as a number, applying a k/m/b suffix."""
    for value, scale in ((groups[0], groups[1]), (groups[2], groups[3]), (groups[4], None)):
        if value:
            n = float(value.replace(",", ""))
            return n * _SCALE[scale.lower()] if scale else n
    return None


def _find_ticker(text: str, known: list[str]) -> str | None:
    upper = {t.upper() for t in known}
    cash = re.search(r"\$([A-Za-z]{1,5})\b", text)
    if cash and cash.group(1).upper() in upper:
        return cash.group(1).upper()
    for token in re.findall(r"\b[A-Z]{2,5}\b", text):  # written as a ticker
        if token in upper:
            return token
    low = text.lower()
    for name, ticker in ALIASES.items():
        if ticker in upper and re.search(rf"\b{re.escape(name)}\b", low):
            return ticker
    for token in re.findall(r"\b[a-zA-Z]{2,5}\b", text):  # typed in lower case
        if token.upper() in upper:
            return token.upper()
    return None


def _settle(out: RuleIntent) -> RuleIntent:
    out.missing_fields = [n for n, v in (("ticker", out.ticker), ("side", out.side), ("notional_quote", out.notional_quote)) if not v]
    if out.missing_fields:
        out.kind = "clarify"
        example = ' For example: "long 25k TSLA overnight, stop 340".' if len(out.missing_fields) == 3 else ""
        out.reply = "I need " + ", ".join(ASKS[m] for m in out.missing_fields) + "." + example
    else:
        out.kind = "analyze"
        out.reply = f"Running {out.side} {out.notional_quote:,.0f} USDT in {out.ticker}."
    return out


def parse_message(text: str, known_tickers: list[str], account_equity: float | None = None) -> RuleIntent:
    """Read one message into a ticket. Nothing is invented; what is absent is asked for."""
    out = RuleIntent()
    out.ticker = _find_ticker(text, known_tickers)

    short, long_ = _SHORT.search(text), _LONG.search(text)
    if short and (not long_ or short.start() < long_.start()):
        out.side = "short"
    elif long_:
        out.side = "long"

    stop, target, equity = _STOP.search(text), _TARGET.search(text), _EQUITY.search(text)
    out.stop_price = float(stop.group(1).replace(",", "")) if stop else None
    out.target_price = float(target.group(1).replace(",", "")) if target else None
    if equity:
        scale = _SCALE[equity.group(2).lower()] if equity.group(2) else 1.0
        out.account_equity_quote = float(equity.group(1).replace(",", "")) * scale
    elif account_equity:
        out.account_equity_quote = account_equity

    # Size is the money left over once the labelled numbers are accounted for.
    spent = [m.span() for m in (stop, target, equity) if m]
    for m in _MONEY.finditer(text):
        if any(s <= m.start() < e for s, e in spent):
            continue
        value = _money(m.groups())
        if value is not None and value != out.account_equity_quote:
            out.notional_quote = value
            break
    if out.notional_quote is None:
        for m in _BARE_MONEY.finditer(text):
            if any(s <= m.start() < e for s, e in spent):
                continue
            if _PRICE_WORD.search(text[: m.start()]):
                continue
            value = float(m.group(1).replace(",", ""))
            if value >= BARE_MONEY_FLOOR and value != out.account_equity_quote:
                out.notional_quote = value
                break

    hours, days = _HOURS.search(text), _DAYS.search(text)
    if _WEEKEND.search(text):
        out.horizon_kind = THROUGH_WEEKEND
    elif _NEXT_OPEN.search(text):
        out.horizon_kind = "next_open"
    elif _WINDOW_END.search(text):
        out.horizon_kind = "window_end"
    elif hours:
        out.horizon_kind, out.horizon_hours = "hours", float(hours.group(1))
    elif days:
        out.horizon_kind, out.horizon_hours = "hours", float(days.group(1)) * 24.0
    elif re.search(r"\b(?:a|one)\s+week\b", text, re.I):
        out.horizon_kind, out.horizon_hours = "hours", 168.0
    # Left as None when the message says nothing about a horizon. A conversation merges
    # message by message, so filling in the default here would let "make it 30k" quietly
    # overwrite the "for 8 hours" from the message before it. The default is applied once,
    # when the ticket is built.

    pct = _HEDGE_PCT.search(text)
    if pct:
        out.hedge_ratio = min(1.0, float(pct.group(1)) / 100.0)
    elif _HEDGE.search(text):
        out.hedge_ratio = 0.5 if re.search(r"\bhalf\b", text, re.I) else 1.0

    thesis, invalid = _THESIS.search(text), _INVALID.search(text)
    out.thesis = thesis.group(1).strip() if thesis else None
    out.invalidation = invalid.group(1).strip() if invalid else None
    return _settle(out)


def read_conversation(messages: list[dict[str, str]], known_tickers: list[str], account_equity: float | None = None) -> RuleIntent:
    """Build one ticket from every user message so far.

    A conversation gets there a piece at a time - "stress test TSLA for me", "long",
    "25k" - and the latest message wins wherever it speaks.
    """
    merged = RuleIntent()
    for m in messages:
        if m.get("role") != "user" or not (m.get("content") or "").strip():
            continue
        latest = parse_message(m["content"], known_tickers, account_equity)
        for key, value in latest.as_dict().items():
            if key in ("kind", "reply", "missing_fields") or value in (None, [], ""):
                continue
            setattr(merged, key, value)
    if merged.account_equity_quote is None and account_equity:
        merged.account_equity_quote = account_equity
    return _settle(merged)


def intent_to_ticket(p: RuleIntent, account_equity: float | None) -> TradeTicket:
    kind, hours, label = horizon_fields(p.horizon_kind, p.horizon_hours)
    return TradeTicket(
        ticker=(p.ticker or "").upper(), side=Side(p.side or "long"), notional_quote=float(p.notional_quote or 0.0),
        account_equity_quote=p.account_equity_quote or account_equity, horizon_kind=kind, horizon_hours=hours,
        stop_price=p.stop_price, target_price=p.target_price, thesis=p.thesis or "", invalidation=p.invalidation or "",
        hedge_ratio=p.hedge_ratio, extra={"horizon_label": label} if label else {},
    )


def _pct(v: float, digits: int = 1) -> str:
    """A signed percentage whose sign comes from the rounded value: a median of -0.04%
    rounds to zero, and "-0.0%" reads as a loss that is not there."""
    text = f"{abs(v):.{digits}f}%"
    sign = "+" if round(v, digits) > 0 else "-" if round(v, digits) < 0 else ""
    return sign + text


# The verdict names in Chinese, for a trader who wrote in Chinese. The numbers are the
# same numbers, formatted the same way; only the words around them change.
VERDICT_ZH = {"GO": "可以做", "REDUCE": "建议减仓", "HEDGE": "建议对冲", "REVIEW": "需要复核", "NO_GO": "不建议做"}
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def needs_the_model(text: str) -> bool:
    """Whether a message has something in it the rules cannot read.

    The rules read the shapes traders type - "long 20k TSLA overnight, stop 350" - and
    they read them in milliseconds. The model reads anything, in 10-60 s. So the model is
    asked only when there is something only it can do: a message not in English, or a
    request to narrow which past moments count, which the rules have no vocabulary for.
    Anything the rules cannot complete goes to the model anyway.
    """
    low = (text or "").lower()
    if _CJK.search(low):
        return True
    # Condition phrases alone are not enough: "long 20k TSLA overnight" names a night
    # without asking to be compared only against nights. People asking to narrow say so.
    if re.search(r"\bonly\b|\bjust\b|\bexcept\b|\bexclud\w*\b|\bcompare\b", low):
        return True
    return False


def language_of(text: str) -> str:
    """"zh" when the trader wrote in Chinese, else "en"."""
    return "zh" if _CJK.search(text or "") else "en"


def _horizon_phrase(report: Any, lang: str) -> str:
    t, h = report.ticket, report.horizon_h
    label = (t.extra or {}).get("horizon_label") if isinstance(t.extra, dict) else None
    if lang == "zh":
        if label:
            return f"持有过周末（{h:.0f} 小时，到周末后的第一个美股开盘）"
        if t.horizon_kind == HorizonKind.NEXT_OPEN:
            return f"持有到下一次美股开盘（{h:.0f} 小时）"
        if t.horizon_kind == HorizonKind.WINDOW_END:
            return f"持有到本时段结束（{h:.0f} 小时）"
        return f"持有 {h:.0f} 小时"
    if label:
        return f"{label} ({h:.0f}h)"
    if t.horizon_kind == HorizonKind.NEXT_OPEN:
        return f"until the next US open ({h:.0f}h)"
    if t.horizon_kind == HorizonKind.WINDOW_END:
        return f"to the end of this window ({h:.0f}h)"
    return f"for {h:.0f}h"


def brief(report: Any, lang: str = "en") -> str:
    """The report as a short briefing, assembled from its own fields.

    Every number here is copied from the report, which is the rule the model is held to
    as well - the difference is that a rule cannot break it. ``lang`` changes the words,
    never the numbers.
    """
    zh = lang == "zh"
    v, t = report.verdict, report.ticket
    lines: list[str] = []
    side = ("做多" if t.side == Side.LONG else "做空") if zh else t.side.value
    if zh:
        head = f"{VERDICT_ZH.get(v.verdict.value, v.verdict.value)}：{t.ticker} {side} {t.notional_quote:,.0f} USDT，{_horizon_phrase(report, lang)}。"
    else:
        head = f"{v.verdict.value} on {side} {t.notional_quote:,.0f} USDT of {t.ticker}, {_horizon_phrase(report, lang)}."
    if v.recommended_notional is not None and abs(v.recommended_notional - t.notional_quote) > 1:
        head += f" 建议仓位改为 {v.recommended_notional:,.0f}。" if zh else f" Size it at {v.recommended_notional:,.0f} instead."
    if v.hedge_ratio:
        head += f" 用永续合约对冲 {v.hedge_ratio:.0%}。" if zh else f" Hedge {v.hedge_ratio:.0%} with the perp."
    lines.append(head)

    analog = report.analog
    horizon = analog.horizons.get(report.primary_horizon) if analog else None
    if horizon is not None and horizon.cohort.n:
        c = horizon.cohort
        p5 = horizon.p5_adjusted if horizon.p5_adjusted is not None else c.p5
        if p5 is not None and c.median_pct is not None:
            if zh:
                line = f"历史：找到 {c.n} 个与现在相似的时刻；中位结果 {_pct(c.median_pct)}，最差的二十分之一低于 {_pct(p5)}。"
            else:
                line = f"History: {c.n} past moments like this one; the middle outcome was {_pct(c.median_pct)} and one in twenty was worse than {_pct(p5)}."
            lens = getattr(analog, "lens", None)
            if lens is not None and lens.applied and lens.lenses:
                from nightwatch.analog.lens import describe

                line += f"（只比较：{describe(lens.lenses)}）" if zh else f" Compared only against {describe(lens.lenses)}."
            lines.append(line)

    paths = getattr(analog, "paths", None) if analog else None
    if t.stop_price and paths is not None and paths.stop_pct is not None and paths.paths:
        n = len(paths.paths)
        if zh:
            lines.append(f"你的止损 {t.stop_price:,.2f} 距现价 {abs(paths.stop_pct):.1f}%；过去 {n} 个相似时刻里有 {paths.stopped} 个会在途中触发它。")
        else:
            lines.append(f"Your stop at {t.stop_price:,.2f} is {abs(paths.stop_pct):.1f}% away; {paths.stopped} of {n} past moments like this would have hit it on the way.")

    priced = [i for i in report.stress.impacts if i.total_pnl_quote is not None]
    if priced:
        worst = min(priced, key=lambda i: i.total_pnl_quote)
        name = next((s.name for s in report.stress.presets if s.id == worst.scenario_id), worst.scenario_id)
        if zh:
            lines.append(f"最坏压力情景（{name}）：仓位 {_pct(worst.total_pct_of_notional)}，约 {worst.total_pnl_quote:,.0f} USDT。")
        else:
            lines.append(f"Worst stress preset ({name}): {_pct(worst.total_pct_of_notional)} of the position, about {worst.total_pnl_quote:,.0f} USDT.")
    mc = report.stress.monte_carlo
    if mc is not None:
        if zh:
            lines.append(f"模拟尾部：二十条路径中最差的一条收在 {_pct(mc.p5)} 以下，同一分位的最大回撤超过 {_pct(mc.drawdown_p5)}。")
        else:
            lines.append(f"Simulated tail: one path in twenty ends below {_pct(mc.p5)}, and the worst drawdown is past {_pct(mc.drawdown_p5)} in the same fifth percentile.")

    q = report.execution.exit_quote
    if q is not None:
        if zh:
            lines.append(f"平仓成本：按{'实时' if report.execution.book_source == 'live' else '记录的'}盘口约 {q.total_cost_bps:.0f} bps，约 {q.total_cost_quote:,.0f} USDT。")
        else:
            lines.append(f"Getting out costs {q.total_cost_bps:.0f} bps on the {report.execution.book_source} book, about {q.total_cost_quote:,.0f} USDT.")

    street = getattr(report, "street", None)
    if street and street.get("token_vs_live_bps") is not None:
        live = street["token_vs_live_bps"]
        if zh:
            lines.append(f"此刻：代币价格与正股的实时价格相差 {live:+.0f} bps（Bitget 数据）。")
        else:
            lines.append(f"Right now the token sits {live:+.0f} bps from the stock's live price (Bitget data).")

    capped = [c for c in v.caps if c.notional is not None]
    if capped:
        binding = min(capped, key=lambda c: c.notional)
        if binding.notional < t.notional_quote - 1:  # a cap above the request binds nothing
            if zh:
                lines.append(f"限制仓位的是 {binding.name.replace('_', ' ')} 上限：{binding.detail}。")
            else:
                lines.append(f"The cap that binds is {binding.name.replace('_', ' ')}: {binding.detail}.")

    # A review that only wants the trader's own words is something they can clear in one
    # message, so say how rather than printing the rule's name at them.
    plan_missing = [r for r in report.gate.rules if r.rule == "written_plan" and r.decision.value != "GO"]
    reasons = [r for r in v.reasons if not r.startswith("written plan")]
    if reasons:
        lines.append(("原因：" if zh else "Why: ") + "; ".join(reasons[:3]) + ("。" if zh else "."))
    if report.second_opinion and report.second_opinion.against:
        lines.append(("反方观点：" if zh else "Case against: ") + report.second_opinion.against[0].text)
    if plan_missing:
        if zh:
            lines.append("要通过复核：告诉我你为什么做这笔交易，以及什么情况说明你错了——例如“因为……，如果收盘跌破……就算错”——我会重新检查。")
        else:
            lines.append("To clear the review, tell me why you want this trade and what would prove it wrong - e.g. \"because ..., wrong if it closes below ...\" - and I'll re-check it.")
    return "\n\n".join(lines)


def is_a_new_idea(text: str, context: dict[str, Any], known_tickers: list[str]) -> bool:
    """True when a message is a fresh trade idea rather than a question about the last one.

    Naming a different token is enough, whether or not the rest of the ticket is there.
    "what about 20k of NVDA?" is phrased as a question and means run it - and if the side
    is missing, the right answer is to ask for the side, not to talk about TSLA. "What if
    I do 40k" names no token and means ask the report on screen.
    """
    parsed = parse_message(text, known_tickers)
    if not parsed.ticker:
        return False
    current = ((context.get("ticket") or {}).get("ticker") or "").upper()
    return parsed.ticker.upper() != current


def rule_turn(state: Any, messages: list[dict[str, str]], *, account_equity: float | None = None) -> dict[str, Any]:
    """One conversational turn with no model involved, in the same shape as the model's.

    ``unverified_numbers`` is always empty here and that is not a boast: the briefing is
    built by formatting the report's own fields, so there is nothing to verify.
    """
    import json

    from nightwatch.pipeline.analyze import analyze
    from nightwatch.pipeline.render import render_text

    tickers = list(state.ctx.tickers_with_data())
    intent = read_conversation(messages, tickers, account_equity)
    result: dict[str, Any] = {
        "intent": intent.as_dict(), "ticket": None, "report": None, "narrative": None,
        "report_text": None, "unverified_numbers": [], "mode": "rules",
    }
    if intent.kind != "analyze":
        result["reply"] = intent.reply
        return result
    if (intent.ticker or "").upper() not in {t.upper() for t in tickers}:
        result["intent"]["kind"] = "clarify"
        result["reply"] = f"{intent.ticker} is not in the tokenized-stock universe I have data for. Available: {', '.join(tickers[:20])}{'...' if len(tickers) > 20 else ''}."
        return result
    ticket = intent_to_ticket(intent, account_equity)
    with state.lock:
        report = analyze(state.ctx, ticket)
        payload = report.to_dict()
        # Keep it, so the next message can be a question about this answer.
        if report.forecast_id is not None:
            try:
                state.reports.save(report.forecast_id, payload)
            except Exception as exc:  # noqa: BLE001 - a keepsake must not fail the turn
                log.warning("could not store the chat report: %s", exc)
    narrative = brief(report)
    result.update({
        "ticket": json.loads(json.dumps(ticket.__dict__, default=str)),
        "report": payload,
        "report_text": render_text(report),
        "narrative": narrative,
        "reply": narrative,
    })
    return result
