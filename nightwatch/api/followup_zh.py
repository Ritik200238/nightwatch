"""Answering a question about the report, in Chinese.

The same rule as the English answers: every number is read from the report's own fields
and formatted the same way, so a Chinese reader and an English one are told the same
figures. Only the words around them differ. The questions traders ask most - how big,
where is the stop, how bad can it get, can I get out, what does history say, why the
review, what are analysts saying - are covered; anything else gets the Chinese menu of
what can be asked, rather than a guess.
"""

from __future__ import annotations

import re

from nightwatch.api.followup import Answer, _bps, _p5, _pct, _primary, _usd

VERDICT_ZH = {"GO": "可以做", "REDUCE": "建议减仓", "HEDGE": "建议对冲", "REVIEW": "需要复核", "NO_GO": "不建议做"}
RULE_ZH = {
    "written_plan": "书面计划", "stop": "止损", "position_size": "仓位大小", "market_posture": "市场状态",
    "liquidity": "流动性", "circuit_breaker": "熔断", "basis": "价差", "event": "事件", "data_quality": "数据质量",
    "liquidation": "强平风险", "exit_liquidity": "平仓流动性", "risk_budget": "风险预算", "concentration": "集中度",
    "revenge": "报复性交易冷静期", "regime": "市场状态",
}


def _v(r: dict) -> str:
    v = (r.get("verdict") or {}).get("verdict", "")
    return VERDICT_ZH.get(v, v)


def _a_size(r: dict, _q: str) -> Answer | None:
    sen = r.get("sensitivity") or {}
    sizing = r.get("sizing") or {}
    caps = [c for c in sizing.get("caps", []) if c.get("notional") is not None]
    binding = next((c for c in caps if c["name"] == sizing.get("binding_cap")), None)
    requested = (r.get("ticket") or {}).get("notional_quote")
    bits = []
    # "仓位减半" / "加倍": the sweep already ran the gate at that size.
    mult = 0.5 if re.search(r"减半|一半", _q) else 2.0 if re.search(r"加倍|翻倍", _q) else None
    sizes = sen.get("sizes") or []
    if mult and requested and sizes:
        target = requested * mult
        p = min(sizes, key=lambda x: abs(x["notional"] - target))
        near = "" if abs(p["notional"] - target) < max(1.0, target * 0.01) else f"（最接近 {_usd(target)} 的扫描点）"
        bits.append(f"仓位 {_usd(p['notional'])}{near} 时结论为 {VERDICT_ZH.get(p['verdict'], p['verdict'])}。")
        if p.get("exit_cost_bps") is not None:
            bits.append(f"平仓成本约 {p['exit_cost_bps']:.1f} bps。")
        if sen.get("max_go_notional") is not None:
            bits.append(f"最大仍可直接做的仓位是 {_usd(sen['max_go_notional'])}。")
        return Answer("size", "".join(bits), ("sensitivity sweep",))
    if binding and requested is not None and binding["notional"] < requested - 1:
        from nightwatch.api.intake import CAP_ZH

        bits.append(f"限制仓位的是{CAP_ZH.get(binding['name'], binding['name'].replace('_', ' '))}上限：{_usd(binding['notional'])}。")
    elif requested is not None:
        bits.append(f"{_usd(requested)} 没有被任何上限削减。")
    if sen.get("max_go_notional") is not None:
        bits.append(f"在整个仓位扫描中，最大仍可直接做的仓位是 {_usd(sen['max_go_notional'])}。")
    return Answer("size", "".join(bits), ("sizing caps", "sensitivity sweep")) if bits else None


def _a_stop(r: dict, _q: str) -> Answer | None:
    sen = r.get("sensitivity") or {}
    stop = (r.get("ticket") or {}).get("stop_price")
    bits = []
    if stop:
        bits.append(f"你的止损在 {stop:.2f}。")
    else:
        p5 = _p5(r)
        bits.append("你没有设止损，所以风险按校准后的第5百分位来计算" + (f"：持有期内 {_pct(p5)}" if p5 is not None else "") + "。")
    if sen.get("widest_stop_pct_for_requested_size") is not None:
        bits.append(f"这个仓位下，风险预算允许的最宽止损距离是 {sen['widest_stop_pct_for_requested_size']:.2f}%。")
    return Answer("stop", "".join(bits), ("ticket", "sensitivity sweep"))


