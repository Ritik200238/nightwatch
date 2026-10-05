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
