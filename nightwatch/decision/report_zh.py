"""Chinese twins for the English sentences a stored report carries and the page shows.

The report page is read in either language, and the language can be switched after a report
was made, so a sentence the engine writes in a fixed shape also carries a Chinese twin
(``*_zh``), built here from the same numbers. Every translator is a pattern over one known
English shape: it copies each number and name out of the English text unchanged, and
returns ``None`` for a shape it does not know, so a new sentence can never break a report;
it reads in English until a pattern for it is added. ``tests/test_report_zh.py`` checks that
every number in a twin is in its English original.

``add_twins(out)`` is called from ``AnalysisReport.to_dict`` and fills the twins that
the web page reads when the language is Chinese.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Rule = tuple[re.Pattern[str], Callable[[re.Match[str]], str]]


def _rules(*pairs: tuple[str, Callable[[re.Match[str]], str]]) -> list[Rule]:
    return [(re.compile(p, re.S), f) for p, f in pairs]


def _apply(rules: list[Rule], text: str) -> str | None:
    t = (text or "").strip()
    for pat, fn in rules:
        m = pat.fullmatch(t)
        if m:
            return fn(m)
    return None


# ------------------------------------------------------------------ small vocabulary

RULE_ZH = {
    "market posture": "市场环境", "written plan": "书面计划", "stop": "止损", "position size": "仓位大小", "risk budget": "风险预算",
    "exit liquidity": "平仓流动性", "liquidation": "强平", "data quality": "数据质量", "circuit breaker": "熔断", "revenge cooldown": "冷静期",
    "book tail": "整体持仓尾部风险",
}
BASIS_ZH = {
    "distance to stop": "到止损的距离",
    "analog 5th-percentile loss": "相似历史时刻的二十分之一亏损", "analog p5 loss": "相似历史时刻的二十分之一亏损",
}
_CAP_WHY_ZH = {
    "the loss if the stop is hit would exceed the share of equity you allow at risk": "止损被触发时的亏损会超过你允许的风险占比",
    "more than that would put too much of your equity in one name": "再多就会让太大比例的账户权益集中在一个标的上",
    "the current market regime calls for a smaller position than requested": "当前市场状态要求比所请求的更小的仓位",
    "the worst severe stress scenario would cost more than the allowed share of equity at a larger size": "仓位再大，最严重压力情景的亏损会超过允许的账户权益占比",
    "a larger size would push the whole book's one-in-twenty loss past the allowed share of equity": "仓位再大，整体持仓二十分之一的亏损会超过允许的账户权益占比",
}
_FLAG_ZH = {
    "thin trading: over a quarter of the last day had no trades, so volatility and the analogs lean on filled bars":
        "成交稀薄：过去一天超过四分之一的时间没有成交，波动率和相似历史时刻依赖补齐的K线",
    "quieter than this token usually is at this time of week, which is a liquidity change rather than a weekend":
        "比这只代币在一周中这个时段通常的状态更安静，这是流动性的变化，而不是周末效应",
    "the native stock has not printed for three days; fair value is older than usual": "原生股票已三天没有成交；公允价值比平时更旧",
}
_WRONG_IF = "你的“错在哪里”那条线"


def _basis(b: str) -> str:
    return BASIS_ZH.get(b, b)


def _span(s: str) -> str | None:
    """'3 days' / '5 hours' / 'over 30 days' / 'unknown' in Chinese, or None."""
    if (m := re.fullmatch(r"(\d+) days?", s)):
        return f"{m.group(1)} 天"
    if (m := re.fullmatch(r"(\d+) hours?", s)):
        return f"{m.group(1)} 小时"
    return {"over 30 days": "超过 30 天", "unknown": "未知"}.get(s)


def _ahead(s: str) -> str | None:
    """features.phrases.earnings_ahead() in Chinese."""
    s = s.strip()
    if s == "no earnings in the next 30 days":
        return "未来 30 天内没有财报"
    if s == "not known (no upcoming date on the earnings calendar)":
        return "未知（财报日历上没有下一次的日期）"
    if (m := re.fullmatch(r"in (.+)", s)) and (sp := _span(m.group(1))):
        return f"{sp}后"
    return None


def _rule_label(name: str) -> str:
    return RULE_ZH.get(name.strip(), name.strip())


# ------------------------------------------------------------------ the gate's own sentences

_WRONG_IF_FAR = (
    r"your 'wrong if' line is (\d+)% away, farther than this token's own one-in-twenty move over the hold \(([\d.]+)%\): "
    r"it is too far to bind, so it does not limit the loss"
)
_NO_STOP = r"(no stop given|no stop order)"
_INVALID = r"; your 'wrong if' line is (\d+)% away, but it is an invalidation, not a stop order"

_GATE = _rules(
    (r"thesis and invalidation stated", lambda m: "已写明理由和失效条件"),
    (r"thesis and invalidation stated \(but the invalidation is (\d+)% away, too far to bind\)",
     lambda m: f"已写明理由和失效条件（但失效线距现价 {m.group(1)}%，太远，起不到约束作用）"),
    (r"missing (.+)", lambda m: "缺少：" + "、".join({"thesis": "理由", "invalidation": "失效条件"}.get(x.strip(), x.strip()) for x in m.group(1).split(","))),
    (_WRONG_IF_FAR, lambda m: f"{_WRONG_IF}距现价 {m.group(1)}%，比这只代币在持有期内二十分之一的波动（{m.group(2)}%）还远：它太远，起不到约束作用，所以并不能限制亏损"),
    (_NO_STOP + r"; sized on the 5th percentile \(([+-][\d.]+)%\) instead(?:" + _INVALID + r")?",
     lambda m: f"{'没有止损单' if m.group(1) == 'no stop order' else '没有设止损'}；改按第 5 百分位（{m.group(2)}%）定仓位"
               + (f"；你的“错在哪里”那条线距现价 {m.group(3)}%，它是判断失效的条件，不是止损单" if m.group(3) else "")),
    (_NO_STOP + r": risk is sized on the calibrated 5th percentile, ([+-][\d.]+)% over the horizon(?:" + _INVALID + r")?",
     lambda m: f"{'没有止损单' if m.group(1) == 'no stop order' else '没有设止损'}：风险按校准后的第 5 百分位（持有期内 {m.group(2)}%）定仓位"
               + (f"；你的“错在哪里”那条线距现价 {m.group(3)}%，它是判断失效的条件，不是止损单" if m.group(3) else "")),
    (r"no stop price and no analog distribution to size on", lambda m: "没有止损价，也没有可用于定仓位的相似历史分布"),
    (r"stop is on the wrong side of entry", lambda m: "止损设在了入场价的错误一侧"),
    (r"stop ([\d.]+)% away is tighter than ([\d.]+)% — inside normal hourly noise for this token",
     lambda m: f"止损距现价 {m.group(1)}%，比 {m.group(2)}% 还紧——落在这只代币正常的小时波动范围之内"),
    (r"stop ([\d.]+)% away - check it is a price for this token", lambda m: f"止损距现价 {m.group(1)}%——请确认这是这只代币的价格"),
    (r"stop ([\d.]+)% away is wider than ([\d.]+)%", lambda m: f"止损距现价 {m.group(1)}%，比 {m.group(2)}% 更宽"),
    (r"stop ([\d.]+)% from entry", lambda m: f"止损距入场价 {m.group(1)}%"),
    (r"account equity not provided", lambda m: "没有提供账户权益"),
    (r"position is ([\d.]+)% of equity \(limit ([\d.]+)%\)", lambda m: f"仓位占账户权益的 {m.group(1)}%（上限 {m.group(2)}%）"),
    (r"position is ([\d.]+)% of equity", lambda m: f"仓位占账户权益的 {m.group(1)}%"),
    (r"cannot compute risk: no stop and no analog distribution", lambda m: "无法计算风险：既没有止损，也没有相似历史分布"),
    (r"risk ([\d,]+) \((.+)\) but equity unknown", lambda m: f"风险 {m.group(1)}（{_basis(m.group(2))}），但账户权益未知"),
    (r"risk ([\d.]+)% of equity \((.+)\) exceeds ([\d.]+)%", lambda m: f"风险占账户权益的 {m.group(1)}%（{_basis(m.group(2))}），超过了 {m.group(3)}%"),
    (r"risk ([\d.]+)% of equity \((.+)\)", lambda m: f"风险占账户权益的 {m.group(1)}%（{_basis(m.group(2))}）"),
    (r"losing exit (\S+) inside the (\d+)h cooldown", lambda m: f"{m.group(1)} 有一笔亏损平仓，仍在 {m.group(2)} 小时冷静期内"),
    (r"no recent losing exit", lambda m: "最近没有亏损平仓"),
    (r"analysis inputs degraded: (.+)", lambda m: f"分析输入质量下降：{m.group(1)}"),
    (r"inputs complete", lambda m: "输入完整"),
    (r"minor flags: (.+)", lambda m: f"轻微提示：{m.group(1)}"),
    (r"hostile regime \(size multiplier ([\d.]+)\); selective entries only", lambda m: f"市场环境不利（仓位乘数 {m.group(1)}）；只做有选择的入场"),
    (r"regime unknown: not enough history", lambda m: "无法判断市场状态：历史数据不足"),
    (r"the live book cannot absorb this size at any price", lambda m: "实时盘口无法以任何价格承接这个仓位"),
    (r"no order book available to cost the exit", lambda m: "没有盘口数据，无法估算平仓成本"),
    (r"exit would cost (\d+) bps \(limit (\d+)\)", lambda m: f"平仓成本约 {m.group(1)} bps（上限 {m.group(2)}）"),
    (r"exit costs (\d+) bps on the live book", lambda m: f"按实时盘口平仓成本为 {m.group(1)} bps"),
    (r"no Bitget perpetual for this stock, so it cannot be held with leverage", lambda m: "这只股票在 Bitget 没有永续合约，无法加杠杆持有"),
    (r"([\d.]+)x is above the ([\d.]+)x Bitget allows at this size", lambda m: f"{m.group(1)} 倍超过了 Bitget 在这个仓位下允许的 {m.group(2)} 倍"),
    (r"liquidation price unknown: no entry price", lambda m: "强平价未知：没有入场价"),
    (r"the 1-in-20 bad outcome \(([+-][\d.]+)%\) reaches the liquidation price ([\d.]+)% away",
     lambda m: f"二十分之一的不利结果（{m.group(1)}%）会触及距现价 {m.group(2)}% 的强平价"),
    (r"(\d+) of (\d+) past moments like this would have been liquidated \(([\d.]+)% away\)",
     lambda m: f"过去 {m.group(2)} 个相似时刻中有 {m.group(1)} 个会被强平（强平价距现价 {m.group(3)}%）"),
    (r"liquidation ([\d.]+)% away is reached by (.+)", lambda m: f"距现价 {m.group(1)}% 的强平价会被{_reached(m.group(2))}触及"),
    (r"liquidation ([\d.]+)% away; no past moment like this and no preset reached it", lambda m: f"强平价距现价 {m.group(1)}%；没有任何相似的历史时刻或压力情景触及它"),
    (r"regime (favorable|mixed|hostile|unknown)", lambda m: "市场状态：" + {"favorable": "有利", "mixed": "好坏参半", "hostile": "不利", "unknown": "未知"}[m.group(1)]),
    (r"no trades marked as taken yet", lambda m: "还没有标记为已执行的交易"),
    (r"no taken trade has matured yet", lambda m: "已执行的交易都还没到期"),
    (r"(.+) loss ([\d,.-]+) has reached the ([\d,.]+) limit \((\d+) trades\)", lambda m: f"{m.group(1)} 亏损 {m.group(2)} 已达 {m.group(3)} 限额（{m.group(4)} 笔交易）"),
    (r"(.+) loss ([\d,.-]+) is (\d+%) of the ([\d,.]+) limit", lambda m: f"{m.group(1)} 亏损 {m.group(2)}，占 {m.group(4)} 限额的 {m.group(3)}"),
    (r"(\d+) losing trades in a row", lambda m: f"连续亏损 {m.group(1)} 笔"),
    (r"account equity not given, so only the losing streak is checked", lambda m: "未提供账户权益，所以只检查连续亏损"),
    (r"within every loss limit(?:; (.+) at ([\d,.-]+))?", lambda m: f"在所有亏损限额之内；{m.group(1)} 为 {m.group(2)}" if m.group(1) else "在所有亏损限额之内"),
    (r"no order book available: exit cost and liquidity caps are unknown", lambda m: "没有盘口数据：平仓成本和流动性上限未知"),
    (r"no stored history for (.+); the book's tail is measured without it", lambda m: f"{m.group(1)} 没有存储的历史数据；整体持仓的尾部风险是在不含它的情况下测得的"),
    (r"the book's history is measured; its limit is applied to the size", lambda m: "已测量整体持仓的历史；它的上限已用于限定仓位"),
    (r"review your book: there is no stored history for (.+), so it is left out of the book's tail and the book cap is measured on the rest",
     lambda m: f"请复核你的持仓：{m.group(1)} 没有存储的历史数据，所以不计入整体持仓的尾部风险，持仓上限只按其余部分测算"),
    (r"no cap could be computed; provide equity and a stop", lambda m: "无法计算任何上限；请提供账户权益和止损"),
    (r"requested size is within every cap", lambda m: "所请求的仓位在所有上限之内"),
    (r"hedging (\d+%)( \(fully hedged\))? costs ~(\d+) bps and cuts the 5th-percentile loss from ([+-][\d.]+)% to about ([+-][\d.]+)% at that ratio \(basis risk only\)",
     lambda m: f"对冲 {m.group(1)}{'（全额对冲）' if m.group(2) else ''}的成本约 {m.group(3)} bps，可把第 5 百分位的亏损从 {m.group(4)}% 降到约 {m.group(5)}%（仅剩价差风险）"),
    (r"No size is allowed: (.+)", lambda m: f"不允许任何仓位：{_CAP_WHY_ZH.get(m.group(1), m.group(1))}" if m.group(1) in _CAP_WHY_ZH else ""),
    (r"Size held at ([\d,]+) USDT: (.+) \(requested ([\d,]+)\)\.?",
     lambda m: _held(m)),
    (r"it moves with the rest of your book \(mean correlation ([\d.]+)\): this adds size, not diversification",
     lambda m: f"它与你其余持仓同向波动（平均相关性 {m.group(1)}）：这只是加大仓位，不是分散风险"),
    (r"(.+) moves with the rest of the book \(mean correlation ([\d.]+)\): this adds size, not diversification",
     lambda m: f"{m.group(1)} 与其余持仓同向波动（平均相关性 {m.group(2)}）：这只是加大仓位，不是分散风险"),
)


def _reached(what: str) -> str:
    parts = []
    for p in what.split(" and "):
        if (m := re.fullmatch(r"(\d+) of (\d+) past moments", p)):
            parts.append(f"过去 {m.group(2)} 个时刻中的 {m.group(1)} 个")
        elif (m := re.fullmatch(r"(\d+) stress presets?", p)):
            parts.append(f"{m.group(1)} 个压力情景")
        else:
            return what
    return "和".join(parts)


def _held(m: re.Match[str]) -> str:
    why = m.group(2)
    book = re.fullmatch(r"the live order book can absorb only that much within the (\d+) bps exit-cost budget", why)
    reason = f"实时盘口在 {book.group(1)} bps 的平仓成本预算内只能承接这么多" if book else _CAP_WHY_ZH.get(why)
    return f"仓位限制在 {m.group(1)} USDT：{reason}（你要求的是 {m.group(3)}）" if reason else ""


def gate_zh(text: str) -> str | None:
    """One gate reason, advisory or verdict line ('stop: ...' with its rule name) in Chinese."""
    t = (text or "").strip()
    if (m := re.fullmatch(r"([a-z][a-z ]*): (.+)", t, re.S)) and m.group(1) in RULE_ZH:
        inner = _apply(_GATE, m.group(2))
        if inner:
            return f"{RULE_ZH[m.group(1)]}：{inner}"
    out = _apply(_GATE, t)
    if out is None:
        out = _FLAG_ZH.get(t)
    return out or None


_CAPS = _rules(
    (r"needs equity and a stop or analog distribution", lambda m: "需要账户权益，以及止损或历史相似分布"),
    (r"([\d.]+)% of equity at risk over a ([\d.]+)% (analog p5 loss|stop distance)",
     lambda m: f"账户权益的 {m.group(1)}% 作为风险，按{'到止损的距离' if m.group(3) == 'stop distance' else '相似历史时刻的二十分之一亏损'} {m.group(2)}% 计算"),
    (r"needs equity", lambda m: "需要账户权益"),
    (r"max ([\d.]+)% of equity in one name, and ([\d,]+) of it is already held", lambda m: f"单一标的最多占账户权益 {m.group(1)}%，其中已持有 {m.group(2)}"),
    (r"max ([\d.]+)% of equity in one name", lambda m: f"单一标的最多占账户权益 {m.group(1)}%"),
    (r"regime size multiplier ([\d.]+) on the requested size", lambda m: f"按市场状态对申请仓位乘以 {m.group(1)}"),
    (r"no order book", lambda m: "没有盘口数据"),
    (r"largest size the live book absorbs within (\d+) bps", lambda m: f"实时盘口在 {m.group(1)} bps 以内能承接的最大仓位"),
    (r"worst severe preset ([+-]?[\d.]+)% of notional; the largest size whose loss stays inside ([\d.]+)% of equity",
     lambda m: f"最严重的压力情景为仓位的 {m.group(1)}%；亏损不超过账户权益 {m.group(2)}% 的最大仓位"),
    (r"worst severe preset ([+-]?[\d.]+)% of notional; approximately the largest size within ([\d.]+)% of equity",
     lambda m: f"最严重的压力情景为仓位的 {m.group(1)}%；大约是亏损不超过账户权益 {m.group(2)}% 的最大仓位"),
    (r"largest size whose worst severe loss stays inside ([\d.]+)% of equity", lambda m: f"最严重压力情景的亏损不超过账户权益 {m.group(1)}% 的最大仓位"),
    (r"no stress presets available", lambda m: "没有可用的压力预设"),
    (r"needs equity to bound the stress loss", lambda m: "需要账户权益才能限定压力亏损"),
    (r"largest size whose book-wide one-in-twenty loss stays inside ([\d.]+)% of equity", lambda m: f"整体持仓二十分之一的亏损不超过账户权益 {m.group(1)}% 的最大仓位"),
    (r"the largest size at which the whole book's one-in-twenty loss stays inside ([\d.]+)% of equity \(([\d,]+)\)(.*)",
     lambda m: f"整体持仓二十分之一的亏损不超过账户权益 {m.group(1)}%（{m.group(2)}）的最大仓位{_held_note(m.group(3))}"),
)


def _held_note(rest: str) -> str:
    """The optional ', of which N is already held' tail some book-cap details carry."""
    r = rest.strip()
    if not r:
        return ""
    if (m := re.fullmatch(r"[,;]?\s*([\d,]+) of it is already held", r)):
        return f"，其中已持有 {m.group(1)}"
    return f" {r}"


def cap_detail_zh(text: str) -> str | None:
    return _apply(_CAPS, text)


# ------------------------------------------------------------------ the analog search and its lens

LENS_ZH: dict[str, tuple[str, str]] = {
    "earnings_soon": ("财报前", "24 小时内有财报"),
    "earnings_this_week": ("三天内有财报", "72 小时内有财报"),
    "just_after_earnings": ("刚出财报", "过去 24 小时内发布了财报"),
    "fomc_soon": ("FOMC 前", "48 小时内有 FOMC 决议"),
    "weekend": ("跨周末", "周五夜、周末或周日夜的时段"),
    "weeknight": ("普通工作日夜晚", "周一至周四的隔夜时段"),
    "market_shut": ("美股休市期间", "美股常规交易时段之外的任何一小时"),
    "market_open": ("美股交易时段内", "美股常规交易时段"),
    "basis_stretched": ("代币偏离公允价值", "价差 z 分数的绝对值不低于 2"),
    "basis_calm": ("代币贴近公允价值", "价差 z 分数的绝对值不高于 0.5"),
    "high_volatility": ("高波动", "已实现波动率处于其自身一年中最高的五分之一"),
    "low_volatility": ("低波动", "已实现波动率处于其自身一年中最低的五分之一"),
    "thin_liquidity": ("盘口偏薄", "成交量不高于一周中同一小时通常水平的一半"),
    "uptrend": ("处于上升趋势", "价格高于其移动平均线"),
    "downtrend": ("处于下降趋势", "价格低于其移动平均线"),
    "fresh_filing": ("刚发布 SEC 公告", "过去 24 小时内受理了一份文件"),
    "risk_off": ("市场紧张", "VIX 处于其自身一年中最高的五分之一"),
}
_LENS_LABEL_EN: dict[str, str] = {}


def _lens_labels() -> dict[str, str]:
    """English label -> Chinese label, read from the live lens list so the two cannot drift."""
    if not _LENS_LABEL_EN:
        from nightwatch.analog import lens as lens_mod

        for x in lens_mod.LENSES:
            if x.name in LENS_ZH:
                _LENS_LABEL_EN[x.label] = LENS_ZH[x.name][0]
    return _LENS_LABEL_EN


def lens_description_zh(desc: str) -> str | None:
    """'earnings ahead and over a weekend' -> '财报前 且 跨周末'. None when any part is unknown."""
    labels = _lens_labels()
    parts = [p.strip() for p in (desc or "").split(" and ")]
    if not parts or any(p not in labels for p in parts):
        return None
    return " 且 ".join(labels[p] for p in parts)


def _lens_text(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    if (m := re.fullmatch(r"only (\d+) past hours match (.+), which is too few to build a distribution from; the answer below is the unfiltered one", t)) and (d := lens_description_zh(m.group(2))):
        return f"只有 {m.group(1)} 个历史小时符合“{d}”，样本太少，无法建立分布；下面的答案是未经筛选的结果"
    if (m := re.fullmatch(r"(.+) covers ([\d,]+) past hours, but (.+) - they fall on too few separate dates to count as independent evidence; the answer below is the unfiltered one", t)) \
            and (d := lens_description_zh(m.group(1))) and (r := _analog_reason_zh(m.group(3))):
        return f"“{d}”覆盖了 {m.group(2)} 个历史小时，但{r}——它们落在太少的不同日期上，不能算作独立的证据；下面的答案是未经筛选的结果"
    if (m := re.fullmatch(r"(.+) is too rare in (\S+)'s own past; searched the pooled history across (\d+) tokens instead", t)) and (d := lens_description_zh(m.group(1))):
        return f"“{d}”在 {m.group(2)} 自己的历史中太少见；改为检索 {m.group(3)} 只代币的合并历史"
    return None


def _analog_reason_zh(r: str) -> str | None:
    if (m := re.fullmatch(r"only (\d+) distinct episodes \(need (\d+)\)", r)):
        return f"只有 {m.group(1)} 个互相独立的历史事件（至少需要 {m.group(2)} 个）"
    if (m := re.fullmatch(r"only (\d+) candidate rows with complete features", r)):
        return f"只有 {m.group(1)} 行候选数据特征完整"
    if r == "fewer than 3 usable features in the query":
        return "可用的特征不足 3 个"
    if r == "fewer than 3 informative features in the history":
        return "历史中有信息量的特征不足 3 个"
    return None


_WARN = _rules(
    (r"same-ticker history has only (\d+) distinct episodes; using pooled history across (\d+) tickers",
     lambda m: f"这只代币自己的历史只有 {m.group(1)} 个互相独立的事件；改用 {m.group(2)} 只代币的合并历史"),
    (r"analog search refused: (.+)", lambda m: (f"相似历史检索未运行：{r}" if (r := _analog_reason_zh(m.group(1))) else "")),
)


def warning_zh(text: str) -> str | None:
    return _lens_text(text) or _apply(_WARN, text) or _apply(_GATE, text) or None


# ------------------------------------------------------------------ execution, book and plans

_LIQ = _rules(
    (r"no order-book snapshots recorded yet", lambda m: "还没有记录到任何盘口快照"),
    (r"every bucket is still thin: the recorder needs more hours before these can be compared", lambda m: "每个时段的样本都还很少：记录器需要更多小时的数据，才能互相比较"),
    (r"(\d+) of (\d+) buckets are still thin and are marked as such", lambda m: f"{m.group(2)} 个时段中有 {m.group(1)} 个样本仍然很少，已做标注"),
)

_BOOK_NOTES = _rules(
    (r"no stored history for (\S+): it is counted in exposure but not in the tail", lambda m: f"{m.group(1)} 没有存储的历史数据：计入了敞口，但没有计入尾部风险"),
    (r"(\S+) has only (\d+) usable hours: too short for a tail", lambda m: f"{m.group(1)} 只有 {m.group(2)} 个可用小时：太短，无法测算尾部风险"),
    (r"(\S+) has too little stored history to measure how it adds to the book", lambda m: f"{m.group(1)} 的历史数据太少，无法测算它对整体持仓的增量影响"),
    (r"only (\d+) hours are shared by every position: not enough to combine them", lambda m: f"所有持仓只有 {m.group(1)} 个共同的小时：不足以把它们合并计算"),
    (r"the combined tail covers only the positions with enough history", lambda m: "合并后的尾部风险只覆盖历史数据足够的持仓"),
    (r"(\S+) moves with the rest of the book \(mean correlation ([\d.]+)\): this adds size, not diversification",
     lambda m: f"{m.group(1)} 与其余持仓同向波动（平均相关性 {m.group(2)}）：这只是加大仓位，不是分散风险"),
    (r"the book's tail is almost the sum of its parts, so these names are one bet", lambda m: "整体持仓的尾部风险几乎等于各部分之和，所以这些标的其实是同一个赌注"),
    (r"you already hold ([\d,]+) of (\S+) (long|short); with this trade that name is ([\d,]+)",
     lambda m: f"你已经持有 {m.group(1)} 的 {m.group(2)}{'多头' if m.group(3) == 'long' else '空头'}；加上这笔交易，该标的将达到 {m.group(4)}"),
    (r"(.+): no stored history, so left out of the windows \(the crash replays use their own daily table\)",
     lambda m: f"{m.group(1)}：没有存储的历史数据，所以不计入各个窗口（历史危机重演使用它们自己的日线表）"),
    (r"(\S+) carries most of the bad case but has no Bitget perpetual to hedge it with", lambda m: f"{m.group(1)} 承担了大部分不利情形，但没有可用来对冲它的 Bitget 永续合约"),
    (r"a trim realises gains or losses on the held position; tax is not counted", lambda m: "减仓会让所持仓位的盈亏落袋；税费未计入"),
    (r"modelled as the perp tracking the stock one for one; funding paid or earned while it is open is not counted", lambda m: "按永续合约与股票一比一同步变动来建模；持仓期间支付或收到的资金费率未计入"),
    (r"the cost is a taker fee to open and again to close", lambda m: "成本是开仓和平仓各一次 taker 手续费"),
    (r"hedge (\d+)% of (\S+) \(([\d,]+)\) with a short on its Bitget perpetual", lambda m: f"用 Bitget 永续合约的空头对冲 {m.group(2)} 的 {m.group(1)}%（{m.group(3)}）"),
    (r"take (\S+) at ([\d,]+) instead of ([\d,]+)", lambda m: f"把 {m.group(1)} 的仓位改为 {m.group(2)}，而不是 {m.group(3)}"),
    (r"trim (\S+) by (\d+)% \(([\d,]+)\), the holding that carries most of the bad case; even closing it does not get the book inside the limit",
     lambda m: f"把 {m.group(1)} 减掉 {m.group(2)}%（{m.group(3)}），它承担了大部分不利情形；即使全部平掉，整体持仓也回不到限额之内"),
    (r"trim (\S+) by (\d+)% \(([\d,]+)\), the holding that carries most of the bad case",
     lambda m: f"把 {m.group(1)} 减掉 {m.group(2)}%（{m.group(3)}），它承担了大部分不利情形"),
)


def liquidity_note_zh(text: str) -> str | None:
    return _apply(_LIQ, text) or None


def book_note_zh(text: str) -> str | None:
    return _apply(_BOOK_NOTES, text) or None


CRASH_ZH = {
    "covid_2020": "2020 年新冠暴跌", "banks_2023": "2023 年 3 月银行危机", "rates_2022": "2022 年通胀冲击",
    "carry_2024": "2024 年 7–8 月科技股轮动与套息交易平仓", "tariffs_2025": "2025 年 4 月关税冲击",
}


# ------------------------------------------------------------------ provenance

_SRC = _rules(
    (r"Bitget spot order book", lambda m: "Bitget 现货盘口"),
    (r"api\.bitget\.com spot orderbook", lambda m: "api.bitget.com 现货盘口"),
    (r"past moments like now, from Bitget candles", lambda m: "来自 Bitget K 线中与现在相似的历史时刻"),
    (r"the stop price you entered", lambda m: "你输入的止损价"),
    (r"spot close→open across closed windows", lambda m: "休市窗口中现货从收盘到开盘的价格变动"),
    (r"rv_24h × √horizon", lambda m: "24 小时已实现波动率 × √持有期"),
    (r"rv_24h, book", lambda m: "24 小时已实现波动率和实时盘口"),
    (r"native stock close→open across report dates", lambda m: "原生股票在各财报日期前后从收盘到开盘的价格变动"),
    (r"Cboe delayed option quotes, at-the-money implied volatility", lambda m: "Cboe 延迟期权报价，平值隐含波动率"),
    (r"\|basis vs index\| during closed sessions", lambda m: "休市时段内代币与指数价差的绝对值"),
    (r"live order book scaled", lambda m: "实时盘口按比例缩减"),
    (r"perp funding history", lambda m: "永续合约资金费率历史"),
    (r"Yahoo daily, stock's move on SPY's extreme day in the window(?: \((\d{4}-\d{2}-\d{2})\))?",
     lambda m: "Yahoo 日线：窗口内标普 ETF（SPY）极端那一天该股票的涨跌" + (f"（{m.group(1)}）" if m.group(1) else "")),
    (r"block bootstrap of this token's hourly returns", lambda m: "对这只代币小时收益率做分块自助抽样"),
    (r"([\d.]+)% maintenance margin assumed \(tiers unavailable\)", lambda m: f"假设维持保证金率 {m.group(1)}%（无法读取分档）"),
    (r"Bitget perpetual margin tiers for this size", lambda m: "Bitget 永续合约针对该仓位的保证金分档"),
    (r"policy caps: risk budget, concentration, cost budget", lambda m: "策略上限：风险预算、集中度、成本预算"),
    (r"Qwen analyst; reads the finished report, never moves a number", lambda m: "Qwen 分析师；只读取已完成的报告，不改变任何数字"),
    (r"Bitget US-stock data \(bitget-mcp-server\)", lambda m: "Bitget 美股数据（bitget-mcp-server）"),
    (r"max\(rv_24h, rv_(\d+)h\) × √horizon", lambda m: f"max(24 小时已实现波动率, {m.group(1)} 小时已实现波动率) × √持有期"),
    (r"analog cohort p(\d+) over the ticket's hold", lambda m: f"相似历史样本在你这笔交易持有期内的第 {m.group(1)} 百分位"),
    (r"preset rule", lambda m: "预设规则"),
)


def source_zh(text: str) -> str | None:
    # A preset's provenance source is its probability note ("5% of 440 past closed windows were worse...").
    from nightwatch.decision.zh import note_zh

    return _apply(_SRC, text) or note_zh(text) or None


# ------------------------------------------------------------------ the premise check

_PREMISE = _rules(
    (r"Your reason leans on a recent earnings report, but the last one was (.+?) ago(?: and next: (.+))?\.",
     lambda m: _p("你的理由依赖最近的一份财报，但上一次财报是 {a} 前" + ("，下一次：{b}" if m.group(2) else "") + "。", a=_span(m.group(1)), b=_ahead(m.group(2) or "x") if m.group(2) else "")),
    (r"Your reason leans on earnings coming up, but next earnings: (.+), well past this hold\.",
     lambda m: _p("你的理由依赖即将到来的财报，但下一次财报：{a}，远在这次持有期之后。", a=_ahead(m.group(1)))),
    (r"Your reason mentions earnings, but none fall near this hold \(no past report on record; next: (.+)\)\.",
     lambda m: _p("你的理由提到了财报，但这次持有期附近没有财报（没有历史财报记录；下一次：{b}）。", b=_ahead(m.group(1)))),
    (r"Your reason mentions earnings, but none fall near this hold \(last (.+?) ago; next: (.+)\)\.",
     lambda m: _p("你的理由提到了财报，但这次持有期附近没有财报（上一次在 {a} 前；下一次：{b}）。", a=_span(m.group(1)), b=_ahead(m.group(2)))),
    (r"Your reason mentions the Fed, but there is no FOMC decision in the next 30 days\.", lambda m: "你的理由提到了美联储，但未来 30 天内没有 FOMC 决议。"),
    (r"Your reason mentions the Fed, but the next FOMC decision is (.+?) away, after this hold ends\.",
     lambda m: _p("你的理由提到了美联储，但下一次 FOMC 决议还有 {a}，在这次持有期结束之后。", a=_span(m.group(1)))),
    (r"Your reason leans on a data release, but no scheduled release \(CPI, jobs, PCE, GDP, retail sales\) falls in the next 72 hours\.",
     lambda m: "你的理由依赖某项数据发布，但未来 72 小时内没有已排期的发布（CPI、就业、PCE、GDP、零售销售）。"),
    (r"Your reason mentions a dividend or split, but none falls inside this hold; the next is (.+)\.",
     lambda m: _p("你的理由提到了分红或拆股，但这次持有期内没有；下一次是 {a}。", a=_event(m.group(1)))),
    (r"Your reason mentions a dividend or split; the stored calendar has: (.+)\.",
     lambda m: _p("你的理由提到了分红或拆股；已存储的日历里有：{a}。", a="；".join(filter(None, [_event(x) for x in m.group(1).split("; ")])) if all(_event(x) for x in m.group(1).split("; ")) else None)),
    (r"Your reason mentions a dividend or split, but the stored calendar has none inside this hold and none ahead\.",
     lambda m: "你的理由提到了分红或拆股，但已存储的日历里这次持有期内没有，之后也没有。"),
    (r"Your reason mentions a dividend or split, but the dividend and split calendar has not been synced, so it could not be checked\.",
     lambda m: "你的理由提到了分红或拆股，但分红与拆股日历还没有同步，所以无法核对。"),
    (r"Your stop \(([\d,.]+)\) sits beyond your own 'wrong if' level \(([\d,.]+)\): if the idea is proven wrong you are still holding it\.",
     lambda m: f"你的止损（{m.group(1)}）设在了你自己的“错在哪里”价位（{m.group(2)}）之外：如果想法被证明是错的，你仍然持有这笔仓位。"),
)


def _p(template: str, **kw: str | None) -> str:
    """Fill a Chinese template; an unknown piece makes the whole sentence unknown ('')."""
    if any(v is None for v in kw.values()):
        return ""
    return template.format(**kw)


def _event(s: str) -> str | None:
    """One corporate event as features.corporate.plain() writes it, in Chinese."""
    s = s.strip()
    if (m := re.fullmatch(r"ex-dividend(?: of ([\d.]+) (\w+) a share)? on (\d{4}-\d{2}-\d{2})(?:, about ([\d.]+)% of the price)? \((.+)\)", s)):
        amt = f"每股 {m.group(1)} {m.group(2)}的" if m.group(1) else ""
        pct = f"，约占股价的 {m.group(4)}%" if m.group(4) else ""
        return f"{m.group(3)} 的{amt}除息{pct}（{_decl(m.group(5))}）"
    if (m := re.fullmatch(r"(.+?) split effective (\d{4}-\d{2}-\d{2}) \((.+)\)", s)):
        ratio = "一次" if m.group(1) == "a" else f"{m.group(1)} 的"
        return f"{ratio}拆股，{m.group(2)} 生效（{_decl(m.group(3))}）"
    return None


def _decl(src: str) -> str:
    return re.sub(r", declared (\S+)$", r"，公告日 \1", src)


def premise_zh(text: str) -> str | None:
    return _apply(_PREMISE, text) or None


# ------------------------------------------------------------------ attach the twins to a report


def _parallel(items: Any, fn: Callable[[str], str | None]) -> list[str] | None:  # noqa: ANN401
    """A list of Chinese lines, one per English line ('' where there is no twin), or None when
    there is nothing to say in Chinese at all."""
    if not isinstance(items, list):
        return None
    out = [(fn(x) or "") if isinstance(x, str) else "" for x in items]
    return out if any(out) else None


def add_twins(out: dict[str, Any]) -> None:
    """Fill the Chinese twins on a serialised report. Each step is independent and safe."""
    steps = (_twin_gate, _twin_lens, _twin_warnings, _twin_premise, _twin_execution, _twin_portfolio, _twin_provenance)
    for step in steps:
        try:
            step(out)
        except Exception:  # noqa: BLE001 - a translation must never break a report
            log.exception("zh twin step %s failed", step.__name__)


def _twin_gate(out: dict[str, Any]) -> None:
    v = out.get("verdict")
    if isinstance(v, dict):
        if (z := _parallel(v.get("reasons"), gate_zh)):
            v["reasons_zh"] = z
        for c in v.get("caps") or []:
            if isinstance(c, dict) and c.get("detail") and (d := cap_detail_zh(c["detail"])):
                c["detail_zh"] = d
    g = out.get("gate")
    if isinstance(g, dict):
        if (z := _parallel(g.get("advisories"), gate_zh)):
            g["advisories_zh"] = z
        for r in g.get("rules") or []:
            if isinstance(r, dict) and r.get("reason") and (d := gate_zh(r["reason"])):
                r["reason_zh"] = d
    sz = out.get("sizing")
    if isinstance(sz, dict):
        for c in sz.get("caps") or []:
            if isinstance(c, dict) and c.get("detail") and (d := cap_detail_zh(c["detail"])):
                c["detail_zh"] = d
        if sz.get("hedge_rationale") and (d := gate_zh(sz["hedge_rationale"])):
            sz["hedge_rationale_zh"] = d


def _twin_lens(out: dict[str, Any]) -> None:
    lens = (out.get("analog") or {}).get("lens")
    if not isinstance(lens, dict):
        return
    if lens.get("description") and (d := lens_description_zh(lens["description"])):
        lens["description_zh"] = d
    if lens.get("refused") and (d := _lens_text(lens["refused"])):
        lens["refused_zh"] = d
    for x in lens.get("lenses") or []:
        if isinstance(x, dict) and x.get("name") in LENS_ZH:
            x["label_zh"], x["definition_zh"] = LENS_ZH[x["name"]]


def _twin_warnings(out: dict[str, Any]) -> None:
    if (z := _parallel(out.get("warnings"), warning_zh)):
        out["warnings_zh"] = z


def _twin_premise(out: dict[str, Any]) -> None:
    if (z := _parallel(out.get("premise"), premise_zh)):
        out["premise_zh"] = z


def _twin_execution(out: dict[str, Any]) -> None:
    h = (out.get("execution") or {}).get("liquidity_history")
    if isinstance(h, dict) and h.get("note") and (d := liquidity_note_zh(h["note"])):
        h["note_zh"] = d


def _twin_portfolio(out: dict[str, Any]) -> None:
    p = out.get("portfolio")
    if not isinstance(p, dict):
        return
    if (z := _parallel(p.get("notes"), book_note_zh)):
        p["notes_zh"] = z
    st = p.get("stress")
    if not isinstance(st, dict):
        return
    if (z := _parallel(st.get("notes"), book_note_zh)):
        st["notes_zh"] = z
    for c in st.get("crashes") or []:
        if isinstance(c, dict) and c.get("key") in CRASH_ZH:
            c["name_zh"] = CRASH_ZH[c["key"]]
    for plan in st.get("plans") or []:
        if not isinstance(plan, dict):
            continue
        if plan.get("detail") and (d := book_note_zh(plan["detail"])):
            plan["detail_zh"] = d
        if (z := _parallel(plan.get("notes"), book_note_zh)):
            plan["notes_zh"] = z


def _twin_provenance(out: dict[str, Any]) -> None:
    items = (out.get("provenance") or {}).get("items")
    if not isinstance(items, dict):
        return

    def one(e: Any) -> None:  # noqa: ANN401
        if not isinstance(e, dict):
            return
        for k in ("source", "feed"):
            if isinstance(e.get(k), str) and (d := source_zh(e[k])):
                e[f"{k}_zh"] = d

    for e in items.values():
        if isinstance(e, dict) and "kind" not in e:
            for sub in e.values():  # the per-preset entries
                one(sub)
        else:
            one(e)