def _a_worst(r: dict, _q: str) -> Answer | None:
    modes = [m for m in (r.get("failure_modes") or []) if m.get("loss_quote") is not None]
    if modes:
        from nightwatch.api.intake import FAILURE_ZH

        bits = ["按可能性乘以损失排序，这笔交易最主要的亏损方式："]
        for i, m in enumerate(modes[:3], 1):
            chance = f"，历史上约 {m['chance']:.0%} 的时候发生" if m.get("chance") is not None else ""
            capped = "（杠杆下会先被强平，亏损止于保证金）" if m.get("capped") else ""
            bits.append(f"{i}. {FAILURE_ZH.get(m['key'], m['title'])}：约 {_usd(m['loss_quote'])}（仓位 {_pct(m.get('loss_pct'))}）{chance}{capped}。")
        return Answer("worst", "".join(bits), ("failure modes",))
    st = r.get("stress") or {}
    rows = [(p, i) for p, i in zip(st.get("presets") or [], st.get("impacts") or [], strict=False) if i.get("total_pnl_quote") is not None]
    bits = []
    if rows:
        rows.sort(key=lambda x: x[1]["total_pnl_quote"])
        from nightwatch.api.intake import preset_zh

        bits.append("用这个代币自身历史构建的最坏三个情景：" + "；".join(f"{preset_zh(p['id'], p['name'])} 损失 {_usd(i['total_pnl_quote'])}（仓位 {_pct(i.get('total_pct_of_notional'))}）" for p, i in rows[:3]) + "。")
    mc = st.get("monte_carlo")
    if mc:
        bits.append(f"模拟中，二十条路径里最差的一条收在 {_pct(mc.get('p5'))} 以下，最差二十分之一的平均是 {_pct(mc.get('expected_shortfall_5_pct'))}。")
    return Answer("worst", "".join(bits), ("stress presets", "Monte Carlo")) if bits else None


def _a_exit(r: dict, _q: str) -> Answer | None:
    ex = r.get("execution") or {}
    q = ex.get("exit_quote")
    if q and q.get("total_cost_bps") is not None:
        text = f"平掉 {_usd(q.get('notional_quote'))} 的成本是 {_bps(q['total_cost_bps'])}，约 {_usd(q.get('total_cost_quote'))}，{'可以全部成交' if q.get('fully_filled') else '无法全部成交'}。"
    elif q:
        text = "以目前的盘口，这个仓位无法在任何价格全部平掉。"
    else:
        text = "没有可用于计算平仓成本的盘口。"
    if ex.get("max_notional_within_budget") is not None:
        text += f"在成本预算内还能平掉的最大仓位是 {_usd(ex['max_notional_within_budget'])}。"
    return Answer("exit", text, ("order book",))


def _a_history(r: dict, _q: str) -> Answer | None:
    h = _primary(r)
    if not h:
        return None
    c = h.get("cohort") or {}
    if c.get("insufficient") or not c.get("n"):
        return Answer("history", "相似的历史时刻不够多，无法回答。", ("analog cohort",))
    text = f"找到 {c['n']} 个与现在相似的历史时刻。{r.get('primary_horizon')} 内的中位结果是 {_pct(c.get('median_pct'))}，最差的二十分之一低于 {_pct(_p5(r))}"
    if c.get("win_rate") is not None:
        text += f"，{c['win_rate'] * 100:.0f}% 以上涨收尾"
    return Answer("history", text + "。", ("analog cohort",))


def _a_gate(r: dict, _q: str) -> Answer | None:
    rules = (r.get("gate") or {}).get("rules") or []
    failed = [x for x in rules if x.get("decision") != "GO"]
    if not failed:
        return Answer("gate", f"风控闸门全部 {len(rules)} 项检查都通过了，结论是{_v(r)}。如果仓位被削减，那是上限而不是规则；可以问“为什么不能更大”。", ("discipline gate",))
    names = "、".join(RULE_ZH.get(x["rule"], x["rule"].replace("_", " ")) for x in failed)
    text = f"{len(rules)} 项检查中有 {len(failed)} 项未通过：{names}。"
    if any(x["rule"] == "written_plan" for x in failed):
        text += "要通过复核：告诉我你为什么做这笔交易，以及什么情况说明你错了。"
    return Answer("gate", text, ("discipline gate",))


