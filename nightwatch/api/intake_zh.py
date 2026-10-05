"""Reading a trade idea written in Chinese, without a model.

The desk answers a trader in the language they wrote in, and Chinese-speaking traders
are a large share of Bitget's users. Until now every Chinese message went to the model,
which takes about a minute to read one. Most of them are the same few shapes English
ones are - which stock, which way, how much, how long, where the stop is - and those can
be read by rules in milliseconds, exactly as the English rules do: nothing invented,
anything absent left for the model or asked for.
"""

from __future__ import annotations

import re

# How Chinese-speaking traders name these stocks.
ALIASES_ZH: dict[str, str] = {
    "特斯拉": "TSLA", "英伟达": "NVDA", "辉达": "NVDA", "苹果": "AAPL", "微软": "MSFT", "亚马逊": "AMZN",
    "谷歌": "GOOGL", "脸书": "META", "奈飞": "NFLX", "网飞": "NFLX", "帕兰提尔": "PLTR", "罗宾汉": "HOOD",
    "美光": "MU", "英特尔": "INTC", "博通": "AVGO", "阿里巴巴": "BABA", "阿里": "BABA", "超微电脑": "SMCI",
    "微策略": "MSTR", "台积电": "TSM", "纳指": "QQQ", "纳斯达克": "QQQ", "标普": "SPY", "标普500": "SPY",
    "超威": "AMD", "超微半导体": "AMD", "三倍做多纳指": "TQQQ", "三倍做空纳指": "SQQQ",
}

_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1_000, "万": 10_000}

_SHORT = re.compile(r"做空|卖空|沽空|看空|空头|开空|空单|做淡")
# "拿点特斯拉" is how a trader says "hold some Tesla": 拿 is a long unless it is 拿不准.
# A bare 空 straight before a stock ("空特斯拉5千") is a short. 清空 and 落空 are not: they
# close or miss, they do not open.
_BARE_SHORT = re.compile(r"(?<![清落腾架天])空\s*(?=" + "|".join(sorted(map(re.escape, ALIASES_ZH), key=len, reverse=True)) + r"|[A-Za-z]{2,5})")
_LONG = re.compile(r"做多|买入|买进|看多|多头|开多|多单|持有|拿(?!不)|入手|上车|抄底|建仓|进场|加仓|囤|买")
# A one-word answer to "做多还是做空？".
_BARE_SIDE = {"多": "long", "做多": "long", "多单": "long", "空": "short", "做空": "short", "空单": "short"}
# A size: Arabic or Chinese numerals, an optional 千/万 scale, then a money word or the
# scale itself ("两万", "1.5万", "20000美元", "5000U").
_SIZE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千]+)\s*(万|千|k|K|w|W)?\s*(美元|美金|刀|USDT|usdt|U|u|块)?")
_STOP = re.compile(r"止损(?:价|位|在|设在|设置在)?\s*[:：]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
# "止损3%" is a distance, not a price of 3.
_STOP_PCT = re.compile(r"止损(?:价|位|在|设在|设置在)?\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*[%％]|止损\s*百分之([零〇一二两三四五六七八九十]+)")
_WEEKEND = re.compile(r"周末|过周末|到周一|下周一")
# "到周三", "持有到星期四收盘": held to that day's open unless the close is said.
_WEEKDAY = re.compile(r"(?:到|至)\s*(?:下)?(?:周|星期)([二三四五])(开盘|收盘)?")
_WEEKDAY_INDEX = {"二": 1, "三": 2, "四": 3, "五": 4}
# "5倍杠杆", "五倍", "杠杆10倍": a multiple, never a size.
_LEVERAGE = re.compile(r"([0-9]+(?:\.[0-9]+)?|[一二两三四五六七八九十]+)\s*倍(?:杠杆)?|杠杆\s*([0-9]+(?:\.[0-9]+)?)\s*倍?")
_NEXT_OPEN = re.compile(r"过夜|隔夜|到开盘|开盘前|今晚")
_HOURS = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:个)?小时")
_DAYS = re.compile(r"([0-9]+)\s*天")
_THESIS = re.compile(r"(?:因为|理由是|逻辑是|理由\s*[:：]|论点\s*[:：]|逻辑\s*[:：])(.+?)(?:[，,。；;！!？?]|$)")
_INVALID = re.compile(r"(?:如果|若|假如)(.+?)(?:就算错|就错|说明我错|就止损|则离场|就离场)")
# "账户10万U", "本金5万美元", "资金 20万U": the money on hand, never the position.
# "我有10万U" is the money on hand too, unless a stock follows it ("我有2万U的特斯拉" is a holding).
_ACCOUNT = re.compile(
    r"(?:账户|本金|资金|总资金|余额|我(?:现在|目前)?(?:手上|手里|这里)?有)\s*(?:余额|规模|有|是|为)?\s*[:：]?\s*"
    r"([0-9][0-9,]*(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万]+)\s*(万|千|k|K|w|W)?\s*(美元|美金|刀|USDT|usdt|U|u|块)?"
    r"(?![万千美刀块Uu0-9.])(?!\s*(?:的)?\s*(?:" +"|".join(sorted(map(re.escape, ALIASES_ZH), key=len, reverse=True)) + r"|[A-Za-z]{2,5}))"
)


