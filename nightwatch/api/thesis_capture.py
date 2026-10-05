"""Reading a trader's reason and "wrong if" line out of a chat message.

The desk asks for exactly one thing to clear a review for a missing written plan: a
reason and what would prove it wrong ("because ..., wrong if it closes below ..."). The
trader types that, and until now it was read as something else - an account size, a
what-if - and thrown away, so the review never cleared.

This module only reads. It returns the two phrases the trader wrote, cut apart so the
reason does not swallow the invalidation, in English or Chinese. It never writes a
reason for them: where the message states none, it returns nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EN_REASON = re.compile(r"\b(?:because|cuz|coz|since|thesis\s*[:\-]|my (?:reason|thesis) (?:is|:)|reason\s*:|on the view that|the idea is)\s+(.+)", re.I | re.S)
# "wrong if it closes below 170", "I'm wrong if ...", "invalid below 170", "thesis is dead if ...",
# "bail if ...", "out if it breaks 170".
_EN_WRONG = re.compile(
    r"(?:\b(?:i'?m|i am|it'?s|this is|that'?s|the (?:thesis|idea|trade) is)\s+)?"
    r"\b(?:wrong|invalid(?:ated)?|broken|dead|bust)\s+(?:(?:if|when|once)\s+(?P<cond>.+?)|(?P<level>(?:below|above|under|over)\s+.+?))\s*(?=[.;!?]|$)"
    r"|\b(?:invalidat\w*|abort|bail|exit|get out|i'?m out|out|stop thesis)\s+(?:is\s+|at\s+)?(?:if|when|once)\s+(?P<cond2>.+?)\s*(?=[.;!?]|$)"
    r"|\bproves?\s+(?:it|me)\s+wrong\s+(?:if|when)\s+(?P<cond3>.+?)\s*(?=[.;!?]|$)"
    r"|\binvalidat\w*\s*(?:is|:|at|below|above)\s+(?P<cond4>.+?)\s*(?=[.;!?]|$)",
    re.I | re.S,
)
_ZH_REASON = re.compile(r"(?:因为|理由是|理由\s*[:：]|逻辑是|逻辑\s*[:：]|论点\s*[:：])\s*(.+)", re.S)
_ZH_WRONG_IF = re.compile(r"(?:如果|若|假如|要是)\s*(?P<c>[^，,。；;]+?)\s*(?:就算错|就错了?|就是错|说明我错|就止损|则离场|就离场|就认错|就不对|我就错)")
_ZH_WRONG_LEVEL = re.compile(r"(?P<c>[^，,。；;]*?(?:跌破|涨破|突破|收盘|低于|高于|跌到|涨到|跌穿|站不上|守不住)[^，,。；;]*?)\s*(?:就算错|就错了?|就是错|说明我错|就止损|就离场|就认错|就不对|我就错)")
_ACCOUNT_TAIL = re.compile(r"[,;，；]?\s*(?:my\s+)?(?:account|equity|portfolio|capital|账户|本金)\s*(?:is\s+|=|:|：|是|有)?\s*\$?\d[\d,.]*\s*[kmwKMW万千]?\s*(?:usdt|usd|u|U|美元|美金)?\s*$", re.I)
_TRIM = " \t\r\n,;:.!?，。；：！？、"


@dataclass(frozen=True)
class Reason:
    thesis: str = ""
    invalidation: str = ""

    def __bool__(self) -> bool:
        return bool(self.thesis or self.invalidation)


def _clean(s: str) -> str:
    return s.strip(_TRIM)


def read(text: str) -> Reason:
    """The reason and the invalidation a message states; empty where it states none."""
    text = (text or "").strip()
    if not text:
        return Reason()
    zh = bool(re.search(r"[㐀-鿿]", text))
    wrong = ""
    cut = len(text)
    if zh:
        m = _ZH_WRONG_IF.search(text) or _ZH_WRONG_LEVEL.search(text)
        if m:
            wrong, cut = _clean(m.group("c")), m.start()
    if not wrong:
        m = _EN_WRONG.search(text)
        if m:
            got = next((m.group(g) for g in ("cond", "level", "cond2", "cond3", "cond4") if m.group(g)), "")
            wrong = _clean(got)
            cut = min(cut, m.start())
    wrong = _clean(_ACCOUNT_TAIL.sub("", wrong))
    reason = ""
    r = (_ZH_REASON.search(text) if zh else None) or _EN_REASON.search(text)
    if r:
        body = r.group(1)
        end = cut - r.start(1)
        if 0 < end < len(body):
            body = body[:end]
        # A sentence ends the reason; so does a comma that starts the "wrong if" clause.
        body = re.split(r"[.;!?。；！？\n]", body, maxsplit=1)[0]
        body = _ACCOUNT_TAIL.sub("", body)
        reason = _clean(re.sub(r"\s*(?:and|but|so)\s*$", "", _clean(body), flags=re.I))
    elif zh and wrong:
        # "我觉得会涨，跌破170就算错": the clause before the invalidation is the view.
        head = _clean(text[:cut])
        reason = _clean(re.sub(r"^(?:我)?(?:觉得|认为|感觉)", "", head)) if head else ""
    return Reason(thesis=reason, invalidation=wrong)


# Words that mean the trader is giving a reason rather than typing a mood.
_MARKER = re.compile(r"\b(?:because|since|cuz|coz|due to|thanks to|given|after|on the back of|expect\w*|earnings|guidance|demand|growth|revenue|margins?|rates?|fed|cpi|ai|news|upgrade|downgrade|breakout|support|resistance|trend|momentum|oversold|overbought|undervalued|overvalued|valuation)\b|因为|由于|财报|需求|增长|利好|利空|突破|支撑|阻力", re.I)


def reads_as_reason(text: str | None) -> bool:
    """Whether a stored thesis is a reason, not stray words.

    "ovr earnigns rocket" was kept as the thesis of a trade. A reason needs enough words to
    say something and at least one that names a cause or a thing a stock moves on; a few
    typed fragments and an emoji are not one. Chinese counts characters, since it has no
    spaces.
    """
    t = re.sub(r"[^\w\s㐀-鿿]", " ", text or "").strip()
    if not t:
        return False
    if re.search(r"[㐀-鿿]", t):
        return len(re.sub(r"\s", "", t)) >= 4
    words = [w for w in t.split() if len(w) > 1]
    if len(words) < 3:
        return False
    return bool(_MARKER.search(t)) or len(words) >= 5
