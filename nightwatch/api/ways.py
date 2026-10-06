"""Ways to hold it: the same idea run several ways, side by side, and the safest go picked.

"What's the safest way to hold NVDA over the weekend?" is a question no single report
answers: it asks for a comparison across versions of the trade. The desk already has
every tool for each version - the whole pipeline re-runs for a changed ticket - so this
runs a fixed set of versions against the same moment and lays them out in one table.

The versions are chosen by rule, not by a model: as asked, half the size, the shorter
hold, half of it hedged on the perpetual, and, for a leveraged ticket, the same trade
without leverage. The pick is also a rule: among versions the desk calls GO, the one
whose one-in-twenty loss costs the least money; if none is a GO, the one that comes
closest, and it says so. Every number in the table is a field of one of the reports.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from nightwatch.decision.ticket import HorizonKind
from nightwatch.time_utils import whole_hours

ASKS = re.compile(
    r"\bsafest\b|\bbest way\b|\bcompare\b.*\b(?:ways|options|versions|holds?)\b|\b(?:ways|options) to (?:hold|do|play|take)\b|\balternatives?\b"
    r"|最安全|比较.*方案|有哪些方案|怎么持有",
    re.I,
)
_VERDICT_RANK = {"GO": 0, "HEDGE": 1, "REDUCE_TO": 2, "REVIEW": 3, "NO_GO": 4}


def versions(base: Any) -> list[tuple[str, Any]]:  # noqa: ANN401 - a TradeTicket
    out = [("As asked", base), ("Half the size", replace(base, notional_quote=base.notional_quote / 2))]
    hours = base.horizon_hours if base.horizon_kind == HorizonKind.HOURS else None
    if hours and hours > 30:
        out.append(("Shorter hold: to the next open", replace(base, horizon_kind=HorizonKind.NEXT_OPEN, horizon_hours=None, extra={})))
    elif base.horizon_kind == HorizonKind.NEXT_OPEN:
        out.append(("Shorter hold: to the end of this session or closed window", replace(base, horizon_kind=HorizonKind.WINDOW_END, horizon_hours=None)))
    if not base.leveraged:
        # A leveraged position is already on the perpetual; offering to half-hedge it onto
        # the same instrument it is already trading is not a distinct version of the trade.
        out.append(("Half hedged on the perpetual", replace(base, hedge_ratio=0.5)))
    if base.leveraged:
        out.append(("Without leverage", replace(base, leverage=None)))
    return out


def _row(label: str, r: Any) -> dict[str, Any]:  # noqa: ANN401 - an AnalysisReport
    h = r.analog.horizons.get(r.primary_horizon) if r.analog else None
    p5 = None
    if h is not None and not h.cohort.insufficient:
        p5 = h.loss_p5_pct
    size = r.verdict.recommended_notional if r.verdict.recommended_notional is not None else r.ticket.notional_quote
    priced = [i for i in r.stress.impacts if i.total_pnl_quote is not None]
    worst = min((i.total_pnl_quote for i in priced), default=None)
    lev = getattr(r, "leverage", None) or {}
    margin = lev.get("margin_quote") if lev.get("liquidation_distance_pct") is not None else None
    if margin and worst is not None:
        worst = max(worst, -margin)
    q = r.execution.exit_quote
    hedge = float(r.ticket.hedge_ratio or 0.0)
    if hedge and p5 is not None:
        # The perpetual offsets the price move on the hedged share; the history's loss line
        # is the unhedged token's, so only the unhedged share carries it. What is left on
        # the hedged share is the basis between token and perp, priced separately below.
        p5 = p5 * (1.0 - hedge)
    return {
        "label": label, "verdict": r.verdict.verdict.value, "size": size, "hours": r.horizon_h,
        "p5_pct": p5, "p5_quote": (p5 / 100.0 * size) if p5 is not None else None,
        "worst_quote": worst, "exit_bps": q.total_cost_bps if q is not None else None,
        "liquidation_pct": lev.get("liquidation_distance_pct"),
        "hedge_bps": r.execution.hedge_quote.total_cost_bps_of_position if (r.ticket.hedge_ratio and r.execution.hedge_quote) else None,
    }


def pick(rows: list[dict[str, Any]], size: float) -> dict[str, Any] | None:
    """The safest version at the size the trader asked for.

    Among full-size GO versions, the one whose one-in-twenty loss is the smallest share of
    the position. "Half the size" is left out of this pick on purpose: less money always
    risks less money, which is true and not an answer; it is said separately.
    """
    full = [x for x in rows if x["label"] != "Half the size" and abs(x["size"] - size) < 1.0 and x["p5_pct"] is not None]
    go = [x for x in full if x["verdict"] == "GO"]
    if go:
        return max(go, key=lambda x: x["p5_pct"])
    ranked = sorted(full or rows, key=lambda x: (_VERDICT_RANK.get(x["verdict"], 9), -(x["p5_pct"] if x["p5_pct"] is not None else -1e9)))
    return ranked[0] if ranked else None


def _usd(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.0f}"


LABEL_ZH = {
    "As asked": "按原计划", "Half the size": "仓位减半", "Shorter hold: to the next open": "缩短持有：到下一次开盘",
    "Shorter hold: to the end of this session or closed window": "缩短持有：到本时段结束",
    "Half hedged on the perpetual": "用永续合约对冲一半", "Without leverage": "不加杠杆",
}
VERDICT_ZH = {"GO": "可以做", "REDUCE_TO": "建议减仓", "HEDGE": "建议对冲", "REVIEW": "需要复核", "NO_GO": "不建议做"}


def _zh(base: Any, rows: list[dict[str, Any]], best: dict[str, Any] | None, half: dict[str, Any] | None) -> str:  # noqa: ANN401
    """The same table in Chinese; the numbers are the same fields."""
    lines = [f"同一个{'做多' if base.side.value == 'long' else '做空'} {base.ticker} 的想法，按 {len(rows)} 种方式在同一时刻重新计算："]
    for x in rows:
        bits = [f"{VERDICT_ZH.get(x['verdict'], x['verdict'])}，{_usd(x['size'])} USDT", f"持有 {whole_hours(x['hours'])} 小时"]
        if x["p5_quote"] is not None:
            bits.append(f"二十分之一的坏情况 {_usd(x['p5_quote'])} USDT（{x['p5_pct']:+.1f}%）" + ("，只计未对冲的一半" if x["hedge_bps"] is not None else ""))
        if x["worst_quote"] is not None:
            bits.append(f"最坏压力情景 {_usd(x['worst_quote'])} USDT")
        if x["exit_bps"] is not None:
            bits.append(f"平仓 {x['exit_bps']:.0f} bps")
        if x["hedge_bps"] is not None:
            bits.append(f"对冲成本 {x['hedge_bps']:.0f} bps")
        if x["liquidation_pct"] is not None:
            bits.append(f"强平线距现价 {x['liquidation_pct']:.1f}%")
        lines.append(f"- {LABEL_ZH.get(x['label'], x['label'])}：" + "，".join(bits))
    lines.append("")
    if best is not None and best["verdict"] == "GO":
        lines.append(f"保持你的仓位不变，仍可直接做的最安全方案是：{LABEL_ZH.get(best['label'], best['label'])}（二十分之一的坏情况为仓位的 {best['p5_pct']:+.1f}%）。")
    elif best is not None:
        lines.append(f"按你的仓位，没有一个方案能直接做。最接近的是：{LABEL_ZH.get(best['label'], best['label'])}（{VERDICT_ZH.get(best['verdict'], best['verdict'])}）。")
    if half is not None and half["p5_quote"] is not None:
        lines.append(f"或者少冒点钱：仓位减半后，二十分之一的坏情况是 {_usd(half['p5_quote'])} USDT。")
    lines.append("每个数字都来自对系统的完整重新计算，没有估算。")
    return "\n".join(lines)


def answer(state: Any, context: dict[str, Any], lang: str = "en") -> dict[str, Any] | None:  # noqa: ANN401
    from nightwatch.api import whatif
    from nightwatch.pipeline.analyze import analyze

    base = whatif.ticket_from(context)
    if base is None:
        return None
    as_of = whatif.as_of_of(context)
    rows = []
    with state.lock:
        for label, ticket in versions(base):
            try:
                rows.append(_row(label, analyze(state.ctx, ticket, as_of=as_of, record=False)))
            except Exception:  # noqa: BLE001 - one version failing must not lose the others
                continue
    if not rows:
        return None
    best = pick(rows, base.notional_quote)
    half = next((x for x in rows if x["label"] == "Half the size"), None)
    zh = lang == "zh"
    lines = []
    for x in rows:
        bits = [f"{x['verdict'].replace('_', ' ')} at {_usd(x['size'])} USDT", f"held {whole_hours(x['hours'])}h"]
        if x["p5_quote"] is not None:
            on = " on the unhedged half" if x["hedge_bps"] is not None else ""
            bits.append(f"1-in-20 loss {_usd(x['p5_quote'])} USDT ({x['p5_pct']:+.1f}%){on}")
        if x["worst_quote"] is not None:
            bits.append(f"worst stress {_usd(x['worst_quote'])} USDT")
        if x["exit_bps"] is not None:
            bits.append(f"exit {x['exit_bps']:.0f} bps")
        if x["hedge_bps"] is not None:
            bits.append(f"hedge costs {x['hedge_bps']:.0f} bps")
        if x["liquidation_pct"] is not None:
            bits.append(f"liquidation {x['liquidation_pct']:.1f}% away")
        lines.append(f"- {x['label']}: " + ", ".join(bits))
    if best is not None and best["verdict"] == "GO":
        verdict = (f"Keeping your size, the safest version the desk still calls a go is {best['label'].lower()}: "
                   f"its one-in-twenty loss is {best['p5_pct']:+.1f}% of the position.")
    elif best is not None:
        verdict = f"At your size none of these is a straight go. The closest is {best['label'].lower()}, at {best['verdict'].replace('_', ' ')}."
    else:
        verdict = "None of these could be priced."
    if half is not None and half["p5_quote"] is not None:
        verdict += f" Or risk less money: half the size puts the one-in-twenty loss at {_usd(half['p5_quote'])} USDT."
    head = f"The same {base.side.value} {base.ticker} idea, run {len(rows)} ways against the same moment:"
    text = "\n".join([head, *lines, "", verdict, "Every number is from a full re-run of the desk; nothing is estimated."])
    if zh:
        text = _zh(base, rows, best, half)
    return {
        "intent": {"kind": "ways", "missing_fields": [], "reply": text},
        "ticket": None, "report": None, "report_text": None, "narrative": text, "unverified_numbers": [],
        "reply": text, "mode": "ways", "ways": rows, "answered_about": context.get("forecast_id"),
    }
