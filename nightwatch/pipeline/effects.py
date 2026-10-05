"""What each source did: for every source a report used, what it supplied and whether it
CHANGED the answer.

Built from the pipeline's own decisions, never from narrative: the binding size cap, the
worst severe stress preset (and which source it was calibrated on), the flags that were
raised, the presets that exist. Four effects, strongest first:

* ``moved_size``   the recommended size is below the requested one because of this source
* ``set_preset``   the source built or priced a stress preset or a measurement the report
                   shows, without being what limited the size
* ``raised_flag``  the source put a caution or warning on the report
* ``context``      shown beside the answer; nothing in the answer depends on it

A source is never credited with more than the numbers show. The size is "moved" only when
the verdict really cut it (more than 5% below the request) and the cap that bound is the
one this source feeds.
"""

from __future__ import annotations

from typing import Any

CUT_TOLERANCE = 0.05  # the verdict's own "within every cap" tolerance

MOVED, PRESET, FLAG, CONTEXT = "moved_size", "set_preset", "raised_flag", "context"

# Presets whose number comes from a stored history, by id prefix -> the sources it was cut from.
_HISTORY_SOURCES = {
    "closed_window_gap": ("bitget_candles", "bitget_perp"),
    "vol_spike": ("bitget_candles", "bitget_perp", "features"),
    "basis_blowout": ("bitget_candles", "yahoo_bars"),
    "earnings_gap": ("nasdaq_earnings", "yahoo_bars"),
    "replay_": ("yahoo_bars",),
    "analog_p5_floor": ("bitget_candles", "features"),
    "funding_spike": ("bitget_perp",),
}


def _worst_severe(report: Any) -> str | None:  # noqa: ANN401
    """The id of the severe preset that costs the most at the requested size."""
    best: tuple[float, str] | None = None
    for sc, im in zip(report.stress.presets, report.stress.impacts, strict=False):
        pct = im.total_pct_of_notional
        if pct is None or getattr(sc.severity, "value", sc.severity) != "severe":
            continue
        if best is None or pct < best[0]:
            best = (pct, sc.id)
    return best[1] if best else None


def _history_sources(preset_id: str | None) -> tuple[str, ...]:
    for prefix, kinds in _HISTORY_SOURCES.items():
        if preset_id and preset_id.startswith(prefix):
            return kinds
    return ()


