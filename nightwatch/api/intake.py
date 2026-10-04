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
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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

# "2w" is how traders on Chinese-speaking desks write 20,000 (万 = ten thousand).
_SCALE = {"k": 1e3, "w": 1e4, "m": 1e6, "b": 1e9}

# "short term" is a horizon, not a direction. Same for "shorter" and "short-dated".
_SHORT = re.compile(r"\bshort(?:ing)?(?!\s*[-\s]?(?:term|dated|dur|er\b))\b|\bsell(?:ing)?\b|\bbearish\b|\bfade\b", re.I)
# "hold 20k of TSLA overnight" is a long position; a trader saying it would be surprised
# to be asked which way round they meant it.
_LONG = re.compile(r"\blong(?:ing)?(?!\s*[-\s]?(?:term|dated|er\b))\b|\bbuy(?:ing)?\b|\bbullish\b|\bhold(?:ing)?\b|\bcarry\b|\bkeep\b", re.I)
_STOP = re.compile(r"\bstop(?:[-\s]?loss)?\b\s*(?:is|at|of|:|=)?\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I)
# "stop 3% below", "a 2% stop": a distance, not a price. Read as a price, "stop 1% above"
# became a stop at 1.00 - 99.9% away, hit by every past moment - on a live test.
_STOP_PCT = re.compile(
    r"\bstop(?:[-\s]?loss)?\b\s*(?:is|at|of|:|=)?\s*(\d+(?:\.\d+)?)\s*%\s*(above|over|below|under)?"
    r"|\b(\d+(?:\.\d+)?)\s*%\s*(?:trailing\s+)?stop(?:[-\s]?loss)?\b",
    re.I,
)
_TARGET = re.compile(r"\b(?:target|take[-\s]?profit|tp)\b\s*(?:is|at|of|:|=)?\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I)
_EQUITY = re.compile(r"\b(?:equity|account|portfolio|book|capital|aum)\b[^.\d]{0,20}\$?\s*([\d,]+(?:\.\d+)?)\s*([kmbw](?![a-z]))?", re.I)
# "I have 100k", "I've got 50k": the money on hand, not a position. Not "I have 20k of TSLA"
# (a holding) and not "I have 3 ideas" (no scale, under a hundred).
_HAVE = re.compile(
    r"\b(?:i|we)(?:\s+(?:only\s+|just\s+)?have|'ve(?:\s+got)?|\s+got)\s+(?:about\s+|around\s+|roughly\s+|like\s+)?\$?([\d,]+(?:\.\d+)?)\s*([kmbw](?![a-z]))?"
    r"(?!\s*%)(?!\s*(?:usdt|usd|u|dollars?)?\s*(?:of|in|worth)\s+(?!my\b|the\b|account\b))",
    re.I,
)
_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([kmbw])?|\b([\d,]+(?:\.\d+)?)\s*([kmbw])\b|\b([\d,]+(?:\.\d+)?)\s*(?:usdt|usd|dollars?)\b", re.I)
# "long 20000 TSLA" states a size as plainly as "long 20k TSLA" does. A bare number is
# read as one only when nothing else has claimed it and it is not a price: "long TSLA at
# 350" is a level, and nobody sizes a position at fifty dollars.
_BARE_MONEY = re.compile(r"(?<![$\d.])\b(\d[\d,]{2,})\b(?!\s*(?:%|bps|hours?\b|hrs?\b|days?\b))", re.I)
_PRICE_WORD = re.compile(r"\b(?:at|@|price|near|around|above|below|under|over)\s*$", re.I)
BARE_MONEY_FLOOR = 100.0
_HOURS = re.compile(r"\b([\d.]+)\s*(?:hours?|hrs?|h)\b", re.I)
_DAYS = re.compile(r"\b([\d.]+)\s*(?:days?|d)\b", re.I)
_NEXT_OPEN = re.compile(r"\bovernight\b|\b(?:until|till|to|through)\s+(?:the\s+)?(?:us\s+)?open\b|\bnext\s+open\b", re.I)
# "Through the weekend" said on a Thursday is until Monday's open, not Thursday's.
_WEEKEND = re.compile(r"\b(?:through|over|across|for|into)\s+the\s+weekend\b|\b(?:into|until|till|to)\s+monday\b|\bmonday(?:'s)?\s+open\b|\bweekend\s+hold\b", re.I)
# "until Wednesday", "through Thursday's close": a named day, held to its open unless the
# close is said. Monday is the weekend rule's, which already means the open after it.
_WEEKDAY = re.compile(r"\b(?:until|till|to|through|into|by)\s+(?:next\s+)?(tues|wednes|thurs|fri)day(?:'s)?(?:\s+(open|close))?", re.I)
_DAY_INDEX = {"tues": 1, "wednes": 2, "thurs": 3, "fri": 4}
_WINDOW_END = re.compile(r"\b(?:until|till|to|by|into)\s+(?:the\s+)?close\b|\bsession\s+end\b", re.I)
# "5x", "5x leverage", "at 10x", "leverage 3", "3x lev". A multiple, never a size.
_LEVERAGE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*[x×](?![a-z])|\bleverage(?:d)?\s*(?:of|at|:|=)?\s*(\d{1,3}(?:\.\d+)?)\s*[x×]?", re.I)
# "20k margin", "margin of 4000", "with 5k collateral": the money put up, not the position.
_MARGIN = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kmbw])?\s*(?:usdt\s*)?(?:of\s+)?(?:margin|collateral)\b|\b(?:margin|collateral)\s*(?:of|is|:|=)?\s*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kmbw])?\b", re.I)
_HEDGE_PCT = re.compile(r"\bhedge\b[^.\d]{0,15}(\d{1,3})\s*%", re.I)
_HEDGE = re.compile(r"\bhedge\b|\bdelta[-\s]?neutral\b", re.I)
_THESIS = re.compile(r"\b(?:because|since|thesis\s*:|on the view that|reason\s*:|the idea is)\s+(.+?)(?:[.;!?]|$)", re.I)
_INVALID = re.compile(
    r"\b(?:invalidat\w*\s*(?:is|if|when|:)|(?:(?:i.m|it.s|this is|that.s)\s+)?wrong\s+if|abort\s+if|bail\s+if|proves?\s+(?:it|me)\s+wrong\s+if)\s*(.+?)(?:[.;!?]|$)",
    re.I,
)