def _a_street(r: dict, _q: str) -> Answer | None:
    s = r.get("street") or {}
    if not s:
        return Answer("street", "这份报告没有 Bitget 的美股数据：服务暂时不可用，或这是过去的时刻。", ())
    bits = []
    if s.get("token_vs_live_bps") is not None:
        bits.append(f"代币价格与正股实时价格相差 {s['token_vs_live_bps']:+.0f} bps。")
    if s.get("n_firms"):
        bits.append(f"过去90天有 {s['n_firms']} 家机构给出评级：买入 {s['bullish']}、持有 {s['neutral']}、卖出 {s['bearish']}")
        bits.append(f"，目标价中位数 ${s['median_target']:,.0f}。" if s.get("median_target") else "。")
    if s.get("insider_sells") or s.get("insider_buys"):
        bits.append(f"过去90天内部人公开市场卖出 {s.get('insider_sells', 0)} 次、买入 {s.get('insider_buys', 0)} 次。")
    if s.get("mood_score") is not None:
        bits.append(f"市场恐慌贪婪指数 {s['mood_score']:.0f}。")
    bits.append("这些都没有影响仓位建议——它们还没有经过隔夜走势的检验。")
    return Answer("street", "".join(bits), ("Bitget US-stock data",))


def _a_hedge(r: dict, _q: str) -> Answer | None:
    hq = (r.get("execution") or {}).get("hedge_quote")
    if not hq:
        return Answer("hedge", "这个代币没有永续合约报价，无法计算对冲成本。", ("hedge quote",))
    return Answer(
        "hedge",
        f"通过 {hq.get('perp_symbol')} 全额对冲的成本是仓位的 {_bps(hq.get('total_cost_bps_of_position'))}，剩余价差风险的第95百分位是 {_bps(hq.get('residual_basis_p95_bps'))}。",
        ("hedge quote",),
    )


def _a_shock(r: dict, q: str) -> Answer | None:
    """"如果跌 10% 呢": the same arithmetic as the English answer, in Chinese."""
    from nightwatch.api.followup import _UP, SHOCK

    m = SHOCK.search(q)
    if not m:
        return None
    size = float(next(g for g in m.groups() if g))
    t = r.get("ticket") or {}
    notional = t.get("notional_quote")
    if not notional or not 0 < size < 100:
        return None
    long_ = (t.get("side") or "long") == "long"
    up = bool(_UP.search(q))
    pnl_pct = (size if up else -size) * (1 if long_ else -1)
    pnl = notional * pnl_pct / 100.0
    exit_bps = ((r.get("execution") or {}).get("exit_quote") or {}).get("total_cost_bps")
    bits = [f"{'上涨' if up else '下跌'} {size:g}%：{_usd(notional)} 的{'多头' if long_ else '空头'}{'赚' if pnl >= 0 else '亏'}约 {_usd(abs(pnl))}"
            + (f"，按当前盘口平仓还要约 {_usd(notional * exit_bps / 1e4)}" if exit_bps is not None else "") + "。"]
    if pnl_pct < 0:
        stop = t.get("stop_price")
        stop_pct = (((r.get("analog") or {}).get("paths") or {}).get("stop_pct"))
        if stop and stop_pct is not None and abs(stop_pct) < size:
            bits.append(f"这会直接越过你在 {stop:,.2f} 的止损（距现价 {abs(stop_pct):.1f}%）：如果是开盘跳空，止损会在跳空之后成交，而不是在你的价格。")
        lev = r.get("leverage") or {}
        if lev.get("liquidation_distance_pct") is not None:
            d = lev["liquidation_distance_pct"]
            bits.append(f"{lev['leverage']:g} 倍杠杆下" + (f"会被强平，{_usd(lev['margin_quote'])} 保证金全部损失。" if size >= d else f"还不会强平（强平线距现价 {d:.1f}%）。"))
        presets = {p["id"]: p for p in ((r.get("stress") or {}).get("presets") or [])}
        p1 = presets.get("closed_window_gap_p1")
        if p1 and abs(p1.get("price_move_pct") or 0) < size:
            bits.append(f"这比该代币历史上百分之一的休市波动（{_pct(p1['price_move_pct'])}）还大。")
    return Answer("shock", "".join(bits), ("position arithmetic", "order book", "stress presets"))


