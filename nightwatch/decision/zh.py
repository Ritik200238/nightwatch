"""Chinese wording for the sentences the decision layer writes itself.

The report page is read in either language and the language can be switched after the
report was made, so every English sentence that has a fixed shape also carries a Chinese
twin (``*_zh``), built from the same numbers in the same place. This module holds the pieces
both writers share: the stress presets' one-line probability notes, which several sentences
quote. A note this does not know is returned as None and the caller keeps the English, so a
new preset can never break a report; it only reads in English until it is added here.
"""

from __future__ import annotations

import re


def usdt(x: float | None) -> str:
    return "—" if x is None else f"{x:,.0f}"


def _way(word: str) -> str:
    return "下跌" if word == "down" else "上涨"


def note_zh(note: str) -> str | None:  # noqa: C901, PLR0911 - one branch per known note
    """A stress preset's probability note in Chinese, or None when it is not a known shape."""
    n = (note or "").strip()
    if not n:
        return ""
    if (m := re.fullmatch(r"what (.+) did on (\S+), the day the market gapped (down|up) most", n)):
        return f"{m.group(1)} 在 {m.group(2)} 的表现，那一天大盘休市后跳空{_way(m.group(3))}最多"
    if (m := re.fullmatch(r"what (.+) did on (\S+), the day the market's three sessions ran (down|up) most", n)):
        return f"{m.group(1)} 在 {m.group(2)} 的表现，那一天前后三个交易日大盘{_way(m.group(3))}最多"
    if (m := re.fullmatch(r"(\d+)% of (\d+) past (?:runs of (\d+) closed windows|closed windows) were worse for this side", n)):
        span = f"连续 {m.group(3)} 个休市时段" if m.group(3) else "休市时段"
        return f"过去 {m.group(2)} 个{span}样本中，有 {m.group(1)}% 对这一方向更不利"
    if (m := re.fullmatch(r"worst of (\d+) past earnings reactions", n)):
        return f"过去 {m.group(1)} 次财报反应中最差的一次"
    if n == "median absolute past reaction, adverse direction":
        return "过去财报反应幅度的中位数，取不利方向"
    if (m := re.fullmatch(r"(\d+)σ adverse move at current realised vol", n)):
        return f"按当前已实现波动率算的 {m.group(1)}σ 不利波动"
    if (m := re.fullmatch(r"(\d+)% of (\d+) closed-market hours had a wider gap", n)):
        return f"{m.group(2)} 个休市小时中，有 {m.group(1)}% 的价差更大"
    if n == "exit into a book one fifth as deep as now":
        return "在只有现在五分之一深度的盘口里平仓"
    if n == "2σ 24h move with no ability to react, then exit into a half-depth book":
        return "24 小时内出现 2σ 波动且来不及应对，之后在深度减半的盘口里平仓"
    if n == "95th percentile |funding| every 8h for the horizon":
        return "持有期内每 8 小时按资金费率绝对值的第 95 百分位计"
    if n == "the one-standard-deviation move listed options imply for this hold, taken in the adverse direction":
        return "上市期权对这个持有期隐含的一倍标准差波动，取不利方向"
    if n.startswith("the loss 1 in 20 similar past moments exceeded over this hold"):
        return "在这个持有期内，二十个相似的历史时刻里有一个的亏损超过了它；压力测试不会比它更温和"
    return None


_SPAN_ZH = (
    (re.compile(r"^over 30 days$"), "超过 30 天"),
    (re.compile(r"^(\d+(?:\.\d+)?) days?$"), r"\1 天"),
    (re.compile(r"^(\d+(?:\.\d+)?) hours?$"), r"\1 小时"),
)
_LABEL_ZH = {
    "the coming weekend, Friday's close to Monday's open": "即将到来的周末：周五收盘到周一开盘",
    "through the weekend, to the next open after it": "持有过周末，到周末后的下一个开盘",
}
_FUND_ZH = {
    "TQQQ": "TQQQ 是每日重置的 3 倍做多纳斯达克 100 基金：持有超过一天，它的回报不等于指数的 3 倍，震荡行情还会侵蚀净值。",
    "SQQQ": "SQQQ 是每日重置的 3 倍做空纳斯达克 100 基金：纳斯达克下跌时它上涨，持有超过一天，回报也不等于指数的 -3 倍。",
}
_FIXED_ZH = {
    "The perp is priced off the token's path; the gap between the two is shocked separately by the basis presets.":
        "永续合约按代币的价格路径定价；两者之间的价差由价差类压力情景单独冲击。",
    "No leverage: a plain token position. Say \"5x\" to test it on the perpetual.": "没有杠杆：普通的现货代币仓位。说一声“5 倍”就能在永续合约上测试。",
    "No stop: the risk is sized on the calibrated 1-in-20 loss instead.": "没有设止损：改按校准后的二十分之一亏损来定风险。",
    "Account size not given, so the size limits that depend on it are not checked.": "没有提供账户规模，所以依赖账户规模的仓位上限没有检查。",
    "The 2σ and 3σ spike scales volatility by the square root of the hours held over a 24-hour, seven-day year, which counts weekend and overnight hours as if they traded like the day. Over a weekend that is not true; read the sigma label as approximate.":
        "2σ 和 3σ 的波动飙升，是按持有小时数的平方根、以一年每天 24 小时每周 7 天来缩放波动率，这会把周末和夜间时段当成和白天一样交易。周末并非如此，请把 σ 标签当作近似值。",
    "The Monte Carlo band redraws blocks of this token's own past hourly returns and adds up the hours held. It uses only hours the token traded, with no volatility scaling for weekends or news, and it is recorded but not yet scored against outcomes the way the 1-in-20 line is.":
        "蒙特卡洛区间从这只代币自己的历史小时收益中抽取成块样本，并累加持有的小时数。它只用代币有成交的小时，没有对周末或消息做波动率缩放；它会被记录，但还没有像二十分之一线那样与实际结果对照评分。",
    "Earnings timing is not known (no upcoming date on the earnings calendar), so the earnings-gap presets are not tied to this hold.":
        "不知道财报时间（财报日历上没有即将到来的日期），所以财报跳空情景没有与这次持有挂钩。",
    "Dividends and splits were not checked: the calendar has not been synced yet.": "没有检查分红和拆股：日历还没有同步。",
    "No ex-dividend date or split inside the hold in the stored calendar (Nasdaq, Yahoo, Bitget notices).": "在已存储的日历（纳斯达克、雅虎、Bitget 公告）里，持有期内没有除息日或拆股。",
}