# What the trader already holds. "hold 20k of TSLA overnight" is a trade, so the phrases
# that mean "I have this on already" need a word that says so: also / already / currently /
# still, or "I own", or an "I'm already long".
_HOLD_INTRO = re.compile(
    r"\b(?:(?:i|we)(?:'ve|\s+have)?\s+)?(?:(?:also|already|currently|still|now)\s+)+(?:hold(?:ing)?|have|own|got|carry|am\s+holding)\b"
    r"|\b(?:i|we)\s+(?:own|have\s+got|'ve\s+got)\b"
    r"|\bi(?:'m|\s+am)\s+(?:(?:also|already|currently|still)\s+)+(?P<side>long|short)\b"
    r"|\b(?:my|our)\s+(?:current\s+|existing\s+|open\s+)?(?:positions?|holdings?)\s*(?:are|is|:|=)",
    re.I,
)
_HELD_SEP = re.compile(r"(?:\s*(?:,|;|&|\band\b|\bplus\b|\balso\b|\bthen\b))*\s*", re.I)
_HELD_ITEM = re.compile(
    r"(?:(?P<lead>long|short)\s+)?(?:a\s+)?(?:position\s+(?:of|in)\s+)?(?:worth\s+)?"
    r"\$?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>[kmbw])?\b(?:\s*(?:usdt|usd|u|dollars?)\b)?\s*(?:of\s+|in\s+|worth\s+of\s+)?",
    re.I,
)
_HELD_NAME = re.compile(r"\$?([A-Za-z][A-Za-z&]{1,11})(?:\s+([A-Za-z]{2,8}))?")
_HELD_TRAIL = re.compile(r"\s+(?:(?:stock|shares?|token|position)\s+)?(long|short)\b", re.I)


def read_positions(text: str, known_tickers: list[str]) -> tuple[list[tuple[str, str, float]], str]:
    """Holdings the message states, and the message with those clauses blanked out.

    "long 20k TSLA, I also hold 30k NVDA" is one new trade and one holding; blanking the
    clause is what stops "hold" reading as a long and NVDA reading as the ticker. A list
    continues over "and"/"&"/"plus" ("... and short 10k AMD"), but a bare comma followed by
    an explicit side starts a new trade instead ("I hold 30k NVDA, long 20k TSLA").
    """
    found: list[tuple[str, str, float]] = []
    chars = list(text)
    for intro in _HOLD_INTRO.finditer(text):
        pos, first, last_end = intro.end(), True, None
        default_side = (intro.groupdict().get("side") or "long").lower()
        while True:
            sep = _HELD_SEP.match(text, pos)
            m = _HELD_ITEM.match(text, sep.end())
            if not m:
                break
            if not first and m.group("lead") and not re.search(r"and|&|plus", sep.group(), re.I):
                break  # "..., long 20k TSLA" is the next trade
            amount = float(m.group("num").replace(",", "")) * (_SCALE[m.group("scale").lower()] if m.group("scale") else 1.0)
            name = _HELD_NAME.match(text, m.end())
            if not name or amount < BARE_MONEY_FLOOR:
                break
            ticker, end = _find_ticker(name.group(1), known_tickers), name.end(1)
            if ticker is None and name.group(2):
                ticker, end = _find_ticker(f"{name.group(1)} {name.group(2)}", known_tickers), name.end(2)
            if ticker is None:
                break
            trail = _HELD_TRAIL.match(text, end)
            if trail:
                end = trail.end()
            found.append((ticker, (m.group("lead") or (trail.group(1) if trail else None) or default_side).lower(), amount))
            pos, last_end, first = end, end, False
        if last_end is not None:
            chars[intro.start():last_end] = " " * (last_end - intro.start())
    return found, "".join(chars)


def merge_positions(*groups: list[tuple[str, str, float]]) -> list[tuple[str, str, float]]:
    """Holdings across messages: a name held the same way is stated once, the later size winning."""
    book: dict[tuple[str, str], float] = {}
    for g in groups:
        for t, side, n in g:
            book[(t.upper(), side)] = float(n)
    return [(t, side, n) for (t, side), n in book.items()]


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
    # A stop given as a distance: how far, and which way if the trader said. Turned into a
    # price only once the entry price is known, which the parser never is.
    stop_pct: float | None = None
    stop_dir: str | None = None  # "above" | "below" | None = on the losing side
    leverage: float | None = None
    target_price: float | None = None
    thesis: str | None = None
    invalidation: str | None = None
    hedge_ratio: float | None = None
    # What the trader already holds, as (ticker, side, notional); merged over a conversation.
    open_positions: list[tuple[str, str, float]] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    reply: str = ""
    # Things the reader changed or ignored, said back to the trader ("a stop at 0 is not a
    # price, so it was left out"), and whether a negative size was refused.
    notes: list[str] = field(default_factory=list)
    negative_size: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "ticker": self.ticker, "side": self.side, "notional_quote": self.notional_quote,
            "account_equity_quote": self.account_equity_quote, "horizon_kind": self.horizon_kind,
            "horizon_hours": self.horizon_hours, "stop_price": self.stop_price, "stop_pct": self.stop_pct, "stop_dir": self.stop_dir,
            "leverage": self.leverage,
            "target_price": self.target_price,
            "thesis": self.thesis, "invalidation": self.invalidation, "hedge_ratio": self.hedge_ratio,
            "open_positions": [list(p) for p in self.open_positions],
            "missing_fields": self.missing_fields, "reply": self.reply, "notes": self.notes,
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


def hours_until_weekday(weekday: int, which: str = "open", now: datetime | None = None) -> float | None:
    """Hours from now to the next regular open (or close) on a named weekday, 0=Monday.

    A holiday on that day moves it to the next trading day, which is when the position
    could actually be closed at the regular session.
    """
    from nightwatch.time_utils import ET, _regular_bounds, is_trading_day, next_trading_day, utc_now

    now = now or utc_now()
    local = now.astimezone(ET)
    ahead = (weekday - local.weekday()) % 7
    for extra in (0, 7):
        d = local.date() + timedelta(days=ahead + extra)
        if not is_trading_day(d):
            d = next_trading_day(d)
        open_utc, close_utc = _regular_bounds(d)
        at = close_utc if which == "close" else open_utc
        if at > now:
            return round((at - now).total_seconds() / 3600.0, 2)
    return None


def find_equity(text: str) -> re.Match[str] | None:
    """The account-size phrase in a message, as a match with number and scale in groups 1 and 2."""
    got = _EQUITY.search(text)
    if got:
        return got
    for m in _HAVE.finditer(text):
        if m.group(2) or float(m.group(1).replace(",", "") or 0) >= 100:
            return m
    return None


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


def describe_book(positions: Any, lang: str = "en") -> str:  # noqa: ANN401
    """"30,000 USDT NVDA and 10,000 USDT AMD short": the holdings as a trader would say them."""
    bits = []
    for t, side, n in list(positions)[:3]:
        if lang == "zh":
            bits.append(f"{float(n):,.0f} USDT 的 {t}{'空单' if side == 'short' else ''}")
        else:
            bits.append(f"{float(n):,.0f} USDT {t}{' short' if side == 'short' else ''}")
    more = len(positions) - 3
    if more > 0:
        bits.append(f"{more} more" if lang != "zh" else f"另外 {more} 笔")
    if len(bits) < 2:
        return "".join(bits)
    return ("、" if lang == "zh" else ", ").join(bits[:-1]) + (" 和 " if lang == "zh" else " and ") + bits[-1]