# "保证金2000", "2千U保证金": the money put up, never the position and never the account.
_MARGIN = re.compile(
    r"保证金\s*(?:是|为|有|:|：)?\s*([0-9][0-9,]*(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万]+)\s*(万|千|k|K|w|W)?"
    r"|([0-9][0-9,]*(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万]+)\s*(万|千|k|K|w|W)?\s*(?:美元|美金|刀|USDT|usdt|U|u|块)?\s*(?:的)?保证金"
)
_PRICE_CONTEXT = re.compile(r"止损|止盈|价|跌破|突破|涨到|跌到|目标|%|％")
_BARE_AFTER_NAME = re.compile(
    "(?:" + "|".join(sorted(map(re.escape, ALIASES_ZH), key=len, reverse=True)) + r"|(?<![A-Za-z])[A-Za-z]{2,5}(?![A-Za-z]))\s*([0-9][0-9,]*(?:\.[0-9]+)?)(?![0-9.]*\s*(?:天|小时|点|个|号|月|日|倍))"
)


def chinese_number(text: str) -> float | None:
    """"两万" -> 20000, "五千" -> 5000, "1.5" -> 1.5, "三十" -> 30."""
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        pass
    total, section, digit = 0, 0, 0
    for ch in text:
        if ch in _DIGITS:
            digit = _DIGITS[ch]
        elif ch in _UNITS:
            unit = _UNITS[ch]
            if unit == 10_000:
                total += (section + digit) * unit
                section, digit = 0, 0
            else:
                section += (digit or 1) * unit
                digit = 0
        else:
            return None
    value = total + section + digit
    return float(value) if value else None


# A ticker written in Latin letters inside Chinese text: "做多TSLA" has no word boundary
# between 多 and T, so the English rule's \b does not see it.
_LATIN_TICKER = re.compile(r"(?<![A-Za-z])([A-Za-z]{2,5})(?![A-Za-z])")


def find_ticker_zh(text: str, known: set[str]) -> str | None:
    for name in sorted(ALIASES_ZH, key=len, reverse=True):  # longest first: 三倍做多纳指 before 纳指
        if name in text and ALIASES_ZH[name] in known:
            return ALIASES_ZH[name]
    for m in _LATIN_TICKER.finditer(text):
        if m.group(1).upper() in known:
            return m.group(1).upper()
    return None


ASKS_ZH = {"ticker": "哪只股票", "side": "做多还是做空", "notional_quote": "多大仓位（USDT）"}


_NAME_ZH = {v: k for k, v in reversed(list(ALIASES_ZH.items()))}  # the first alias listed is the name used
_SIDE_ZH = {"long": "做多", "short": "做空"}
_HINT_ZH = {"side": "回“多”或“空”就行", "notional_quote": "比如“2万U”", "ticker": "比如“特斯拉”或“NVDA”"}


