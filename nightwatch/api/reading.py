"""Saying back what the desk understood, and what it could not use.

A trader who types "shrot Appl 5k ovr earnigns" gets a verdict on a trade they cannot see
the desk's reading of. When the reading is wrong - a margin taken for an account, a hold
carried over from the last ticker, "earnings" dropped - the verdict is an answer to a
question they did not ask, and nothing says so. The first reply to a trade therefore opens
with one line, "I read this as: ...", built from the ticket the engine actually ran, and
a "not used" list for every part of the message the rules could not turn into a field.

The line is assembled from the ticket, never from the message, so it can only say what the
engine did: it cannot echo a field the engine did not receive.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from nightwatch.stress.scenarios import Side

_BULLISH_SLANG = re.compile(r"🚀|\brocket\w*\b|\bmoon\w*\b|\byolo\b|\bape\b|\baping\b|\bsend it\b|\bto the moon\b|冲|起飞|梭哈", re.I)
_STOP_WORD = re.compile(r"\bstop\b|止损", re.I)
_TARGET_WORD = re.compile(r"\btarget\b|\btake[-\s]?profit\b|\btp\b|止盈", re.I)
_EARN_WORD = re.compile(r"\bearn\w{2,7}\b|财报", re.I)


def _short(text: str, n: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def unused_parts(
    intent: Any,  # noqa: ANN401 - RuleIntent
    ticket: Any,  # noqa: ANN401 - TradeTicket
    latest: str,
    lang: str,
    *,
    earnings_note: str | None = None,
    earnings_applied: bool = False,
    dropped_reason: str | None = None,
) -> list[str]:
    """What the message said that no field of the ticket carries, in the trader's words."""
    zh = lang == "zh"
    out: list[str] = []
    if earnings_note:
        out.append(earnings_note)
    elif getattr(intent, "through_earnings", False) and not earnings_applied:
        out.append("“过完财报”（你同时给了持有期，按持有期算）" if zh else "holding over earnings (you also gave a hold length, so I used that)")
    elif _EARN_WORD.search(latest) and not getattr(intent, "through_earnings", False):
        out.append("“财报”（没读出要持有到财报；说“持有过财报”我就把持有期拉到财报之后）" if zh
                   else '"earnings" (I could not tell if you mean holding through the report; say "hold through earnings" and I will stretch the hold)')
    slang = _BULLISH_SLANG.search(latest)
    if slang:
        word = slang.group(0)
        if ticket.side == Side.SHORT:
            out.append(f"“{word}”（读起来是看涨，但你说的是做空，按做空算）" if zh else f'"{word}" (reads bullish, but you said short, so I ran the short)')
        else:
            out.append(f"“{word}”（是情绪，不是交易参数）" if zh else f'"{word}" (a mood, not a trade input)')
    if _STOP_WORD.search(latest) and ticket.stop_price is None and ticket.stop_offset_pct is None:
        out.append("止损（没读出价格或百分比）" if zh else "stop (I could not read a price or a percentage)")
    if _TARGET_WORD.search(latest) and ticket.target_price is None:
        out.append("目标价（没读出价格）" if zh else "target (I could not read a price)")
    margin = getattr(intent, "margin_quote", None)
    if margin and not ticket.leveraged:
        out.append(f"保证金 {margin:,.0f}（没有杠杆或仓位可以对应）" if zh else f"margin {margin:,.0f} (needs a leverage or a size to mean anything)")
    if dropped_reason:
        out.append(f"“{_short(dropped_reason, 40)}”（不像一个理由，没有记为理由）" if zh else f'"{_short(dropped_reason, 40)}" (does not read as a reason, so it was not stored as one)')
    return out


def echo_line(report: Any, lang: str, *, carried: Mapping[str, str] | set[str] | frozenset[str] = frozenset(), unused: list[str] | None = None, earnings_hold: bool = False) -> str:  # noqa: ANN401
    """"I read this as: long 20,000 USDT of NVDA, 3x (margin 6,667), hold ..., account ..., stop ..., reason ...".

    ``carried`` names the fields that did not come from this message, each with where it did
    come from: a quote of the earlier message that typed it, the account box on the page, or
    the desk's own default. Every field is labelled with its true origin, never silently
    applied; a field typed in this message, or derived (the earnings hold, from the
    calendar), is labelled as such."""
    from nightwatch.api.intake import _horizon_phrase

    zh = lang == "zh"
    t = report.ticket
    side = ("做多" if t.side == Side.LONG else "做空") if zh else t.side.value
    origin = carried if isinstance(carried, Mapping) else {k: "" for k in carried}

    def tag(name: str, text: str) -> str:
        if name == "account" and "account_box" in origin:
            return text + ("（用的是页面上设置的账户）" if zh else " - the account you set on the page")
        if name == "hold" and "hold_default" in origin:
            return text + ("（你没说持有多久，这是系统默认）" if zh else " - the desk's default, you gave no hold")
        if name not in origin:
            return text
        said = origin[name]
        if not said:
            return text + ("（沿用你之前消息里的）" if zh else " - same as in your earlier message")
        return text + (f"（沿用你之前说的：“{said}”）" if zh else f' - typed earlier, in "{said}"')

    bits = [tag("size", f"{side} {t.ticker} {t.notional_quote:,.0f} USDT" if zh else f"{side} {t.notional_quote:,.0f} USDT of {t.ticker}")]

    if t.leveraged and t.leverage:
        margin = t.notional_quote / t.leverage
        bits.append(tag("leverage", f"{round(t.leverage, 2):g} 倍杠杆（保证金 {margin:,.0f}）" if zh else f"{round(t.leverage, 2):g}x leverage (margin {margin:,.0f})"))
    hold = _horizon_phrase(report, lang)
    if earnings_hold:
        hold += "，持有到财报之后（按财报日历推算）" if zh else ", through the earnings report (worked out from the earnings calendar)"
    bits.append(tag("hold", hold))
    if t.account_equity_quote:
        bits.append(tag("account", f"账户 {t.account_equity_quote:,.0f}" if zh else f"account {t.account_equity_quote:,.0f}"))
    else:
        bits.append("账户：未提供" if zh else "account: not given")
    if t.stop_price is not None:
        bits.append(tag("stop", f"止损 {t.stop_price:,.2f}" if zh else f"stop {t.stop_price:,.2f}"))
    elif t.stop_offset_pct is not None:
        bits.append(tag("stop", f"止损距现价 {abs(t.stop_offset_pct):g}%" if zh else f"stop {abs(t.stop_offset_pct):g}% away"))
    if t.thesis.strip():
        bits.append(tag("reason", f"理由“{_short(t.thesis)}”" if zh else f'reason "{_short(t.thesis)}"'))
    if t.invalidation.strip():
        bits.append(f"错在“{_short(t.invalidation)}”" if zh else f'wrong if "{_short(t.invalidation)}"')
    line = ("我的理解：" + "，".join(bits) + "。") if zh else ("I read this as: " + ", ".join(bits) + ".")
    if unused:
        line += ("没用上：" + "；".join(unused) + "。") if zh else (" Not used: " + "; ".join(unused) + ".")
    return line