def _settle(out: RuleIntent) -> RuleIntent:
    out.missing_fields = [n for n, v in (("ticker", out.ticker), ("side", out.side), ("notional_quote", out.notional_quote)) if not v]
    if out.missing_fields:
        out.kind = "clarify"
        example = ' For example: "long 25k TSLA overnight, stop 340".' if len(out.missing_fields) == 3 else ""
        # Say back what landed, so an answer to half the question is seen to have counted.
        have = [x for x in (out.ticker, out.side, f"{out.notional_quote:,.0f} USDT" if out.notional_quote else None) if x]
        head = f"Got {', '.join(have)}. " if have else ""
        if len(out.missing_fields) == 1:
            hint = {"side": ' (just say "long" or "short")', "notional_quote": ' (e.g. "25k")', "ticker": ' (e.g. "TSLA")'}
            out.reply = f"{head}Still need {ASKS[out.missing_fields[0]]}{hint[out.missing_fields[0]]}."
        else:
            out.reply = head + "I need " + ", ".join(ASKS[m] for m in out.missing_fields) + "." + example
    else:
        out.kind = "analyze"
        out.reply = f"Running {out.side} {out.notional_quote:,.0f} USDT in {out.ticker}."
        if out.open_positions:
            out.reply = out.reply[:-1] + f", with {describe_book(out.open_positions)} already in the book."
        if out.notes:
            out.reply += " " + " ".join(out.notes)
    return out


# "-5000": a size cannot be negative. The dash must touch the number, so "TSLA - 5000" (a
# separator) and "stop -3%" (not a size) are left alone.
_NEG_SIZE = re.compile(r"(?<![\w.%])[-−]\$?(\d[\d,]*(?:\.\d+)?)\s*([kmbw])?(?![\w%])", re.I)
_LEVEL_WORD = re.compile(r"(?:stop|target|tp|止损|止盈|目标)\W*$", re.I)
# The longest hold the history can speak to: past it the window runs out of data.
MAX_HOLD_HOURS = 720.0

NEGATIVE_SIZE_REPLY = {
    "en": 'A position size cannot be negative. Tell me the size as a positive amount (e.g. "5k") and the side as long or short.',
    "zh": "仓位大小不能是负数。请用正数告诉我仓位（例如“5千U”），并用“做多”或“做空”说明方向。",
}


def _sanitize(out: RuleIntent, text: str, zh: bool) -> None:
    """Values that cannot be what the trader meant are dropped or capped, and said so."""
    if out.stop_price is not None and out.stop_price <= 0:
        out.stop_price = None
        out.notes.append("止损价为 0 不是有效价格，已忽略这个止损。" if zh else "A stop at 0 is not a price, so I ignored the stop.")
    if out.stop_pct is not None and out.stop_pct <= 0:
        out.stop_pct = out.stop_dir = None
        out.notes.append("止损距离为 0 无效，已忽略这个止损。" if zh else "A stop 0% away is not a stop, so I ignored it.")
    lev = _LEVERAGE.search(text)
    raw = float(lev.group(1) or lev.group(2)) if lev else None
    if _CJK.search(text):
        from nightwatch.api import intake_zh

        zlev = intake_zh._LEVERAGE.search(text)
        if zlev:
            raw = intake_zh.chinese_number(zlev.group(1)) if zlev.group(1) else float(zlev.group(2))
    if raw is not None and raw < 1:
        out.leverage = None
        out.notes.append(f"杠杆 {raw:g} 倍低于 1 倍，按不加杠杆处理。" if zh else f"Leverage of {raw:g}x is below 1x, so I treated it as no leverage.")
    if out.horizon_hours is not None and out.horizon_hours > MAX_HOLD_HOURS:
        was = out.horizon_hours
        out.horizon_hours = MAX_HOLD_HOURS
        out.notes.append(f"持有 {was:,.0f} 小时超出历史数据能覆盖的范围，已按 30 天（720 小时）计算。" if zh
                         else f"A hold of {was:,.0f} hours is longer than the history can speak to, so I capped it at 30 days (720 hours).")


def parse_message(text: str, known_tickers: list[str], account_equity: float | None = None) -> RuleIntent:
    """Read one message into a ticket. Nothing is invented; what is absent is asked for."""
    out = RuleIntent()
    # Full-width digits and letters ("２万Ｕ", "％") read like their ordinary forms.
    text = unicodedata.normalize("NFKC", text)
    # What is already held is read first and blanked out, so it cannot be mistaken for the trade.
    held: list[tuple[str, str, float]] = []
    if _CJK.search(text):
        from nightwatch.api import intake_zh

        held, text = intake_zh.read_positions(text, {t.upper() for t in known_tickers})
    more, text = read_positions(text, known_tickers)
    out.open_positions = merge_positions(held, more)
    neg = next((m for m in _NEG_SIZE.finditer(text) if not _LEVEL_WORD.search(text[: m.start()])), None)
    if neg:
        out.negative_size = True
        text = text[: neg.start()] + " " * (neg.end() - neg.start()) + text[neg.end():]
    out.ticker = _find_ticker(text, known_tickers)

    short, long_ = _SHORT.search(text), _LONG.search(text)
    if short and (not long_ or short.start() < long_.start()):
        out.side = "short"
    elif long_:
        out.side = "long"

    stop_pct = _STOP_PCT.search(text)
    stop = None if stop_pct else _STOP.search(text)
    target, equity = _TARGET.search(text), find_equity(text)
    out.stop_price = float(stop.group(1).replace(",", "")) if stop else None
    if stop_pct:
        out.stop_pct = float(stop_pct.group(1) or stop_pct.group(3))
        word = (stop_pct.group(2) or "").lower()
        out.stop_dir = "above" if word in ("above", "over") else "below" if word in ("below", "under") else None
        stop = stop_pct  # its span is spent, so the percentage is never read as a size
    out.target_price = float(target.group(1).replace(",", "")) if target else None
    if equity:
        scale = _SCALE[equity.group(2).lower()] if equity.group(2) else 1.0
        out.account_equity_quote = float(equity.group(1).replace(",", "")) * scale
    elif account_equity:
        out.account_equity_quote = account_equity

    # Size is the money left over once the labelled numbers are accounted for.
    lev = _LEVERAGE.search(text)
    margin = _MARGIN.search(text) if lev else None
    spent = [m.span() for m in (stop, target, equity, lev, margin) if m]  # "100x" is not a size
    for m in _MONEY.finditer(text):
        if any(s <= m.start() < e for s, e in spent):
            continue
        if (m.group(4) or "").lower() == "w" and re.search(r"\b(?:for|hold|over|next|in|within)\s*$", text[: m.start()], re.I):
            continue  # "for 2w" is a duration
        value = _money(m.groups())
        if value is not None and value != out.account_equity_quote:
            out.notional_quote = value
            break
    # A bare number is read as a size only in English. In a Chinese message a size carries
    # 万/千/U/美元, and a bare "340" is a price - "如果收盘跌破 340 就算错" became a 340 USDT trade.
    if out.notional_quote is None and not _CJK.search(text):
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
    day = _WEEKDAY.search(text)
    if day and (h := hours_until_weekday(_DAY_INDEX[day.group(1).lower()], (day.group(2) or "open").lower())):
        out.horizon_kind, out.horizon_hours = "hours", h
    elif _WEEKEND.search(text):
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

    if lev:
        value = float(lev.group(1) or lev.group(2))
        out.leverage = value if value >= 1 else None
        if margin and out.leverage:
            # The trader named the margin: the position is the margin times the leverage.
            amount, scale = (margin.group(1), margin.group(2)) if margin.group(1) else (margin.group(3), margin.group(4))
            put_up = float(amount.replace(",", "")) * (_SCALE[scale.lower()] if scale else 1.0)
            out.notional_quote = put_up * out.leverage

    pct = _HEDGE_PCT.search(text)
    if pct:
        out.hedge_ratio = min(1.0, float(pct.group(1)) / 100.0)
    elif _HEDGE.search(text):
        out.hedge_ratio = 0.5 if re.search(r"\bhalf\b", text, re.I) else 1.0

    thesis, invalid = _THESIS.search(text), _INVALID.search(text)
    out.thesis = thesis.group(1).strip() if thesis else None
    out.invalidation = invalid.group(1).strip() if invalid else None
    if _CJK.search(text):
        # A Chinese message: read it with the Chinese rules, filling only what the
        # English rules did not find (a ticker written as TSLA reads the same either way).
        from nightwatch.api import intake_zh

        # The Chinese reader knows 账户, 理由 and where the invalidation ends; where it read a
        # size, an account, a reason or an invalidation, its reading wins over the English one.
        zh_wins = ("notional_quote", "account_equity_quote", "thesis", "invalidation")
        for key, value in intake_zh.read(text, {t.upper() for t in known_tickers}).items():
            if getattr(out, key) in (None, "") or (key in zh_wins and value not in (None, "")):
                setattr(out, key, value)
    _sanitize(out, text, bool(_CJK.search(text)))
    if out.negative_size and out.notional_quote:
        out.negative_size = False  # another amount in the message is the size; the negative one is dropped
    _settle(out)
    if out.negative_size and "notional_quote" in out.missing_fields:
        out.reply = NEGATIVE_SIZE_REPLY["zh" if _CJK.search(text) else "en"]
    return out


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
        # A stop is either a price or a distance; the later message replaces either kind.
        if latest.stop_price is not None:
            merged.stop_pct = merged.stop_dir = None
        elif latest.stop_pct is not None:
            merged.stop_price = None
        if latest.ticker and merged.ticker and latest.ticker.upper() != merged.ticker.upper():
            # A stop, a target or a price-based invalidation belongs to the stock it was
            # given for. Carried over when the trader switches to another one, a TSLA stop
            # at 350 became an NVDA stop 56% away that "40 of 40 past moments hit".
            merged.stop_price = merged.target_price = merged.invalidation = None
            merged.stop_pct = merged.stop_dir = None
        merged.open_positions = merge_positions(merged.open_positions, latest.open_positions)
        for key, value in latest.as_dict().items():
            if key in ("kind", "reply", "missing_fields", "open_positions", "notes") or value in (None, [], ""):
                continue
            setattr(merged, key, value)
        merged.notes, merged.negative_size = latest.notes, latest.negative_size
    if merged.account_equity_quote is None and account_equity:
        merged.account_equity_quote = account_equity
    return _settle(merged)


