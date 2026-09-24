"""Testing the trader's own plan against the data, where it can be tested.

The gate asks for a written plan - why the trade, and what would prove it wrong - and
until now it only checked that the words were there. A plan is more useful than that.
"Wrong if it closes below 350" is a price level, and the desk knows how far away it is
and how often past moments like this one crossed it inside the same hold. "Wrong if it
loses the 30-day average" is a level the desk already computes. "Wrong if it drops 5%"
is a move the analog paths can be counted against.

So the invalidation is read for those three shapes. What cannot be read is said to be
untested rather than guessed at: a plan is the trader's, and a desk that pretends to
have evaluated a sentence it could not parse is worse than one that says so.

The reason for the trade gets one check, deliberately narrow: whether it reads the
opposite way to the position ("weakness into the close" on a long). A mismatch is often
a typo in the side, which is an expensive typo, and is flagged - never scored.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

HOURS_PER_DAY = 24

_LEVEL = re.compile(r"(?:below|under|beneath|breaks?|loses?|through|above|over|past|reclaims?|at)\s+\$?\s*(\d[\d,]*(?:\.\d+)?)\b(?!\s*%)", re.I)
_BARE_LEVEL = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)|\b(\d{2,}(?:\.\d+)?)\b(?!\s*(?:%|-?\s*day|d\b|dma|h\b|hours?))", re.I)
_MA = re.compile(r"(\d{1,3})\s*[- ]?\s*(?:day|d)\s*(?:simple\s+)?(?:moving\s+)?(?:average|avg|ma|sma)\b|(\d{1,3})\s*dma\b|(?:moving\s+)?average", re.I)
_PCT = re.compile(r"(?:drops?|falls?|loses?|down|declines?|slides?|rises?|rallies|up|gains?)\s+(?:by\s+|more than\s+|over\s+)?(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*(?:drop|fall|decline|move|loss|lower|down|up|higher|rally|gain)", re.I)

# The same three shapes as a Chinese trader writes them.
_LEVEL_ZH_DOWN = re.compile(r"(?:跌破|跌穿|跌到|跌至|低于|破)\s*\$?\s*(\d[\d,]*(?:\.\d+)?)")
_LEVEL_ZH_UP = re.compile(r"(?:涨破|突破|涨到|涨至|高于|站上)\s*\$?\s*(\d[\d,]*(?:\.\d+)?)")
_MA_ZH = re.compile(r"(\d{1,3})\s*(?:日|天)\s*(?:均线|平均线|移动平均)")
_PCT_ZH = re.compile(r"(?:跌|下跌|跌幅|回撤|涨|上涨|涨幅)\s*(?:超过|达到)?\s*(\d+(?:\.\d+)?)\s*%")

_BULLISH = re.compile(r"\b(?:strength|strong|bullish|breakout|rally|rallies|momentum up|higher|upside|beat|squeeze|bounce|rebound|buy(?:ers|ing)? the dip|uptrend)\b", re.I)
_BEARISH = re.compile(r"\b(?:weakness|weak|bearish|breakdown|sell[- ]?off|selloff|lower|downside|miss|dump|fade|crash|downtrend|overbought|topping)\b", re.I)


@dataclass
class PlanCheck:
    invalidation: str
    kind: str  # "level" | "moving_average" | "move" | "wrong_side" | "untested"
    level: float | None = None  # the price that proves it wrong, when there is one
    distance_pct: float | None = None  # from the current price, signed
    crossed: int | None = None  # past moments like this that crossed it inside the hold
    of: int | None = None
    already: bool = False  # the line is already crossed at the current price
    note: str = ""
    thesis_mismatch: str = ""  # the reason reads the opposite way to the position

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _moving_average(frame: pd.DataFrame, days: int) -> float | None:
    close = frame["spot_close"].dropna() if "spot_close" in frame.columns else pd.Series(dtype=float)
    h = days * HOURS_PER_DAY
    if len(close) < h // 2:
        return None
    return float(close.iloc[-h:].mean())


def _paths_crossing(paths: Any, move_pct: float, *, downward: bool) -> tuple[int, int] | None:  # noqa: ANN401
    """How many analog paths moved at least ``move_pct`` from entry inside the hold."""
    rows = [p.values for p in getattr(paths, "paths", None) or [] if p.values]
    if not rows:
        return None
    if downward:
        hit = sum(1 for v in rows if min(v) <= move_pct)
    else:
        hit = sum(1 for v in rows if max(v) >= move_pct)
    return hit, len(rows)


def _thesis_mismatch(thesis: str, long: bool) -> str:
    bull, bear = bool(_BULLISH.search(thesis or "")), bool(_BEARISH.search(thesis or ""))
    if long and bear and not bull:
        return "the reason given reads bearish, but the position is long - check the direction"
    if not long and bull and not bear:
        return "the reason given reads bullish, but the position is short - check the direction"
    return ""


def check(invalidation: str, thesis: str, *, long: bool, price: float | None, frame: pd.DataFrame, paths: Any = None) -> PlanCheck | None:  # noqa: ANN401
    """Read the invalidation for a testable level, and measure it. None if there is no plan."""
    text = (invalidation or "").strip()
    mismatch = _thesis_mismatch(thesis, long)
    if not text:
        return PlanCheck(invalidation="", kind="untested", thesis_mismatch=mismatch) if mismatch else None
    out = PlanCheck(invalidation=text, kind="untested", thesis_mismatch=mismatch)
    # Which way "wrong" is: a long is proved wrong by a fall, a short by a rise.
    downward = long

    pct = _PCT.search(text) or _PCT_ZH.search(text)
    ma = _MA.search(text) or _MA_ZH.search(text)
    level = _LEVEL.search(text) or _LEVEL_ZH_DOWN.search(text) or _LEVEL_ZH_UP.search(text)
    if pct:
        move = _num(next(g for g in pct.groups() if g))
        signed = -move if downward else move
        out.kind, out.distance_pct = "move", signed
        crossed = _paths_crossing(paths, signed, downward=downward)
        if crossed:
            out.crossed, out.of = crossed
        return out
    if ma:
        days = int(next((g for g in ma.groups() if g), 30))
        value = _moving_average(frame, days)
        if value is not None and price:
            out.kind, out.level = "moving_average", value
            out.note = f"{days}-day average"
    elif level and price:
        out.kind, out.level = "level", _num(level.group(1))
    elif price:
        bare = _BARE_LEVEL.search(text)
        if bare:
            candidate = _num(bare.group(1) or bare.group(2))
            # A number within half the price either way is a price level; anything else
            # (a date, a count) is not one this can read.
            if 0.5 * price <= candidate <= 1.5 * price:
                out.kind, out.level = "level", candidate
    if out.level is not None and price:
        out.distance_pct = (out.level / price - 1.0) * 100.0
        if out.kind == "level" and (out.level > price if downward else out.level < price):
            # A long proved wrong by a price above it is describing a target; counting
            # "crossings" of it would count the moves the trader wants.
            out.kind, out.note = "wrong_side", "above" if downward else "below"
            return out
        out.already = out.level > price if downward else out.level < price
        crossed = _paths_crossing(paths, out.distance_pct, downward=downward)
        if crossed and not out.already:
            out.crossed, out.of = crossed
    return out


def describe(c: PlanCheck, lang: str = "en") -> str:
    """One sentence about the plan, built from the check's own fields."""
    zh = lang == "zh"
    bits = []
    if c.kind == "untested" and c.invalidation:
        bits.append("你的“错误条件”无法用数据检验，仅作为你的备注保留。" if zh else "Your invalidation is not something the desk can test against data; it stays as your note.")
    elif c.kind in ("level", "moving_average") and c.level is not None and c.distance_pct is not None:
        what = (f"{c.note} ({c.level:,.2f})" if c.note else f"{c.level:,.2f}")
        if c.already:
            bits.append(f"你的错误条件（{what}）按现价已经触发。" if zh else f"Your invalidation ({what}) is already crossed at the current price.")
        else:
            line = (f"你的错误条件（{what}）距现价 {abs(c.distance_pct):.1f}%" if zh else f"Your invalidation ({what}) is {abs(c.distance_pct):.1f}% away")
            if c.crossed is not None:
                line += (f"；过去 {c.of} 个相似时刻中有 {c.crossed} 个在持有期内越过它。" if zh else f"; {c.crossed} of {c.of} past moments like this crossed it inside the hold.")
            else:
                line += "。" if zh else "."
            bits.append(line)
    elif c.kind == "wrong_side" and c.level is not None:
        side_zh = "上方" if c.note == "above" else "下方"
        bits.append(
            f"你的错误条件 {c.level:,.2f} 在现价{side_zh}——对这个方向来说它更像目标价，而不是证明你错了的价位。" if zh
            else f"Your invalidation {c.level:,.2f} is {c.note} the current price - for this direction that reads like a target, not what would prove you wrong."
        )
    elif c.kind == "move" and c.distance_pct is not None:
        line = (f"你的错误条件是 {abs(c.distance_pct):.1f}% 的不利波动" if zh else f"Your invalidation is a {abs(c.distance_pct):.1f}% adverse move")
        if c.crossed is not None:
            line += (f"；过去 {c.of} 个相似时刻中有 {c.crossed} 个在持有期内出现过。" if zh else f"; {c.crossed} of {c.of} past moments like this saw one inside the hold.")
        else:
            line += "。" if zh else "."
        bits.append(line)
    if c.thesis_mismatch:
        bits.append("注意：你给出的理由看空，但仓位是做多——请核对方向。" if zh and "bearish" in c.thesis_mismatch else
                    "注意：你给出的理由看多，但仓位是做空——请核对方向。" if zh else f"Note: {c.thesis_mismatch}.")
    return " ".join(bits)