def ask(missing: list[str], known: dict[str, object] | None = None) -> str:
    """The clarifying question, in Chinese, for the fields still missing.

    It first says back what it already has, so a trader who answered part of the
    question sees the answer landed and is not handed the same sentence again.
    """
    known = known or {}
    have = []
    if known.get("ticker"):
        have.append(_NAME_ZH.get(str(known["ticker"]), str(known["ticker"])))
    if known.get("side") in _SIDE_ZH:
        have.append(_SIDE_ZH[str(known["side"])])
    if known.get("notional_quote"):
        have.append(f"{float(known['notional_quote']):,.0f} USDT")
    kind = known.get("horizon_kind")
    if kind == "through_weekend":
        have.append("过周末")
    elif kind == "next_open":
        have.append("过夜")
    elif kind == "hours" and known.get("horizon_hours"):
        have.append(f"{float(known['horizon_hours']):g} 小时")
    wanted = [m for m in missing if m in ASKS_ZH]
    head = ("已记下：" + " · ".join(have) + "。") if have else ""
    if len(wanted) == 1:
        return f"{head}还差一项：{ASKS_ZH[wanted[0]]}？{_HINT_ZH[wanted[0]]}。"
    return head + "还需要知道：" + "、".join(ASKS_ZH[m] for m in wanted) + "。例如：“周末持有两万美元的特斯拉，止损350”。"


# "我还持有", "我已经持有", "我手上有", "目前持仓：": what is already on, as opposed to a trade
# being asked about. A bare 持有 is a trade ("周末持有两万美元的特斯拉"), so an adverb or a
# place ("手上") is required.
_HOLD_INTRO = re.compile(
    r"(?:我|咱)?(?:现在|目前|已经|还|也|另外|同时)+(?:持有|持仓|拿着|有)"
    r"|(?:我|咱)?(?:手上|手里)(?:还|已经|目前)?(?:持有|有|拿着)"
    r"|(?:现有|目前|当前)?持仓\s*[:：]"
)
_HELD_SEP = re.compile(r"(?:\s*(?:[,，、;；]|和|以及|还有|并且|另外|外加|加上|还|也))*\s*")
_HELD_ITEM = re.compile(
    r"(?P<lead>做多|做空|多单|空单)?\s*(?P<num>[0-9][0-9,]*(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千]+)\s*(?P<scale>万|千|k|K|w|W)?\s*(?P<money>美元|美金|刀|USDT|usdt|U|u|块)?\s*(?:的)?\s*"
)
_HELD_TRAIL = re.compile(r"\s*(多单|空单|多头|空头|做多|做空)")
_TRAIL_SIDE = {"多单": "long", "多头": "long", "做多": "long", "空单": "short", "空头": "short", "做空": "short"}


def _name_at(text: str, pos: int, known: set[str]) -> tuple[str, int] | None:
    for name in sorted(ALIASES_ZH, key=len, reverse=True):
        if text.startswith(name, pos) and ALIASES_ZH[name] in known:
            return ALIASES_ZH[name], pos + len(name)
    m = _LATIN_TICKER.match(text, pos)
    if m and m.group(1).upper() in known:
        return m.group(1).upper(), m.end()
    return None


def read_positions(text: str, known: set[str]) -> tuple[list[tuple[str, str, float]], str]:
    """Holdings a Chinese message states, and the message with those clauses blanked out."""
    found: list[tuple[str, str, float]] = []
    chars = list(text)
    for intro in _HOLD_INTRO.finditer(text):
        pos, first, last_end = intro.end(), True, None
        while True:
            sep = _HELD_SEP.match(text, pos)
            m = _HELD_ITEM.match(text, sep.end())
            if not m:
                break
            number, scale, money = m.group("num"), m.group("scale"), m.group("money")
            if not (scale or money or re.search("[百千]", number)):
                break  # a bare number is a price or a duration, not a holding
            if not first and m.group("lead") and not re.search("和|以及|并且|外加|加上", sep.group()):
                break  # a comma then a side starts the next trade
            value = chinese_number(number)
            got = _name_at(text, m.end(), known)
            if value is None or got is None:
                break
            value *= 10_000 if scale in ("万", "w", "W") else 1_000 if scale in ("千", "k", "K") else 1
            ticker, end = got
            trail = _HELD_TRAIL.match(text, end)
            side = _TRAIL_SIDE.get(m.group("lead") or "") or (_TRAIL_SIDE[trail.group(1)] if trail else "long")
            if trail:
                end = trail.end()
            found.append((ticker, side, value))
            pos, last_end, first = end, end, False
        if last_end is not None:
            chars[intro.start():last_end] = " " * (last_end - intro.start())
    return found, "".join(chars)