def stop_offset(pct: float | None, direction: str | None, side: str | None) -> float | None:
    """A stop distance as a signed offset from entry, in percent. Unsaid, the direction is
    the losing one: below entry for a long, above it for a short."""
    if pct is None or not 0 < pct < 100:
        return None
    if direction == "above":
        return pct
    if direction == "below":
        return -pct
    return pct if side == "short" else -pct


def intent_to_ticket(p: RuleIntent, account_equity: float | None) -> TradeTicket:
    kind, hours, label = horizon_fields(p.horizon_kind, p.horizon_hours)
    return TradeTicket(
        ticker=(p.ticker or "").upper(), side=Side(p.side or "long"), notional_quote=float(p.notional_quote or 0.0),
        account_equity_quote=p.account_equity_quote or account_equity, horizon_kind=kind, horizon_hours=hours,
        stop_price=p.stop_price, target_price=p.target_price, thesis=p.thesis or "", invalidation=p.invalidation or "",
        stop_offset_pct=None if p.stop_price is not None else stop_offset(p.stop_pct, p.stop_dir, p.side),
        hedge_ratio=p.hedge_ratio, leverage=p.leverage if p.leverage and p.leverage <= 125 else None,
        open_positions=tuple((t.upper(), side, float(n)) for t, side, n in p.open_positions),
        extra={"horizon_label": label} if label else {},
    )


def _pct(v: float, digits: int = 1) -> str:
    """A signed percentage whose sign comes from the rounded value: a median of -0.04%
    rounds to zero, and "-0.0%" reads as a loss that is not there."""
    text = f"{abs(v):.{digits}f}%"
    sign = "+" if round(v, digits) > 0 else "-" if round(v, digits) < 0 else ""
    return sign + text


# Failure-mode names in Chinese; the mechanism sentences stay in the English report.
FAILURE_ZH = {
    "gap_bad": "开盘跳空（二十分之一的情形）", "gap_worst": "开盘严重跳空（百分之一的情形）", "earnings": "财报后不利跳空",
    "basis": "代币偏离公允价值", "liquidity": "平仓时盘口变薄", "halt": "24 小时无法平仓", "vol": "波动率骤升",
    "stop_jumped": "止损被跳空越过", "liquidation": "被强制平仓", "drift": "价格缓慢走弱", "replay": "历史危机重演",
    "invalidation": "你自己设定的止错线被突破", "convergence": "代币价格回归正股",
}

# The verdict names in Chinese, for a trader who wrote in Chinese. The numbers are the
# same numbers, formatted the same way; only the words around them change.
VERDICT_ZH = {"GO": "可以做", "REDUCE": "建议减仓", "REDUCE_TO": "建议减仓", "HEDGE": "建议对冲", "REVIEW": "需要复核", "NO_GO": "不建议做"}
CAP_ZH = {"risk_budget": "风险预算", "concentration": "集中度", "regime": "市场状态", "exit_liquidity": "平仓流动性", "stress": "压力测试", "breaker": "熔断", "book_tail": "整体持仓尾部风险"}
RULE_ZH = {
    "written_plan": "书面计划", "stop": "止损", "position_size": "仓位大小", "market_posture": "市场状态",
    "liquidity": "流动性", "circuit_breaker": "熔断", "basis": "价差", "event": "事件", "data_quality": "数据质量",
    "liquidation": "强平风险", "exit_liquidity": "平仓流动性", "revenge": "报复性交易冷静期", "concentration": "集中度", "risk_budget": "风险预算", "book_tail": "整体持仓风险",
}


def preset_zh(sid: str, name: str) -> str:
    """A stress preset's name in Chinese, from its id; the English name when unknown."""
    import re as _re

    if (m := _re.fullmatch(r"closed_window_gap_p(\d+)", sid)):
        return f"休市期间跳空（第 {m.group(1)} 百分位）"
    if (m := _re.fullmatch(r"basis_blowout_p(\d+)", sid)):
        return f"代币偏离公允价值（休市时段第 {m.group(1)} 百分位）"
    if sid.startswith("replay_"):
        return "历史危机重演：" + {"covid_2020": "2020 年新冠暴跌", "banks_2023": "2023 年 3 月银行危机", "rates_2022": "2022 年通胀冲击",
                               "carry_2024": "2024 年 8 月套息交易平仓", "tariffs_2025": "2025 年 4 月关税冲击"}.get(sid[7:], name)
    if (m := _re.fullmatch(r"vol_spike_x(\d+)", sid)):
        return f"波动率骤升 ×{m.group(1)}"
    return {
        "earnings_gap_worst": "财报跳空：历史最差", "earnings_gap_typical": "财报跳空：典型不利",
        "liquidity_drought": "流动性枯竭（盘口深度 ÷5）", "exchange_halt_24h": "24 小时无法平仓",
        "funding_spike": "对冲腿资金费率飙升",
    }.get(sid, name)
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