def carried_fields(
    latest: str,
    tickers: list[str],
    merged: Any,  # noqa: ANN401
    messages: list[dict[str, str]] | None = None,
    account_equity: float | None = None,
) -> dict[str, str]:
    """Fields in the conversation's merged reading that this message did not state.

    A hold from the last ticker, a stop, a leverage: kept because an earlier message gave
    it. Said in the echo line, so it is never applied silently. With ``messages`` given, a
    field counts only when an earlier user message really stated it; an account that came
    from the page's account box instead is reported as ``account_box``, never as "said
    earlier".
    """
    from nightwatch.api.intake import parse_message

    alone = parse_message(latest, tickers)
    earlier = [(m["content"], parse_message(m["content"], tickers)) for m in (messages or [])[:-1] if m.get("role") == "user" and (m.get("content") or "").strip()]

    def said_in(attr: str) -> str | None:
        """The newest earlier message that typed this field, quoted; "" when no history is given."""
        if messages is None:
            return ""
        for text, e in reversed(earlier):
            if getattr(e, attr, None):
                return _short(text, 50)
        return None

    got: dict[str, str] = {}
    if merged.horizon_kind and not alone.horizon_kind and (q := said_in("horizon_kind")) is not None:
        got["hold"] = q
    elif not merged.horizon_kind and not alone.horizon_kind:
        got["hold_default"] = ""
    if (merged.stop_price or merged.stop_pct) and not (alone.stop_price or alone.stop_pct):
        q = said_in("stop_price") or said_in("stop_pct")
        if q is not None:
            got["stop"] = q
    if merged.leverage and not alone.leverage and (q := said_in("leverage")) is not None:
        got["leverage"] = q
    if merged.account_equity_quote and not alone.account_equity_quote:
        if (q := said_in("account_equity_quote")) is not None:
            got["account"] = q
        elif account_equity and float(account_equity) == float(merged.account_equity_quote):
            got["account_box"] = ""
    if merged.thesis and not alone.thesis and (q := said_in("thesis")) is not None:
        got["reason"] = q
    # Only a size an earlier message really stated. One the desk chose itself (the largest it
    # allows on the account) or computed from margin and leverage matches nothing said before.
    if merged.notional_quote and not alone.notional_quote and messages is not None:
        for text, e in reversed(earlier):
            if e.notional_quote and abs(e.notional_quote - merged.notional_quote) < 0.5:
                got["size"] = _short(text, 50)
                break
    return got


def apply_earnings_hold(state: Any, intent: Any, lang: str = "en") -> tuple[bool, str | None]:  # noqa: ANN401
    """Stretch a hold to the earnings report when the message asked for one, if the calendar can date it.

    Returns (applied, note). An explicit hold length in the message wins and is left alone;
    a report the calendar cannot date (none in the next 30 days) is not guessed at - the
    note says so and goes into the "not used" list.
    """
    from nightwatch.api.whatif import AFTER_REPORT_OPEN_H
    from nightwatch.pipeline import analyze as _analyze

    if not getattr(intent, "through_earnings", False) or intent.horizon_kind or not intent.ticker:
        return False, None
    zh_note = "“持有过财报”（下一次财报超过 30 天或无法确定日期，没有拉长持有期）"
    en_note = "holding over earnings (the next report is more than 30 days away or has no date, so I did not stretch the hold)"
    try:
        feats = state.ctx.snapshot_at(state.ctx.spec(intent.ticker), _analyze.utc_now()).features
        hte = feats.get("hours_to_earnings")
    except Exception:  # noqa: BLE001 - no calendar means no stretch, said plainly
        hte = None
    if hte is not None and float(hte) + AFTER_REPORT_OPEN_H <= 720.0:
        intent.horizon_kind, intent.horizon_hours = "hours", round(float(hte) + AFTER_REPORT_OPEN_H, 2)
        return True, None
    return False, zh_note if lang == "zh" else en_note
