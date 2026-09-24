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

_SHORT = re.compile(r"做空|卖空|看空|空头|开空")
_LONG = re.compile(r"做多|买入|买进|看多|多头|开多|持有|拿着|加仓|买")
# A size: Arabic or Chinese numerals, an optional 千/万 scale, then a money word or the
# scale itself ("两万", "1.5万", "20000美元", "5000U").
_SIZE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千]+)\s*(万|千|k|K)?\s*(美元|美金|刀|USDT|usdt|U|u|块)?")
_STOP = re.compile(r"止损(?:价|位|在|设在|设置在)?\s*[:：]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
_WEEKEND = re.compile(r"周末|过周末|到周一|下周一")
_NEXT_OPEN = re.compile(r"过夜|隔夜|到开盘|开盘前|今晚")
_HOURS = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:个)?小时")
_DAYS = re.compile(r"([0-9]+)\s*天")
_THESIS = re.compile(r"(?:因为|理由是|逻辑是)(.+?)(?:[，,。；;！!？?]|$)")
_INVALID = re.compile(r"(?:如果|若|假如)(.+?)(?:就算错|就错|说明我错|就止损|则离场|就离场)")


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
# between 多 and T, so the English rule's  does not see it.
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


def ask(missing: list[str]) -> str:
    """The clarifying question, in Chinese, for the fields still missing."""
    return "还需要知道：" + "、".join(ASKS_ZH[m] for m in missing if m in ASKS_ZH) + "。例如：“周末持有两万美元的特斯拉，止损350”。"


def read(text: str, known: set[str]) -> dict[str, object]:
    """The fields a Chinese message states. Anything not stated is left out."""
    out: dict[str, object] = {}
    ticker = find_ticker_zh(text, known)
    if ticker:
        out["ticker"] = ticker
    short, long_ = _SHORT.search(text), _LONG.search(text)
    if short:
        out["side"] = "short"
    elif long_:
        out["side"] = "long"
    stop = _STOP.search(text)
    if stop:
        out["stop_price"] = float(stop.group(1).replace(",", ""))
    spent = [stop.span()] if stop else []
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
        if scale in ("万",):
            value *= 10_000
        elif scale in ("千", "k", "K"):
            value *= 1_000
        out["notional_quote"] = value
        break
    if _WEEKEND.search(text):
        out["horizon_kind"] = "through_weekend"
    elif _NEXT_OPEN.search(text):
        out["horizon_kind"] = "next_open"
    elif (h := _HOURS.search(text)):
        out["horizon_kind"], out["horizon_hours"] = "hours", float(h.group(1))
    elif (d := _DAYS.search(text)):
        out["horizon_kind"], out["horizon_hours"] = "hours", float(d.group(1)) * 24.0
    thesis, invalid = _THESIS.search(text), _INVALID.search(text)
    if thesis:
        out["thesis"] = thesis.group(1).strip()
    if invalid:
        out["invalidation"] = invalid.group(1).strip()
    return out