# How a trader asks to narrow the comparison, in either language the desk answers in.
_NARROW = re.compile(r"\bonly\b|\bjust\b|\bexcept\b|\bexclud\w*\b|\bcompare\b|只|仅|对比|除了", re.I)


def asks_to_narrow(text: str) -> bool:
    """Whether the message asks to compare against only some past moments.

    Describing the situation is not asking for a filter: "hold TSLA over the weekend"
    says when, not "compare only against weekends". The model is told the same, and
    this is the check that holds it to it.
    """
    return bool(_NARROW.search(text or ""))


def needs_the_model(text: str) -> bool:
    """Whether a message has something in it the rules cannot read.

    The rules read the shapes traders type - "long 20k TSLA overnight, stop 350" - and
    they read them in milliseconds. The model reads anything, in 10-60 s. So the model is
    asked only when there is something only it can do: a request to narrow which past
    moments count, which the rules have no vocabulary for. Anything the rules cannot
    complete - in English or Chinese - goes to the model anyway.
    """
    low = (text or "").lower()
    # Condition phrases alone are not enough: "long 20k TSLA overnight" names a night
    # without asking to be compared only against nights. People asking to narrow say so.
    if asks_to_narrow(low):
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


_DAY_ZH = {"Monday": "周一", "Tuesday": "周二", "Wednesday": "周三", "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日"}


def weekend_line(report: Any, lang: str) -> str | None:
    """Which weekend was answered, when "over the weekend" was asked early in the week.

    Holding from a Tuesday to Monday's open is a six-day trade, longer than any hold the
    desk has scored, and a judge reading "weekend: 152h" took it for broken clock maths.
    Say what was measured, then give the answer the trader most likely meant - buying on
    Friday - from what past weekends did, plainly marked as raw history.
    """
    w = getattr(report, "weekend_only", None)
    if not w:
        return None
    days = w["hold_from_now_h"] / 24.0
    if lang == "zh":
        return (
            f"说明：今天是{_DAY_ZH.get(w['today'], w['today'])}，从现在持有到周末后的周一开盘是 {days:.1f} 天，比我们评分过的任何持有期都长。"
            f"如果你是打算周五买、周一卖：{report.ticket.ticker} 过去 {w['n']} 个周末（周五收盘到周一开盘），大约每二十个周末有一个亏损超过 {-w['p5_pct']:.1f}%，"
            f"最差 {w['worst_pct']:+.1f}%（未经校准的原始历史）。周五再问我一次，可以得到那个周末的完整检查。"
        )
    return (
        f"Note: today is {w['today']}, so holding from now through the weekend is {days:.1f} days, to Monday's open - longer than any hold we have scored. "
        f"If you mean buying on Friday and selling on Monday: over {report.ticket.ticker}'s last {w['n']} weekends, Friday's close to Monday's open, "
        f"1 in 20 lost more than {-w['p5_pct']:.1f}% and the worst was {w['worst_pct']:+.1f}% (raw history, not calibrated). Ask again on Friday for the full check of that weekend."
    )


def _leverage_line(lev: dict[str, Any], lang: str) -> str:
    """Where the exchange closes a leveraged position, and how often history got there."""
    zh = lang == "zh"
    x = f"{lev['leverage']:g}"
    if lev.get("perp_symbol") is None:
        return "该股票在 Bitget 没有永续合约，无法加杠杆；以下按现货分析。" if zh else f"{x}x: Bitget lists no perpetual for this stock, so it cannot be held with leverage; the rest is the spot trade."
    if not lev.get("allowed", True):
        return (f"{x} 倍超过了 Bitget 在这个仓位规模下允许的 {lev['max_leverage_at_size']:g} 倍。" if zh
                else f"{x}x is more than the {lev['max_leverage_at_size']:g}x Bitget allows at this size.")
    d, price = lev.get("liquidation_distance_pct"), lev.get("liquidation_price")
    if d is None or price is None:
        return "杠杆已记录，但没有入场价，无法计算强平价。" if zh else f"{x}x noted, but with no entry price the liquidation level is unknown."
    hits, of = lev.get("analog_hits"), lev.get("analog_of")
    mc = lev.get("mc_share")
    presets = lev.get("presets_hit") or []
    if zh:
        line = f"{x} 倍杠杆：保证金约 {lev['margin_quote']:,.0f} USDT，约在 {price:,.2f} 强平（距现价 {d:.1f}%）。"
        if of:
            line += f"过去 {of} 个相似时刻里有 {hits} 个会在持有期内触及强平"
            line += f"；模拟路径中约 {mc:.0%} 会触及。" if mc is not None else "。"
        if presets:
            line += f"有 {len(presets)} 个压力情景会导致强平。"
        return line
    line = f"{x}x leverage: about {lev['margin_quote']:,.0f} USDT of margin, liquidated near {price:,.2f} ({d:.1f}% away)."
    if of:
        line += f" {hits} of {of} past moments like this would have reached it inside the hold"
        line += f", and {mc:.0%} of simulated paths do." if mc is not None else "."
    if presets:
        line += f" Stress presets that liquidate it: {'; '.join(presets[:3])}{'...' if len(presets) > 3 else ''}."
    if lev.get("tiers_source") == "assumed":
        line += f" (Bitget's margin tiers were unavailable; {lev['mmr']:.1%} maintenance margin assumed.)"
    return line


