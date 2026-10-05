"""The turns where a trader gives less than a full ticket, and the desk still has to help.

Three of them dead-ended a judge on the live desk:

* "5x long TSLA overnight, my account is 50k" has a token, a side and an account but no
  position size. The desk asked for one. It can answer instead: the sensitivity search
  already finds the largest size that still passes, so it runs that and says plainly that
  the size is its own, not the trader's.
* "should I buy NVDA?" asks for a direction. The desk does not predict one, and says so,
  then runs the trade at a stated stand-in size so the answer is still the desk's verdict.
* "long 5k XYZQ over the weekend" names a token the desk does not cover. It lists the ones
  it does.

A size is never invented silently: every reply that uses one says whose it is.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import replace
from typing import Any

log = logging.getLogger(__name__)

# What the desk uses when the trader gave neither a size nor an account. Said out loud.
STAND_IN_SIZE = 10_000.0

# "Should I buy NVDA?", "is it worth buying", "该买吗", "要不要买特斯拉".
SHOULD_I = re.compile(
    r"\bshould (?:i|we)\b|\bis (?:it|this) (?:a )?(?:good|worth)\b|\bworth (?:buying|it)\b|\bwould you (?:buy|short|go)\b|\bgo for it\b"
    r"|该买|该不该|要不要(?:买|做|入|上车)|能买吗|可以买吗|值得买|值不值|买吗|做多吗|做空吗|该做",
    re.I,
)

# Capital words that are not tickers, so "LONG" or "USDT" is never reported as an unknown token.
_NOT_TICKERS = frozenset(
    "I A AN AND OR OF TO IN ON AT IT IS BE DO GO NO OK OKAY PM AM ET EST EDT UTC GMT USD USDT USDC BTC ETH LONG SHORT BUY SELL HOLD STOP TP SL "
    "PNL ROI ETF IPO CEO CFO FED CPI FOMC GDP NFP AI API MCP LLM FAQ HELP WHAT WHY HOW WHEN WHO IF THE FOR NOW NOT YES ALL ANY MAX MIN BIG "
    "UP DOWN GAP EOD ATH ATL RSI MACD VAR OTC NYSE US UK EU CN HK TIME OPEN CLOSE WEEK DAY HR HRS K M B W X".split()
)
_CANDIDATE = re.compile(r"(?<![\w$])\$?([A-Z]{2,5})(?![\w])")


def unknown_token(text: str, known: list[str]) -> str | None:
    """A ticker-looking word the desk does not cover, or None.

    Only an upper-case word, or a ``$cash`` tag, counts: "xyzq" in the middle of a sentence
    is too likely to be an ordinary word to call it a token.
    """
    upper = {t.upper() for t in known}
    for m in _CANDIDATE.finditer(text or ""):
        word = m.group(1)
        if word in upper or word in _NOT_TICKERS:
            continue
        return word
    cash = re.search(r"\$([A-Za-z]{2,5})\b", text or "")
    if cash and cash.group(1).upper() not in upper and cash.group(1).upper() not in _NOT_TICKERS:
        return cash.group(1).upper()
    return None


# A trade that names its token right beside the side or the size: "long 10k ZZZZ",
# "buy $ZZZZ", "ZZZZ short 5k", "做多 ZZZZ 2万U". Only an upper-case word or a $tag counts.
_SIDE_EN = r"(?:long|short|buy|sell)(?:ing)?"
_SIDE_ZH = r"(?:做多|做空|买入|卖出|买|卖)"
_SIZE = r"(?:\$?\s*[\d,]+(?:\.\d+)?\s*[kKmMbBwW万千]?\s*(?:usdt|usd|u|U|美元|美金|刀)?)"
_AFTER_SIDE = re.compile(rf"(?:\b{_SIDE_EN}|{_SIDE_ZH})\s*(?:{_SIZE}\s*)?(?:(?:of|in|worth of)\s+)?(\$[A-Za-z]{{2,5}}|[A-Z]{{2,5}})(?![A-Za-z])", re.I)
_BEFORE_SIDE = re.compile(rf"(?<![A-Za-z$])(\$[A-Za-z]{{2,5}}|[A-Z]{{2,5}})\s*[,:：-]?\s*(?:{_SIDE_ZH}|\b{_SIDE_EN}\b)", re.I)


def named_unknown_ticker(text: str, known: list[str]) -> str | None:
    """The upper-case word a trade names as its token when the desk does not cover it.

    "long 10k ZZZZ" must never be answered as a trade in some other stock: if the message
    names a token beside its side or size and that token is not covered, that is the answer.
    A message that also names a covered token is left to the normal reading.
    """
    from nightwatch.api.intake import _find_ticker

    text = unicodedata.normalize("NFKC", text or "")
    upper = {t.upper() for t in known}
    if _find_ticker(text, known):
        return None
    for rx in (_AFTER_SIDE, _BEFORE_SIDE):
        for m in rx.finditer(text):
            raw = m.group(1)
            word = raw.lstrip("$").upper()
            if raw.startswith("$") or raw == raw.upper():
                if word not in upper and word not in _NOT_TICKERS:
                    return word
    return None


def unknown_ticker_reply(word: str, known: list[str], lang: str) -> str:
    names = ", ".join(sorted(t.upper() for t in known))
    n = len(known)
    if lang == "zh":
        return f"{word} 不在我们覆盖的 {n} 只代币化美股里：{names}。没有运行任何交易，屏幕上的报告没有变。请从这些里选一只，比如“周末做多 TSLA 2万U”。"
    return (f"{word} isn't one of the {n} tokenized stocks we cover: {names}. "
            "Nothing was run and the report on screen is unchanged. Pick one of these, e.g. \"long 10k TSLA over the weekend\".")


def covered_list(known: list[str], lang: str) -> str:
    names = ", ".join(sorted(t.upper() for t in known))
    return f"我覆盖这些：{names}。" if lang == "zh" else f"I cover: {names}."


def covered_reply(word: str | None, known: list[str], lang: str, *, have: str = "") -> str:
    """Say which tokens the desk covers, short, so the trader can pick one."""
    if lang == "zh":
        head = f"{word} 不在我覆盖的代币里。" if word else "没认出是哪只股票。"
        return f"{head}{have}{covered_list(known, lang)}选一个，比如“周末做多 TSLA 2万U”。"
    head = f"{word} isn't a token I cover." if word else "I did not catch which token you mean."
    return f"{head} {have}{covered_list(known, lang)} Pick one, e.g. \"long 10k TSLA over the weekend\"."


def no_token_reply(intent: Any, known: list[str], latest: str, lang: str) -> str | None:  # noqa: ANN401
    """The reply when no covered token was named and one of two things can be said better
    than "which token?": the word was a token the desk does not cover, or the question was
    "should I buy?", which has no direction to give but a desk to offer."""
    if intent.ticker:
        return None
    trade_like = bool(intent.side or intent.notional_quote)
    word = unknown_token(latest, known) if trade_like else None
    have = _have_said(intent, lang)
    if word:
        return covered_reply(word, known, lang, have=have)
    if SHOULD_I.search(latest or ""):
        if lang == "zh":
            return (f"我不预测涨跌。桌面能告诉你的是：这笔交易扛不扛得住风险、仓位最大能做多少。告诉我哪只股票（和仓位），我来算。{covered_list(known, lang)}")
        return ("I don't predict direction. What the desk can tell you is whether a trade holds up and how big it can be. "
                f"Name a token (and a size) and I'll run it. {covered_list(known, lang)}")
    return None


def _have_said(intent: Any, lang: str) -> str:  # noqa: ANN401
    bits = [x for x in (intent.side, f"{intent.notional_quote:,.0f} USDT" if intent.notional_quote else None) if x]
    if not bits:
        return ""
    return ("已记下：" + " · ".join(bits) + "。") if lang == "zh" else f"Got {', '.join(bits)}. "


def _k(v: float) -> str:
    """50000 -> "50k", 1250000 -> "1.25M"."""
    if v >= 1e6:
        return f"{v / 1e6:g}M"
    if v >= 1e3:
        return f"{v / 1e3:g}k"
    return f"{v:,.0f}"


def _wan(v: float) -> str:
    """50000 -> "5万U", the way a Chinese-speaking trader writes the account."""
    return f"{v / 1e4:g}万U" if v >= 1e4 else f"{v:,.0f}U"


def _floor_size(v: float) -> float:
    """Round down to a clean size, so the size shown is still one that passes."""
    step = 100.0 if v >= 2_000 else 10.0 if v >= 200 else 1.0
    return math.floor(v / step) * step if v >= step else v


def largest_size(state: Any, intent: Any, equity: float) -> tuple[float, str] | None:  # noqa: ANN401
    """The largest size the desk lets this idea run at on this account, and how it knows.

    One probe run at the gate's own per-position limit; the sensitivity search it carries
    bisects to the largest size that is still a GO. When no size is a GO, the size the
    desk's caps recommend is used instead and the basis says so.
    """
    from nightwatch.api.intake import intent_to_ticket
    from nightwatch.pipeline.analyze import analyze

    probe = max(100.0, equity * 0.25)
    ticket = intent_to_ticket(replace(intent, notional_quote=probe, account_equity_quote=equity), equity)
    with state.lock:
        report = analyze(state.ctx, ticket, record=False)
    sens = report.sensitivity
    if sens is not None and sens.max_go_notional:
        return _floor_size(float(sens.max_go_notional)), "largest_go"
    rec = report.verdict.recommended_notional or report.sizing.recommended_notional
    if rec and rec > 0:
        return _floor_size(float(rec)), "desk_cap"
    return None


def assumed_size_note(size: float, basis: str, equity: float | None, lang: str, *, should_i: bool = False) -> str:
    """The sentence that says the size is the desk's, and invites the trader's own.

    ``basis`` says how the size was found; the sentence is the same for both, because either
    way it is the largest size the desk's own limits allow on that account."""
    zh = lang == "zh"
    lead = ("我不预测涨跌。" if zh else "I don't predict direction. ") if should_i else ""
    if equity is None:
        if zh:
            return f"{lead}你没有给仓位和账户，我先用 {size:,.0f} USDT 作为参考仓位来算。告诉我你自己的仓位（和账户规模），我按你的来重算。"
        return (f"{lead}You didn't give a size or an account, so I used a stand-in of {size:,.0f} USDT to show how the desk judges a trade like this. "
                "Give me your own size (and account) and I'll run that instead.")
    if zh:
        return f"{lead}你没有给仓位，所以这里是桌面在 {_wan(equity)} 账户上允许的最大仓位：{size:,.0f} USDT。想用自己的仓位，直接告诉我。"
    return (f"{lead}You didn't give a size, so here is the largest size the desk allows on a {_k(equity)} account: {size:,.0f} USDT. "
            "Tell me your own size and I'll run that instead.")