def read(text: str, known: set[str]) -> dict[str, object]:
    """The fields a Chinese message states. Anything not stated is left out."""
    out: dict[str, object] = {}
    ticker = find_ticker_zh(text, known)
    if ticker:
        out["ticker"] = ticker
    short, long_ = _SHORT.search(text), _LONG.search(text)
    bare = _BARE_SIDE.get(text.strip().strip("。.!！~ "))
    if bare:
        out["side"] = bare
    elif short or _BARE_SHORT.search(text):
        out["side"] = "short"
    elif long_:
        out["side"] = "long"
    stop_pct = _STOP_PCT.search(text)
    stop = stop_pct or _STOP.search(text)
    if stop_pct:
        pct = float(stop_pct.group(1)) if stop_pct.group(1) else chinese_number(stop_pct.group(2))
        if pct:
            out["stop_pct"] = pct
    elif stop:
        out["stop_price"] = float(stop.group(1).replace(",", ""))
    spent = [stop.span()] if stop else []
    lev = _LEVERAGE.search(text)
    if lev:
        value = chinese_number(lev.group(1)) if lev.group(1) else float(lev.group(2))
        if value and value >= 1:
            out["leverage"] = value
        spent.append(lev.span())
    # An account size ("账户10万U") is the money on hand, never the position, and the
    # thesis and invalidation clauses carry their own numbers ("跌破340") that read like
    # a size but are not one. All three are spent before a bare number is taken for one.
    account = _ACCOUNT.search(text)
    if account:
        value = chinese_number(account.group(1))
        if value is not None:
            scale = account.group(2)
            if scale in ("万", "w", "W"):
                value *= 10_000
            elif scale in ("千", "k", "K"):
                value *= 1_000
            out["account_equity_quote"] = value
        spent.append(account.span())
    margin = _MARGIN.search(text)
    if margin:
        raw, scale = (margin.group(1), margin.group(2)) if margin.group(1) else (margin.group(3), margin.group(4))
        value = chinese_number(raw)
        if value is not None:
            value *= 10_000 if scale in ("万", "w", "W") else 1_000 if scale in ("千", "k", "K") else 1
            out["margin_quote"] = value
        spent.append(margin.span())
    thesis, invalid = _THESIS.search(text), _INVALID.search(text)
    if thesis:
        spent.append(thesis.span())
    if invalid:
        spent.append(invalid.span())
    for m in _SIZE.finditer(text):
        if any(a <= m.start() < b for a, b in spent):
            continue
        number, scale, money = m.group(1), m.group(2), m.group(3)
        # A bare number is only a size when it is scaled or said to be money; "350" on
        # its own is as likely a price, and "3小时" is a duration.
        if not (scale or money):
            continue
        value = chinese_number(number)
        if value is None:
            continue
        if scale in ("万", "w", "W"):
            value *= 10_000
        elif scale in ("千", "k", "K"):
            value *= 1_000
        out["notional_quote"] = value
        break
    if "notional_quote" not in out and ticker and not _PRICE_CONTEXT.search(text):
        # "拿 苹果 5000 到周三": a plain number right after the name, with nothing else to
        # size the trade, is the size. Under 100 it is more likely a price or a count.
        for m in _BARE_AFTER_NAME.finditer(text):
            if any(a <= m.start(1) < b for a, b in spent):
                continue
            value = chinese_number(m.group(1))
            if value is not None and value >= 100:
                out["notional_quote"] = value
                break
    day = _WEEKDAY.search(text)
    if day:
        from nightwatch.api.intake import hours_until_weekday

        h = hours_until_weekday(_WEEKDAY_INDEX[day.group(1)], "close" if day.group(2) == "收盘" else "open")
        if h:
            out["horizon_kind"], out["horizon_hours"] = "hours", h
    if "horizon_kind" in out:
        pass
    elif _WEEKEND.search(text):
        out["horizon_kind"] = "through_weekend"
    elif _NEXT_OPEN.search(text):
        out["horizon_kind"] = "next_open"
    elif (h := _HOURS.search(text)):
        out["horizon_kind"], out["horizon_hours"] = "hours", float(h.group(1))
    elif (d := _DAYS.search(text)):
        out["horizon_kind"], out["horizon_hours"] = "hours", float(d.group(1)) * 24.0
    if thesis:
        out["thesis"] = thesis.group(1).strip()
    if invalid:
        out["invalidation"] = invalid.group(1).strip()
    return out