def book_line(report: Any, lang: str = "en") -> str | None:  # noqa: ANN401
    """What the trader already holds, and what this trade does to the whole book.

    Every figure is copied from the report's portfolio section, which is measured on one
    shared set of historical windows for the holdings and the trade together.
    """
    t, port = report.ticket, getattr(report, "portfolio", None)
    if not t.open_positions or port is None:
        return None
    zh = lang == "zh"
    held = describe_book(t.open_positions, lang)
    before, after = port.before.tail_loss_quote, port.after.tail_loss_quote
    bits: list[str] = []
    if before is None or after is None:
        bits.append(f"你已有 {held}，但缺少足够的历史来衡量整个持仓的风险，所以没有计入尾部风险。" if zh
                    else f"With your {held}: there is not enough stored history to measure the whole book, so no book limit was applied.")
    else:
        delta = after - before
        verb = ("增加" if delta < 0 else "减少") if zh else ("adds" if delta < 0 else "removes")
        if zh:
            bits.append(f"你已有 {held}：整个持仓的二十分之一亏损从 {abs(before):,.0f} USDT 变为 {abs(after):,.0f} USDT（这笔交易{verb} {abs(delta):,.0f}）。")
        else:
            bits.append(f"With your {held}: your book's one-in-twenty loss goes from {abs(before):,.0f} to {abs(after):,.0f} USDT with this trade at the size you asked ({verb} {abs(delta):,.0f}).")
        rec = report.verdict.recommended_notional
        if port.book_cap_binds and port.book_cap_quote is not None:
            tail_rec = port.tail_after_recommended_quote
            pct = port.book_cap_pct_of_equity
            if zh:
                bits.append(f"整体持仓上限把这笔交易限制在 {port.book_cap_quote:,.0f} USDT（持仓尾部亏损不超过账户的 {pct:g}%）。")
            else:
                tail_txt = f", which leaves the book at {abs(tail_rec):,.0f}" if tail_rec is not None else ""
                bits.append(f"The book cap holds it to {port.book_cap_quote:,.0f} USDT ({pct:g}% of equity for the whole book){tail_txt}.")
        elif rec is not None and abs(rec - t.notional_quote) > 1 and port.tail_after_recommended_quote is not None:
            bits.append(f"按建议的 {rec:,.0f} USDT，整个持仓的二十分之一亏损为 {abs(port.tail_after_recommended_quote):,.0f} USDT。" if zh
                        else f"At the recommended {rec:,.0f} it is {abs(port.tail_after_recommended_quote):,.0f}.")
    same = port.same_name
    if same:
        bits.append(f"你已持有 {abs(same['held_signed_quote']):,.0f} USDT 的 {same['ticker']}，加上这笔后该股共 {abs(same['combined_signed_quote']):,.0f} USDT。" if zh
                    else f"You already hold {abs(same['held_signed_quote']):,.0f} of {same['ticker']}, so with this trade that name is {abs(same['combined_signed_quote']):,.0f}.")
    if port.unknown:
        names = ", ".join(port.unknown)
        bits.append(f"{names} 没有足够的历史数据，未计入尾部风险。" if zh else f"No stored history for {names}, so it is left out of the tail (not counted as zero).")
    extra = _book_stress_line(port, zh)
    if extra:
        bits.append(extra)
    return "".join(bits) if zh else " ".join(bits)


_LEVER_ZH = {"smaller_trade": "把新仓缩小到", "skip_trade": "不做这笔", "trim_holding": "减仓", "hedge_perp": "用永续对冲"}


def _book_stress_line(port: Any, zh: bool) -> str:  # noqa: ANN401
    """The book through its worst crash week and, on a breach, the first plan that gets it back inside."""
    st = getattr(port, "stress", None)
    if st is None:
        return ""
    bits: list[str] = []
    crash = min((c for c in st.crashes if c.asked_quote is not None), key=lambda c: c.asked_quote, default=None)
    if crash is not None:
        bits.append(f"整个持仓在最坏的一次历史冲击（{crash.name}）里会亏 {abs(crash.asked_quote):,.0f} USDT。" if zh
                    else f"In its worst crash replay ({crash.name}) the whole book would have lost {abs(crash.asked_quote):,.0f} USDT.")
    plan = next((p for p in st.plans if p.achieves_limit), None)
    if st.breached and plan is not None:
        if zh:
            bits.append(f"超出组合上限。可行的调整：{_LEVER_ZH.get(plan.lever, plan.lever)} {plan.ticker}（{plan.amount_quote:,.0f} USDT），"
                        f"二十分之一亏损降到 {abs(plan.after.tail_quote):,.0f} USDT。")
        else:
            bits.append(f"That is past the book limit. One fix that gets back inside it: {plan.detail}, which takes the one-in-twenty loss from {abs(plan.before.tail_quote):,.0f} to {abs(plan.after.tail_quote):,.0f}.")
    return "".join(bits) if zh else " ".join(bits)


def _at_rec(m: dict, zh: bool = False) -> str:
    """The loss at the recommended size, when the report recommends a smaller one."""
    q = m.get("loss_quote_at_recommended")
    if q is None:
        return ""
    return f"（按建议仓位：约 {abs(q):,.0f} USDT）" if zh else f" (at the recommended size: about {abs(q):,.0f} USDT)"


