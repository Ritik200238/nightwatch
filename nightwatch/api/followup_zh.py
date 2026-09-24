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
    st = r.get("stress") or {}
    rows = [(p, i) for p, i in zip(st.get("presets") or [], st.get("impacts") or [], strict=False) if i.get("total_pnl_quote") is not None]
    bits = []
    if rows:
        rows.sort(key=lambda x: x[1]["total_pnl_quote"])
        bits.append("用这个代币自身历史构建的最坏三个情景：" + "；".join(f"{p['name']} 损失 {_usd(i['total_pnl_quote'])}（仓位 {_pct(i.get('total_pct_of_notional'))}）" for p, i in rows[:3]) + "。")
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


ROUTES = (
    ("street", re.compile(r"分析师|评级|目标价|内部人|高管|恐慌|贪婪|情绪|华尔街|实时价"), _a_street),
    ("stop", re.compile(r"止损"), _a_stop),
    ("size", re.compile(r"仓位|更大|更小|加仓|减仓|为什么不能|上限|多少钱"), _a_size),
    ("worst", re.compile(r"最坏|最差|风险|压力|暴跌|亏多少|崩"), _a_worst),
    ("exit", re.compile(r"平仓|出场|卖得掉|流动性|滑点|盘口|深度"), _a_exit),
    ("hedge", re.compile(r"对冲|永续"), _a_hedge),
    ("gate", re.compile(r"为什么|复核|规则|原因|闸门"), _a_gate),
    ("history", re.compile(r"历史|过去|相似|概率|胜率|中位"), _a_history),
)

MENU_ZH = "我可以根据这份报告回答：仓位为什么是这么大、止损、最坏的情况、平仓成本、历史怎么说、对冲、为什么需要复核，以及分析师和内部人在做什么。"


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