def with_assumed_size(state: Any, intent: Any, tickers: list[str], account_equity: float | None, latest: str, lang: str) -> tuple[Any, dict[str, Any]] | None:  # noqa: ANN401
    """The intent completed with a stated size, or None when the desk should ask instead.

    Applies only when the one thing missing is the size and the token is covered. With an
    account the size is the largest the desk allows; without one it is used only for a
    "should I buy" question, where the stand-in is announced and the trader asked for a view.
    """
    from nightwatch.api.intake import _settle

    if intent.kind == "analyze" or intent.missing_fields != ["notional_quote"] or not intent.side:
        return None
    if (intent.ticker or "").upper() not in {t.upper() for t in tickers}:
        return None
    equity = intent.account_equity_quote or account_equity
    should_i = bool(SHOULD_I.search(latest or ""))
    if equity:
        got = largest_size(state, intent, float(equity))
        if got is None:
            return None
        size, basis = got
    elif should_i:
        size, basis = STAND_IN_SIZE, "stand_in"
    else:
        return None
    done = replace(intent, notional_quote=size, account_equity_quote=equity or None, notes=list(intent.notes))
    done = _settle(done)
    note = assumed_size_note(size, basis, float(equity) if equity else None, lang, should_i=should_i)
    done.notes = [*done.notes, note]
    return done, {"notional_quote": size, "basis": basis, "account_equity_quote": equity or None, "note": note}