def _needs_account_head(report: Any, head: str, zh: bool) -> str:  # noqa: ANN401
    """A REVIEW that is only waiting for the account size, as one plain sentence: what to do,
    and why, with the loss at the size asked and what the live book supports. The verdict and
    the numbers are the report's; only the wording of the first line changes."""
    v, t = report.verdict, report.ticket
    if v.verdict.value != "REVIEW" or t.account_equity_quote:
        return head
    horizon = report.analog.horizons.get(report.primary_horizon) if report.analog else None
    p5 = horizon.loss_p5_pct if horizon is not None else None
    if p5 is None or p5 >= 0:
        return head
    bad = abs(p5) / 100.0 * t.notional_quote
    book = v.recommended_notional if v.recommended_notional is not None and 1 <= v.recommended_notional < t.notional_quote - 1 else None
    stop = "" if t.stop_price or t.stop_offset_pct else ("（有止损的话也请加上）" if zh else " (and add a stop if you can)")
    if zh:
        tail = f"，而当前盘口只能承接 {book:,.0f} USDT" if book is not None else ""
        return f"需复核（REVIEW）：请告诉系统你的账户规模{stop}，才能完成检查。按 {t.notional_quote:,.0f} USDT 计，二十分之一的坏夜晚约亏 {bad:,.0f} USDT{tail}。"
    tail = f", and the live order book supports only {book:,.0f} USDT" if book is not None else ""
    return (f"REVIEW: tell the desk your account size{stop} to finish the checks. At {t.notional_quote:,.0f} USDT a bad night, one in twenty, "
            f"loses about {bad:,.0f} USDT{tail}.")


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
        head = f"{v.verdict.value.replace('_', ' ')} on {side} {t.notional_quote:,.0f} USDT of {t.ticker}, {_horizon_phrase(report, lang)}."
    if v.recommended_notional is not None and v.recommended_notional < 1:
        # "Size it at 0 instead" read as a contradiction next to a REVIEW. What it means is
        # that no size clears a limit, so say which one.
        priced_caps = [c for c in v.caps if c.notional is not None]
        binding = min(priced_caps, key=lambda c: c.notional) if priced_caps else None
        if binding is not None and binding.name == "exit_liquidity":
            head += " 以目前的盘口，任何仓位的平仓成本都超过预算，现在不宜开仓。" if zh else " No size gets out within the exit-cost budget on the book right now, so there is nothing to size."
        else:
            head += " 目前没有任何仓位能通过限制。" if zh else " No size passes the limits right now."
    elif v.recommended_notional is not None and abs(v.recommended_notional - t.notional_quote) > 1:
        head += f" 建议仓位改为 {v.recommended_notional:,.0f}。" if zh else f" Size it at {v.recommended_notional:,.0f} instead."
    head = _needs_account_head(report, head, zh)
    if v.hedge_ratio:
        head += f" 用永续合约对冲 {v.hedge_ratio:.0%}。" if zh else f" Hedge {v.hedge_ratio:.0%} with the perp."
    lines.append(head)
    bk = book_line(report, lang)
    if bk:
        lines.append(bk)
    wk = weekend_line(report, lang)
    if wk:
        lines.append(wk)

    analog = report.analog
    horizon = analog.horizons.get(report.primary_horizon) if analog else None
    if horizon is not None and horizon.cohort.n:
        c = horizon.cohort
        # The position's own outcome: a short gains what the token loses.
        p5, median = horizon.loss_p5_pct, horizon.pnl_median_pct
        short = t.side == Side.SHORT
        raw = (-c.p95 if c.p95 is not None else None) if short else c.p5
        adjusted = horizon.p95_adjusted if short else horizon.p5_adjusted
        if p5 is not None and median is not None:
            if zh:
                line = f"历史：找到 {c.n} 个与现在相似的时刻；这笔仓位的中位结果 {_pct(median)}，最差的二十分之一低于 {_pct(p5)}。"
                if short:
                    line += "（做空时，坏情况是股价上涨。）"
            else:
                line = f"History: {c.n} past moments like this one; for this position the middle outcome was {_pct(median)} and one in twenty was worse than {_pct(p5)}."
                if short:
                    line += " For a short, the bad case is the stock rising."
                adj = horizon.adjustment or {}
                if adj.get("uncalibrated"):
                    line += " That is the raw history: no forecast held this long has been scored, so it is not calibrated."
                elif raw is not None and adjusted is not None and abs(raw - p5) >= 1.0:
                    line += f" (The raw count of these moments said {_pct(raw)}; adjusted by how past calls of this length actually came out.)"
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

    lev = getattr(report, "leverage", None)
    if lev:
        lines.append(_leverage_line(lev, lang))

    plan = getattr(report, "plan_check", None)
    if plan:
        from nightwatch.decision.plan_check import PlanCheck
        from nightwatch.decision.plan_check import describe as describe_plan

        said = describe_plan(PlanCheck(**plan), lang)
        if said:
            lines.append(said)

    priced = [i for i in report.stress.impacts if i.total_pnl_quote is not None]
    lev_view = getattr(report, "leverage", None) or {}
    margin = lev_view.get("margin_quote") if lev_view.get("liquidation_distance_pct") is not None else None
    lev_x = lev_view.get("leverage") or 1.0
    if priced:
        worst = min(priced, key=lambda i: i.total_pnl_quote)
        name = next((s.name for s in report.stress.presets if s.id == worst.scenario_id), worst.scenario_id)
        if zh:
            line = f"最坏压力情景（{preset_zh(worst.scenario_id, name)}）：仓位 {_pct(worst.total_pct_of_notional)}，约 {worst.total_pnl_quote:,.0f} USDT。"
            if margin and worst.total_pnl_quote < -margin:
                line += f"但 {lev_x:g} 倍杠杆会先被强平，亏损止于 {margin:,.0f} USDT 保证金。"
            lines.append(line)
        else:
            line = f"Worst stress preset ({name}): {_pct(worst.total_pct_of_notional)} of the position, about {worst.total_pnl_quote:,.0f} USDT."
            if margin and worst.total_pnl_quote < -margin:
                line += f" At {lev_x:g}x the exchange liquidates first, so the loss stops at the {margin:,.0f} USDT margin."
            lines.append(line)
    mc = report.stress.monte_carlo
    if mc is not None:
        if zh:
            lines.append(f"模拟尾部：二十条路径中最差的一条收在 {_pct(mc.p5)} 以下，同一分位的最大回撤超过 {_pct(mc.drawdown_p5)}。")
        else:
            lines.append(f"Simulated tail: one path in twenty ends below {_pct(mc.p5)}, and the worst drawdown is past {_pct(mc.drawdown_p5)} in the same fifth percentile.")

    q = report.execution.exit_quote
    if q is not None and not q.fully_filled and q.total_cost_bps is not None:
        # The book takes part of the size. Printing the cost of that part as "getting out
        # costs" sat beside "cannot absorb this size" and read as a contradiction.
        cost = f" the part that fills costs about {q.total_cost_bps:.0f} bps," if q.total_cost_bps is not None else ""
        lines.append("平仓：盘口只能吃下这个仓位的一部分，其余目前在任何价格都无法卖出。" if zh
                     else f"Getting out: the book takes only part of this size;{cost} the rest cannot be sold at any price right now.")
    elif q is not None and q.total_cost_bps is not None and q.total_cost_quote is not None:
        if zh:
            lines.append(f"平仓成本：按{'实时' if report.execution.book_source == 'live' else '记录的'}盘口约 {q.total_cost_bps:.0f} bps，约 {q.total_cost_quote:,.0f} USDT。")
        else:
            lines.append(f"Getting out costs {q.total_cost_bps:.0f} bps on the {report.execution.book_source} book, about {q.total_cost_quote:,.0f} USDT.")
    elif q is not None:
        # The book cannot take this size at any price. That is the most important thing
        # the exit line can say, and it used to crash the reply instead.
        lines.append("平仓：以目前的盘口，这个仓位无法在任何价格全部平掉。" if zh else "Getting out: the order book cannot absorb this size at any price right now.")

    street = getattr(report, "street", None)
    if street and street.get("token_vs_live_bps") is not None:
        live = street["token_vs_live_bps"]
        if zh:
            lines.append(f"此刻：代币价格与正股的实时价格相差 {live:+.0f} bps（Bitget 数据）。")
        else:
            lines.append(f"Right now the token sits {live:+.0f} bps from the stock's live price (Bitget data).")

    sig = getattr(report, "signal", None)
    if sig and sig.get("agrees"):
        if zh:
            word = {"oversold": "超卖", "overbought": "超买"}.get(sig["reading"], "中性")
            lines.append(f"Bitget 信号技能：{sig['timeframe']} RSI {sig['rsi']:.1f}（{word}）；我们用 Bitget K 线自算 {sig['own_rsi']:.1f}，一致。仅供参考。")
        else:
            lines.append(f"Bitget signal skill: RSI {sig['rsi']:.1f} on {sig['timeframe']} ({sig['reading']}); our own from Bitget candles {sig['own_rsi']:.1f} - agrees. Context only.")

    capped = [c for c in v.caps if c.notional is not None]
    if capped:
        binding = min(capped, key=lambda c: c.notional)
        if binding.notional < t.notional_quote - 1:  # a cap above the request binds nothing
            if zh:
                lines.append(f"限制仓位的是{CAP_ZH.get(binding.name, binding.name.replace('_', ' '))}上限：{binding.notional:,.0f} USDT。")
            else:
                held = next((r for r in v.reasons if r.startswith("Size held at")), None)
                lines.append(held if held else f"The cap that binds is {binding.name.replace('_', ' ')}: {binding.detail}.")

    # A review that only wants the trader's own words is something they can clear in one
    # message, so say how rather than printing the rule's name at them.
    plan_missing = [r for r in report.gate.rules if r.rule == "written_plan" and r.decision.value != "GO"]
    reasons = [r for r in v.reasons if not r.startswith("written plan") and not r.startswith("Size held at")]
    if zh:
        # The gate's reasons are written in English; name the checks that did not pass
        # instead, which is the part a reader needs, rather than mix languages.
        failed = [RULE_ZH.get(r.rule, r.rule.replace("_", " ")) for r in report.gate.rules if r.decision.value != "GO" and r.rule != "written_plan"]
        if failed:
            lines.append("未通过的检查：" + "、".join(failed) + "。")
    elif reasons:
        lines.append("Why: " + "; ".join(reasons[:3]) + ".")
    premise = getattr(report, "premise", None) or []
    if premise and not zh:
        lines.append("Check your plan: " + " ".join(premise))
    modes = getattr(report, "failure_modes", None) or []
    if modes and not zh:
        top = [m for m in modes if m.get("loss_quote") is not None][:2]
        if top:
            lines.append("How this loses money: " + " ".join(
                f"{m['title']} ({m.get('short') or m['mechanism']}): about {m['loss_quote']:,.0f} USDT{_at_rec(m)}; {m['likelihood']}."
                for m in top
            ))
    elif modes and zh:
        top = [m for m in modes if m.get("loss_quote") is not None][:2]
        if top:
            lines.append("主要亏损方式：" + "；".join(f"{FAILURE_ZH.get(m['key'], m['title'])}，约 {m['loss_quote']:,.0f} USDT{_at_rec(m, True)}" for m in top) + "。")
    if report.second_opinion and report.second_opinion.against:
        against = report.second_opinion.against[0].text
        # Often the case against is the worst stress preset again, already said above; and
        # its text is English, which a Chinese reader has just been spared everywhere else.
        repeats = bool(priced) and against.startswith(name)
        if not repeats and not zh:
            lines.append("Case against: " + against)
    equity_missing = getattr(report.ticket, "account_equity_quote", None) is None and any(r.rule == "position_size" and r.decision.value != "GO" for r in report.gate.rules)
    if equity_missing:
        if zh:
            lines.append("要给出明确结论，请告诉我你的账户规模——例如“账户 20万U”——我会据此判断仓位是否过大。")
        else:
            lines.append("For a firm GO or NO-GO, tell me your account size - e.g. \"account 200k\" - so I can check this position against it.")
    if plan_missing:
        if zh:
            lines.append("要通过复核：告诉我你为什么做这笔交易，以及什么情况说明你错了——例如“因为……，如果收盘跌破……就算错”——我会重新检查。")
        else:
            lines.append("To clear the review, tell me why you want this trade and what would prove it wrong - e.g. \"because ..., wrong if it closes below ...\" - and I'll re-check it.")
    return "\n\n".join(lines)