FEATURE_ZH = {
    "basis_index_bps": "与公允价值的偏离", "basis_index_z": "偏离的程度", "rv_24h": "当日波动率", "rv_168h": "周波动率",
    "vol_pctl_90d": "波动率分位", "trend_sma_pct": "趋势", "sma_slope_5d_pct": "趋势斜率", "liq_ratio": "交易活跃度",
    "no_trade_share_24h": "无成交时段占比", "native_close_age_h": "距正股上次交易的时间", "hours_to_earnings": "距财报时间",
    "hours_since_earnings": "距上次财报时间", "macro_events_72h": "未来宏观数据", "hours_to_fomc": "距美联储会议时间",
    "news_count_24h": "新闻数量", "vix_pctl_1y": "VIX", "curve_pctl_1y": "收益率曲线", "dollar_20d_chg_pct": "美元",
    "ten_year_20d_chg_bps": "十年期美债收益率",
}


def _a_similar(r: dict, _q: str) -> Answer | None:
    from collections import Counter

    matches = ((r.get("analog") or {}).get("result") or {}).get("matches") or []
    if not matches or not any(m.get("alike_on") for m in matches):
        return None
    alike = Counter(f for m in matches for f in (m.get("alike_on") or []))
    differs = Counter(f for m in matches for f in (m.get("differs_on") or []))
    top = [FEATURE_ZH.get(f, f) for f, _ in alike.most_common(3)]
    text = f"这 {len(matches)} 个历史时刻与现在最接近的是：{'、'.join(top)}。"
    if differs:
        f, n = differs.most_common(1)[0]
        text += f"差别最大的是{FEATURE_ZH.get(f, f)}，{len(matches)} 个里有 {n} 个相差较远。"
    return Answer("moments", text, ("matched moments",))


ROUTES = (
    ("shock", re.compile(r"(?:跌|涨|跳空|暴跌|暴涨)[^0-9]{0,6}[0-9]+(?:\.[0-9]+)?\s*[%％]"), _a_shock),
    ("similar", re.compile(r"相似|一样|像现在"), _a_similar),
    ("street", re.compile(r"分析师|评级|目标价|内部人|高管|恐慌|贪婪|情绪|华尔街|实时价"), _a_street),
    ("stop", re.compile(r"止损"), _a_stop),
    ("size", re.compile(r"仓位|更大|更小|加仓|减仓|为什么不能|上限|多少钱|减半|加倍|翻倍"), _a_size),
    ("worst", re.compile(r"最坏|最差|风险|压力|暴跌|亏多少|崩|出什么问题|怎么亏|会亏|出错"), _a_worst),
    ("exit", re.compile(r"平仓|出场|卖得掉|流动性|滑点|盘口|深度"), _a_exit),
    ("hedge", re.compile(r"对冲|永续"), _a_hedge),
    ("gate", re.compile(r"为什么|复核|规则|原因|闸门"), _a_gate),
    ("history", re.compile(r"历史|过去|相似|概率|胜率|中位"), _a_history),
)

MENU_ZH = "我可以根据这份报告回答：仓位为什么是这么大、止损、最坏的情况、如果跌 10% 会怎样、平仓成本、历史怎么说、这些时刻为什么相似、对冲、为什么需要复核，以及分析师和内部人在做什么。也可以问“最安全的持有方式是什么”。"


def answer(report: dict, question: str) -> Answer | None:
    for _kind, pattern, fn in ROUTES:
        if pattern.search(question):
            try:
                got = fn(report, question)
            except Exception:  # noqa: BLE001 - a malformed report must not take the desk down
                continue
            if got is not None:
                return got
    return None


def answer_or_menu(report: dict, question: str) -> Answer:
    return answer(report, question) or Answer("menu", MENU_ZH, ())