def _span_zh(s: str) -> str:
    for pat, rep in _SPAN_ZH:
        if pat.match(s):
            return pat.sub(rep, s)
    return s


def assumption_zh(text: str) -> str | None:  # noqa: C901, PLR0911, PLR0912 - one branch per known shape
    """One line of "what this answer assumes" in Chinese, or None when it is not a known shape."""
    t = (text or "").strip()
    if t in _FIXED_ZH:
        return _FIXED_ZH[t]
    for ticker, en in {"TQQQ": "TQQQ is a 3x leveraged", "SQQQ": "SQQQ is a 3x inverse"}.items():
        if t.startswith(en):
            return _FUND_ZH[ticker]
    if (m := re.fullmatch(r"Held for (\d+) hours(?: \((.+)\)|, to the next US regular open)?, then closed\.", t)):
        tail = f"（{_LABEL_ZH.get(m.group(2), m.group(2))}）" if m.group(2) else "，到下一个美股常规开盘" if "to the next US regular open" in t else ""
        return f"持有 {m.group(1)} 小时{tail}，之后休市。"
    if (m := re.fullmatch(r"Entered at the token's last price, ([\d,.]+), as of (\d\d \w{3} \d\d:\d\d) UTC\.", t)):
        return f"按代币最新价 {m.group(1)} 入场（截至 {m.group(2)} UTC）。"
    if (m := re.fullmatch(r"([\d.]+)x on the Bitget perpetual, isolated margin, maintenance margin ([\d.]+)%( from Bitget's tier for this size\.| \(assumed; Bitget's tiers were unavailable\)\.)", t)):
        src = "，取自 Bitget 对这个仓位大小的档位。" if m.group(3).startswith(" from") else "（假设值；Bitget 的档位暂不可用）。"
        return f"{m.group(1)} 倍杠杆，在 Bitget 永续合约上、逐仓保证金，维持保证金率 {m.group(2)}%{src}"
    if (m := re.fullmatch(r"Stop at ([\d,.]+)\. A resting stop fills at the next price there is, so a gap can fill it worse than the stop\.", t)):
        return f"止损设在 {m.group(1)}。挂着的止损单按下一个能成交的价格成交，所以跳空时可能比止损价更差。"
    if (m := re.fullmatch(r"Account of ([\d,]+) USDT; the size limits are shares of it\.", t)):
        return f"账户 {m.group(1)} USDT；各项仓位上限都是它的一定比例。"
    if (m := re.fullmatch(r"The (\d+) past moments compared against run from (.+) to (.+), across (\d+) tokens?; the future is assumed to resemble them only as much as the calibration page shows it has\.", t)):
        return f"用来比较的 {m.group(1)} 个历史时刻，时间跨度从 {m.group(2)} 到 {m.group(3)}，涉及 {m.group(4)} 只代币；只在校准页面显示过的程度上，才假设未来会与它们相似。"
    if (m := re.fullmatch(r"The crash replays apply (\S+)'s own stock move from those crises to today's token\. The token did not exist then.*", t)):
        return f"危机重演是把 {m.group(1)} 自己的股价在那些危机中的走势套用到今天的代币上。当时这只代币并不存在（只有 2025 年 4 月的冲击落在它的存续期内），所以价差、夜间薄盘口和上市效应都没有被重演进去。这五个时间窗口是事后挑选的。"
    if (m := re.fullmatch(r"Fair value is Bitget's index for the stock; the token sits ([+-]\d+) bps from it now\.", t)):
        return f"公允价值取 Bitget 对这只股票的指数价；代币现在比它偏离 {m.group(1)} bps。"
    if (m := re.fullmatch(r"Exit cost is walked on the (\S+) order book(?: at (\d\d:\d\d) UTC)?, taker fee on both legs; a thinner book at exit is a separate stress preset\.", t)):
        book = {"live": "实时", "recorded": "已记录的"}.get(m.group(1), m.group(1))
        at = f"（{m.group(2)} UTC）" if m.group(2) else ""
        return f"平仓成本按{book}盘口{at}逐档计算，买卖两端都按吃单手续费；平仓时盘口更薄的情况，由单独的压力情景覆盖。"
    if (m := re.fullmatch(r"Earnings fall inside the hold \(in (.+)\); the earnings-gap presets are included\.", t)):
        return f"持有期内有财报（{_span_zh(m.group(1))}后）；已包含财报跳空情景。"
    if (m := re.fullmatch(r"No earnings inside the hold \(no earnings in the next 30 days\)\.", t)):
        return "持有期内没有财报（未来 30 天内没有财报）。"
    if (m := re.fullmatch(r"No earnings inside the hold \(next in (.+)\)\.", t)):
        return f"持有期内没有财报（下一次在 {_span_zh(m.group(1))}后）。"
    if (m := re.fullmatch(r"No earnings inside the hold \(in (.+)\)\.", t)):
        return f"持有期内没有财报（{_span_zh(m.group(1))}后）。"
    return None