_SHORT_KEEP_EN = ("Why:", "Check your plan:", "History:", "For a firm GO", "To clear the review")
_SHORT_KEEP_ZH = ("未通过的检查", "历史：", "要给出明确结论", "要通过复核")


def brief_short(report: Any, lang: str = "en") -> str:
    """The first reply in chat: the answer and the one thing that matters, then an offer.

    The full briefing ran to ten paragraphs and a judge called it a wall of text. The chat
    now leads with the verdict and size, why when it is not a go, leverage, the plan check,
    the single most likely-and-costly way the trade loses, the history in one line and
    anything the trader still has to say - and invites the follow-ups that open the rest.
    Every line is one the full briefing prints; the page below still shows everything.
    """
    zh = lang == "zh"
    full = brief(report, lang).split("\n\n")
    keep = _SHORT_KEEP_ZH if zh else _SHORT_KEEP_EN
    out = [full[0]]
    bk = book_line(report, lang)
    if bk:
        out.append(bk)
    wk = weekend_line(report, lang)
    if wk:
        out.append(wk)
    note = getattr(report.execution, "book_note", None)
    if note:
        out.append("注意：盘口此刻异常宽，仓位上限按过去两小时的正常盘口计算；现在进出成本更高，可以等一等或用限价单。" if zh
                   else "Heads-up: " + note[0].upper() + note[1:] + ".")
    lev = getattr(report, "leverage", None)
    if lev:
        out.append(_leverage_line(lev, lang))
    modes = [m for m in (getattr(report, "failure_modes", None) or []) if m.get("loss_quote") is not None]
    picked = {p: next((x for x in full[1:] if x.startswith(p)), None) for p in keep}
    for p in keep[:2] if not zh else keep[:1]:
        if picked.get(p):
            out.append(picked[p])
    if modes:
        m = modes[0]
        if zh:
            out.append(f"最需要注意的亏损方式：{FAILURE_ZH.get(m['key'], m['title'])}，约 {m['loss_quote']:,.0f} USDT{_at_rec(m, True)}。")
        else:
            out.append(f"The one to watch: {m['title']} ({m.get('short') or m['mechanism']}) - about {m['loss_quote']:,.0f} USDT{_at_rec(m)}; {m['likelihood']}.")
    for p in (keep[2:] if not zh else keep[1:]):
        if picked.get(p):
            out.append(picked[p])
    t = report.ticket
    lev_ask = ("不加杠杆呢？" if zh else "what about no leverage?") if t.leveraged else ("5 倍杠杆呢？" if zh else "what about 5x?")
    if zh:
        out.append(f"可以接着问我：为什么？· 如果跌 10% 呢？· 仓位减半 · {lev_ask} · {t.ticker} 周末跌 5% 的概率是多少？")
    else:
        out.append(f"Ask me: why? · what if it gaps down 10%? · halve it · {lev_ask} · how often does {t.ticker} fall 5% over a weekend?")
    return "\n\n".join(out)


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

    from nightwatch.api import desk_help
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.pipeline.render import render_text

    tickers = list(state.ctx.tickers_with_data())
    intent = read_conversation(messages, tickers, account_equity)
    latest = next((m["content"] for m in reversed(messages) if m.get("role") == "user" and (m.get("content") or "").strip()), "")
    lang = language_of(latest)
    # A token, a side and an account but no size: the desk runs the largest size it allows
    # and says so, rather than sending the trader back to type one.
    assumed = None
    got = desk_help.with_assumed_size(state, intent, tickers, account_equity, latest, lang)
    if got:
        intent, assumed = got
    result: dict[str, Any] = {
        "intent": intent.as_dict(), "ticket": None, "report": None, "narrative": None,
        "report_text": None, "unverified_numbers": [], "mode": "rules",
    }
    if assumed:
        result["size_assumed"] = assumed
    if intent.kind != "analyze":
        result["reply"] = intent.reply
        if "ticker" in intent.missing_fields and not intent.negative_size:
            # Not a dead end: say which tokens are covered.
            result["reply"] = desk_help.no_token_reply(intent, tickers, latest, lang) or f"{intent.reply} {desk_help.covered_list(tickers, lang)}"
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
                state.prefetch_take(report.forecast_id, payload, language_of(messages[-1].get("content", "") if messages else ""))
            except Exception as exc:  # noqa: BLE001 - a keepsake must not fail the turn
                log.warning("could not store the chat report: %s", exc)
    narrative = brief_short(report, lang)
    if assumed:
        narrative = assumed["note"] + "\n\n" + narrative
    result.update({
        "ticket": json.loads(json.dumps(ticket.__dict__, default=str)),
        "report": payload,
        "report_text": render_text(report),
        "narrative": narrative,
        "reply": narrative,
    })
    return result
