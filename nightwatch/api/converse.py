"""The small turns of a conversation that are not trades and not questions about one.

A judge who types the way people talk hit three dead ends. "thanks, that helps" was read
as the start of a new trade and answered "which token, side and size?". "Compare to just
holding SPY", "is this better than NVDA?" and "short it instead" named a change to the
trade on screen, but the desk treated any other token as a new idea and asked for the
size again, although it was right there. These are read here, by rules, in
microseconds.
"""

from __future__ import annotations

import re
from typing import Any

ACK = re.compile(
    r"^\s*(?:ok(?:ay)?|cool|great|nice|thanks?|thank you|thx|ty|cheers|got it|makes sense|perfect|awesome|appreciated?|"
    r"appreciate it|understood|alright|all right|sounds good|good to know|fair enough|brilliant)"
    r"(?:[\s,!.]+(?:thanks?|thank you|that helps|that'?s helpful|helpful|man|bro|mate|a lot|so much|very much|got it|cool|great))*[\s!.]*$",
    re.I,
)
ACK_ZH = re.compile(r"^\s*(?:谢谢|多谢|感谢|谢了|好的|好|明白了?|懂了|收到|知道了|行|可以|了解)(?:[，,。！!\s]*(?:谢谢|多谢|很有用|有帮助|明白了?))*[了啊呀哈！!。~\s]*$")

# The other direction, on the trade already on screen.
FLIP = re.compile(
    r"^\s*(?:ok\s+|and\s+|then\s+|so\s+|what if (?:i|we)\s+|can i\s+)?(?:go\s+)?short\s+(?:it|this|that|instead)\b"
    r"|\bflip (?:it|the side|sides|the trade)\b|\bshort (?:it )?instead\b|\bthe other (?:way|side|direction)\b|\bopposite (?:side|direction|way)\b"
    r"|^\s*(?:ok\s+|and\s+|what if (?:i|we)\s+)?(?:go\s+)?long\s+(?:it|this|that)\s+instead\b"
    r"|改成做空|改为做空|反过来|反向|做空呢|改成做多|改为做多|做多呢",
    re.I,
)
# Words that ask to set another token beside, or in place of, the one on screen.
_ALONGSIDE = re.compile(
    r"\bcompare\b|\bvs\.?\b|\bversus\b|\bbetter than\b|\bworse than\b|\bsafer than\b|\briskier than\b|\binstead\b|\bwhat about\b|\bhow about\b"
    r"|\brather than\b|\bor\b|\bsame (?:for|with|in|on)\b|\bdo (?:it|this|the same) (?:for|with|in|on)\b|\bin\s+[A-Z]{2,5}\b"
    r"|对比|比较|换成|改成|那.{0,6}呢|比.{0,8}(?:好|差|安全|危险)",
    re.I,
)


def is_ack(text: str) -> bool:
    return bool(ACK.match(text or "") or ACK_ZH.match(text or ""))


def ack_reply(context: dict[str, Any] | None, lang: str) -> dict[str, Any]:
    """A short acknowledgement that keeps the trade on screen in play."""
    ticket = (context or {}).get("ticket") or {}
    ticker = ticket.get("ticker")
    short = ticket.get("side") == "short"  # a short is hurt by a rise
    if lang == "zh":
        text = (f"不客气。还可以继续问这笔 {ticker} 交易：为什么？· 如果{'涨' if short else '跌'} 10% 呢？· 仓位减半 · 最安全的持有方式是什么？或者直接描述一笔新交易。" if ticker
                else "不客气。准备好了就描述一笔交易，比如“周末做多特斯拉 2万U”。")
    else:
        text = (f"Glad it helped. Still here for this {ticker} trade: why? · what if it gaps {'up' if short else 'down'} 10%? · halve it · what's the safest way to hold it? "
                "Or describe a new one." if ticker else 'Any time. Describe a trade when you are ready, e.g. "long 20k TSLA over the weekend".')
    return {
        "intent": {"kind": "followup", "question": "ack", "missing_fields": [], "reply": text},
        "ticket": None, "report": None, "narrative": None, "report_text": None, "unverified_numbers": [],
        "reply": text, "mode": "rules", "answer_kind": "ack",
    }


def carries_the_trade(text: str, context: dict[str, Any] | None, tickers: list[str]) -> bool:
    """True when a message changes the trade on screen rather than starting a new one.

    Another token named without a size of its own ("compare to SPY", "is this better
    than NVDA?", "what about AAPL instead") means the same trade in that token; a flip
    ("short it instead") means the same trade the other way. A message that brings its
    own size is a new idea and is left to the intake.
    """
    if not context or not text:
        return False
    from nightwatch.api import intake

    current = str((context.get("ticket") or {}).get("ticker") or "").upper()
    if FLIP.search(text):
        return True
    parsed = intake.parse_message(text, tickers)
    other = parsed.ticker and parsed.ticker.upper() != current
    if not other or parsed.notional_quote:
        return False
    return bool(_ALONGSIDE.search(text) or text.strip().endswith(("?", "？")))
