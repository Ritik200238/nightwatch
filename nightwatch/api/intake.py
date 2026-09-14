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

import re
from dataclasses import dataclass, field
from typing import Any

from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.stress.scenarios import Side

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
_LONG = re.compile(r"\blong(?!\s*[-\s]?(?:term|dated|er\b))\b|\bbuy\b|\bbullish\b", re.I)
_STOP = re.compile(r"\bstop(?:[-\s]?loss)?\b\s*(?:is|at|of|:|=)?\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I)
_TARGET = re.compile(r"\b(?:target|take[-\s]?profit|tp)\b\s*(?:is|at|of|:|=)?\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I)
_EQUITY = re.compile(r"\b(?:equity|account|portfolio|book|capital|aum)\b[^.\d]{0,20}\$?\s*([\d,]+(?:\.\d+)?)\s*([kmb])?", re.I)
_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([kmb])?|\b([\d,]+(?:\.\d+)?)\s*([kmb])\b|\b([\d,]+(?:\.\d+)?)\s*(?:usdt|usd|dollars?)\b", re.I)
_HOURS = re.compile(r"\b([\d.]+)\s*(?:hours?|hrs?|h)\b", re.I)
_DAYS = re.compile(r"\b([\d.]+)\s*(?:days?|d)\b", re.I)
_NEXT_OPEN = re.compile(r"\bovernight\b|\b(?:until|till|to|through)\s+(?:the\s+)?(?:us\s+)?open\b|\bnext\s+open\b|\bover\s+the\s+weekend\b", re.I)
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

    hours, days = _HOURS.search(text), _DAYS.search(text)
    if _NEXT_OPEN.search(text):
        out.horizon_kind = "next_open"
    elif _WINDOW_END.search(text):
        out.horizon_kind = "window_end"
    elif hours:
        out.horizon_kind, out.horizon_hours = "hours", float(hours.group(1))
    elif days:
        out.horizon_kind, out.horizon_hours = "hours", float(days.group(1)) * 24.0
    elif re.search(r"\b(?:a|one)\s+week\b", text, re.I):
        out.horizon_kind, out.horizon_hours = "hours", 168.0
    else:
        out.horizon_kind = "next_open"

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
    kind = HorizonKind(p.horizon_kind) if p.horizon_kind in ("next_open", "window_end", "hours") else HorizonKind.NEXT_OPEN
    return TradeTicket(
        ticker=(p.ticker or "").upper(), side=Side(p.side or "long"), notional_quote=float(p.notional_quote or 0.0),
        account_equity_quote=p.account_equity_quote or account_equity, horizon_kind=kind, horizon_hours=p.horizon_hours,
        stop_price=p.stop_price, target_price=p.target_price, thesis=p.thesis or "", invalidation=p.invalidation or "",
        hedge_ratio=p.hedge_ratio,
    )


def brief(report: Any) -> str:
    """The report as a short briefing, assembled from its own fields.

    Every number here is copied from the report, which is the rule the model is held to
    as well - the difference is that a rule cannot break it.
    """
    v, t = report.verdict, report.ticket
    lines: list[str] = []
    head = f"{v.verdict.value} on {t.side.value} {t.notional_quote:,.0f} USDT of {t.ticker} over {report.horizon_h:.0f}h."
    if v.recommended_notional is not None and abs(v.recommended_notional - t.notional_quote) > 1:
        head += f" Size it at {v.recommended_notional:,.0f} instead."
    if v.hedge_ratio:
        head += f" Hedge {v.hedge_ratio:.0%} with the perp."
    lines.append(head)

    horizon = report.analog.horizons.get(report.primary_horizon) if report.analog else None
    if horizon is not None and horizon.cohort.n:
        c = horizon.cohort
        p5 = horizon.p5_adjusted if horizon.p5_adjusted is not None else c.p5
        if p5 is not None and c.median_pct is not None:
            line = f"History: {c.n} past moments like this one; the middle outcome was {c.median_pct:+.1f}% and one in twenty was worse than {p5:+.1f}%."
            if horizon.baseline is not None and horizon.baseline.permutation_p_value is not None:
                line += f" Against random hours of the same kind, p = {horizon.baseline.permutation_p_value:.2f}."
            lines.append(line)

    priced = [i for i in report.stress.impacts if i.total_pnl_quote is not None]
    if priced:
        worst = min(priced, key=lambda i: i.total_pnl_quote)
        name = next((s.name for s in report.stress.presets if s.id == worst.scenario_id), worst.scenario_id)
        lines.append(f"Worst stress preset ({name}): {worst.total_pct_of_notional:+.1f}% of the position, about {worst.total_pnl_quote:,.0f} USDT.")
    mc = report.stress.monte_carlo
    if mc is not None:
        lines.append(f"Simulated tail: one path in twenty ends below {mc.p5:+.1f}%, and the worst drawdown is past {mc.drawdown_p5:+.1f}% in the same fifth percentile.")

    q = report.execution.exit_quote
    if q is not None:
        lines.append(f"Getting out costs {q.total_cost_bps:.0f} bps on the {report.execution.book_source} book, about {q.total_cost_quote:,.0f} USDT.")
    capped = [c for c in v.caps if c.notional is not None]
    if capped:
        binding = min(capped, key=lambda c: c.notional)
        if binding.notional < t.notional_quote - 1:  # a cap above the request binds nothing
            lines.append(f"The cap that binds is {binding.name.replace('_', ' ')}: {binding.detail}.")
    if v.reasons:
        lines.append("Why: " + "; ".join(v.reasons[:3]) + ".")
    if report.second_opinion and report.second_opinion.against:
        lines.append("Case against: " + report.second_opinion.against[0].text)
    return "\n\n".join(lines)


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
    narrative = brief(report)
    result.update({
        "ticket": json.loads(json.dumps(ticket.__dict__, default=str)),
        "report": report.to_dict(),
        "report_text": render_text(report),
        "narrative": narrative,
        "reply": narrative,
    })
    return result