def _n(x: Any) -> int:  # noqa: ANN401
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def build(report: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    """One row per source in ``report.sources``: kind, label, supplied, effect, note (each with a ``_zh``)."""
    requested = float(report.ticket.notional_quote)
    rec = report.verdict.recommended_notional
    cut = rec is not None and rec < requested * (1.0 - CUT_TOLERANCE)
    binding = getattr(report.sizing, "binding_cap", None)
    worst = _worst_severe(report)
    presets = {p.id for p in report.stress.presets}
    summary = report.stress.inputs_summary or {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def row(src: dict[str, Any], effect: str, supplied: tuple[str, str], note: tuple[str, str]) -> None:
        rows.append({"kind": src["kind"], "label": src.get("label"), "effect": effect, "supplied": supplied[0], "supplied_zh": supplied[1],
                     "note": note[0], "note_zh": note[1]})

    def history_effect(kind: str) -> tuple[str, tuple[str, str]]:
        """How a history-fed source did its work: it fed the cap that bound, or it built presets."""
        if cut and binding in ("risk_budget", "book_tail", "regime") and kind in ("bitget_candles", "features"):
            return MOVED, (f"The {binding.replace('_', ' ')} limit that cut the size is measured on it.", f"压低仓位的{ {'risk_budget': '风险预算', 'book_tail': '整体持仓尾部风险', 'regime': '市场状态'}[binding] }上限由它测得。")
        if cut and binding == "stress" and kind in _history_sources(worst):
            return MOVED, (f"The stress limit that cut the size is sized on {worst.replace('_', ' ')}, built from it.", f"压低仓位的压力上限按「{worst}」设定，该情景由它构建。")
        if kind in ("bitget_candles", "yahoo_bars", "features", "bitget_perp"):
            return PRESET, ("It calibrated the stress presets and the history comparison; they did not cut the size.", "它用于校准压力情景和历史对比；这些没有压低仓位。")
        return CONTEXT, ("", "")

    for src in report.sources:
        kind = src.get("kind")
        if not kind or kind in seen:
            continue
        seen.add(kind)
        rows_used = _n(src.get("rows_used"))
        if kind == "orderbook":
            lv = _n(src.get("levels"))
            eq = report.execution.exit_quote
            cost = f", exit cost {eq.total_cost_bps:.0f} bps at the requested size" if eq is not None and eq.total_cost_bps is not None else ""
            cost_zh = f"，按请求仓位平仓成本 {eq.total_cost_bps:.0f} 个基点" if eq is not None and eq.total_cost_bps is not None else ""
            if cut and binding == "exit_liquidity":
                row(src, MOVED, (f"{lv} live price levels{cost}.", f"{lv} 档实时盘口{cost_zh}。"), ("The size is held to what this book absorbs within the exit-cost budget.", "仓位被限制在该盘口能在平仓成本预算内承接的范围。"))
            else:
                row(src, PRESET, (f"{lv} live price levels{cost}.", f"{lv} 档实时盘口{cost_zh}。"), ("It priced the exit and the liquidity-drought preset; the book was deep enough not to cut the size.", "用它计算平仓成本和流动性枯竭情景；盘口足够深，没有压低仓位。"))
        elif kind in ("bitget_candles", "yahoo_bars", "features"):
            what = {"bitget_candles": (f"{rows_used} hourly token candles.", f"{rows_used} 根代币小时 K 线。"),
                    "yahoo_bars": (f"{rows_used} stock bars (the underlying's own price history).", f"{rows_used} 根正股 K 线（标的自身价格历史）。"),
                    "features": ("Features computed from the stored history and the regime label.", "由存储的历史数据计算的特征及市场状态标签。")}[kind]
            eff, note = history_effect(kind)
            row(src, eff, what, note if eff != CONTEXT else ("", ""))
        elif kind == "bitget_perp":
            eff, note = history_effect(kind)
            fund = "funding_spike" in presets
            row(src, eff if eff == MOVED or fund else CONTEXT,
                (f"{rows_used} perp candles and funding rows.", f"{rows_used} 条永续 K 线和资金费率记录。"),
                note if (eff == MOVED or fund) else ("Shown for the hedge and the leverage section; nothing in the size depends on it.", "用于对冲和杠杆部分；仓位不依赖它。"))
        elif kind == "bitget_margin_tiers":
            lev = report.leverage or {}
            hit = lev.get("presets_hit") or []
            liq = lev.get("liquidation_price")
            if liq is not None and (hit or (lev.get("analog_hits") or 0) > 0):
                row(src, FLAG, (f"{rows_used} margin tiers, which fix the liquidation price.", f"{rows_used} 档保证金等级，用于确定强平价。"),
                    (f"The liquidation price {liq:,.2f} is inside what the stress presets or past moments reached.", f"强平价 {liq:,.2f} 落在压力情景或历史走势所到达的范围内。"))
            else:
                row(src, PRESET if liq is not None else CONTEXT, (f"{rows_used} margin tiers.", f"{rows_used} 档保证金等级。"),
                    ("They fix the liquidation price shown in the leverage section; no tested move reached it.", "用于确定杠杆部分显示的强平价；测试的走势均未触及。"))
        elif kind == "nasdaq_earnings":
            inside = bool(summary.get("earnings_in_window"))
            if inside and cut and binding == "stress" and worst and worst.startswith("earnings_gap"):
                row(src, MOVED, ("The next report date.", "下一次财报日期。"), ("A report falls inside the hold, so the earnings-gap presets apply, and the worst of them is what sized the stress limit.", "持有期内有财报，因此启用财报跳空情景；其中最坏的一个决定了压力上限。"))
            elif inside:
                row(src, PRESET, ("The next report date.", "下一次财报日期。"), ("A report falls inside the hold, so the earnings-gap presets were added; they did not cut the size.", "持有期内有财报，因此加入了财报跳空情景；它们没有压低仓位。"))
            else:
                row(src, CONTEXT, ("The next report date.", "下一次财报日期。"), ("No report inside the hold, so no earnings preset.", "持有期内没有财报，因此没有财报情景。"))
        elif kind == "bitget_mcp":
            street = report.street or {}
            if src.get("status") in ("unavailable", "last_good") or street.get("stale"):
                row(src, FLAG, ("Analyst, insider and live-quote context from Bitget.", "来自 Bitget 的分析师、内部人和实时报价信息。"), ("It was down or stale, and the report says so in its warnings.", "该数据源不可用或已过期，报告的警告中已说明。"))
            elif any("calendar puts the next" in w for w in report.warnings):
                row(src, FLAG, ("Analyst, insider and live-quote context from Bitget.", "来自 Bitget 的分析师、内部人和实时报价信息。"), ("Its earnings date disagrees with Nasdaq's; the report raised a warning.", "其财报日期与 Nasdaq 不一致；报告已给出警告。"))
            else:
                row(src, CONTEXT, ("Analyst, insider and live-quote context from Bitget.", "来自 Bitget 的分析师、内部人和实时报价信息。"), ("Shown beside the answer; checked against the desk's own price, no disagreement.", "显示在答案旁；已与自有价格核对，未发现分歧。"))
        elif kind == "bitget_signal":
            sig = report.signal or {}
            flag = sig.get("flag") or sig.get("caution")
            if flag:
                row(src, FLAG, ("Bitget's technical-analysis skill, cross-checked against the desk's own RSI.", "Bitget 技术分析 Skill，已与自有 RSI 交叉核对。"), (str(flag), str(flag)))
            else:
                row(src, CONTEXT, ("Bitget's technical-analysis skill, cross-checked against the desk's own RSI.", "Bitget 技术分析 Skill，已与自有 RSI 交叉核对。"), ("It agreed with the desk's own reading; nothing changed.", "与自有读数一致，没有改变任何结论。"))
        elif kind == "bitget_open_interest":
            oi = report.open_interest or {}
            if oi.get("crowded"):
                row(src, FLAG, ("Open interest on the perp now and 24 h ago.", "永续合约当前及 24 小时前的未平仓量。"), (f"{oi.get('crowded_line')}: a caution on the report; the size is unchanged.", f"{oi.get('crowded_line')}：已在报告中提示谨慎；仓位未变。"))
            else:
                row(src, CONTEXT, ("Open interest on the perp now and 24 h ago.", "永续合约当前及 24 小时前的未平仓量。"), ("Not unusually high against its own history; nothing raised.", "相对自身历史并不异常偏高；未触发提示。"))
        elif kind == "cboe_options":
            o = report.options or {}
            mv = o.get("implied_move_pct")
            sup = (f"The options-implied move over the hold: ±{mv:.1f}%." if mv is not None else "The options-implied move over the hold.", f"期权隐含的持有期波动：±{mv:.1f}%。" if mv is not None else "期权隐含的持有期波动。")
            if o.get("sizing_binding") and cut and binding == "stress" and worst == "options_implied_move":
                row(src, MOVED, sup, ("The options market expects more than history, so the stress limit was sized on it and the size came down.", "期权市场预期的波动超过历史，因此压力上限按它设定，仓位被压低。"))
            elif o.get("sizing_binding"):
                row(src, PRESET, sup, ("The options market expects more than history, so it is now the worst severe stress preset; another limit still bound the size.", "期权市场预期的波动超过历史，因此它成为最坏的严重压力情景；但另有其他上限更紧。"))
            else:
                row(src, CONTEXT, sup, ("Within history's severe moves, so the size is the same with or without it.", "未超过历史上的严重波动，有无它仓位都一样。"))
        elif kind == "corporate_events":
            ce = report.corporate_events or {}
            if ce.get("in_hold"):
                row(src, FLAG, ("Dividends, splits and Bitget notices around the hold.", "持有期前后的分红、拆股和 Bitget 公告。"), ("An event falls inside the hold; the report says how it is not verified for rToken holders.", "持有期内有事件；报告已说明其对 rToken 持有人的处理方式未经核实。"))
            else:
                row(src, CONTEXT, ("Dividends, splits and Bitget notices around the hold.", "持有期前后的分红、拆股和 Bitget 公告。"), ("Nothing falls inside the hold.", "持有期内没有相关事件。"))
        elif kind == "sec_edgar":
            n = len(report.filings or [])
            if n:
                row(src, FLAG, (f"{n} recent filing{'s' if n != 1 else ''} not yet priced.", f"{n} 份尚未被市场消化的近期文件。"), ("Listed with what past filings of the same kind did to the price.", "与同类文件过去对价格的影响一并列出。"))
            else:
                row(src, CONTEXT, ("Recent filings.", "近期文件。"), ("No filing in the last 72 h.", "最近 72 小时没有新文件。"))
        elif kind == "fred_macro":
            row(src, CONTEXT, ("The release calendar for the hold.", "持有期内的数据发布日历。"), ("Shown beside the answer.", "显示在答案旁。"))
        elif kind == "rss_news":
            row(src, CONTEXT, (f"{rows_used} recent headline{'s' if rows_used != 1 else ''}.", f"{rows_used} 条近期新闻标题。"), ("Shown beside the answer; headlines are not scored.", "显示在答案旁；新闻标题不参与评分。"))
        else:
            row(src, CONTEXT, (src.get("label") or kind, src.get("label") or kind), ("Shown beside the answer.", "显示在答案旁。"))
    return rows
