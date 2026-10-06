"""What the verdict assumes, and how this trade loses money.

The report already carries every number a stress test needs - presets, analogs, the
book, the simulation. What it did not do was say two things a careful reader asks first:
*what are you assuming?* and *how, concretely, does this go wrong?* A judge reading it
against the chain "decision → assumptions → scenarios → analogues → consequences →
failure modes" found the assumptions link and the consequences link nearly empty.

Both are written here by rules, from the report's own fields, never by a model. The
research on language models and cause and effect is blunt: they recite causal stories
they have read rather than infer them (Kiciman et al. 2023; "causal parrots", Zečević et
al. 2023). So each failure mode names a mechanism that is structural to this market -
the stock reopening at a new price while only the token traded, a thin book at night,
the exchange closing a leveraged position - and attaches only numbers the engine
measured, with how often it happened.

A premise check sits beside them: when the trader's stated reason depends on an event
("post-earnings drift", "into the Fed"), the event's timing is read from the data and
the mismatch is said.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from typing import Any

from nightwatch.decision.zh import note_zh
from nightwatch.features.phrases import earnings_ahead
from nightwatch.time_utils import whole_hours


@dataclass(frozen=True)
class Assumption:
    topic: str
    text: str
    kind: str = "fact"  # "fact" | "caveat" - a caveat is something that could make the numbers wrong


@dataclass(frozen=True)
class FailureMode:
    key: str
    title: str
    trigger: str
    mechanism: str
    loss_quote: float | None  # negative = a loss, at the ticket's size
    loss_pct: float | None  # of the position
    likelihood: str
    source: str
    short: str = ""  # the mechanism in a clause, for the chat reply
    # How often, as a number, where it was measured (a percentile, a share of past moments,
    # a share of simulated paths). None where it is a named crisis or an assumption.
    chance: float | None = None
    capped: bool = False  # a leveraged loss stopped at the margin by liquidation
    # The same loss at the recommended size, when that is smaller than the request. The
    # headline loss is always at the requested size, the size the rest of the report prices.
    loss_quote_at_recommended: float | None = None
    # The same sentences in Chinese, built from the same numbers where the English is, so the
    # page can be read in either language. Empty where the English has no Chinese twin.
    trigger_zh: str = ""
    mechanism_zh: str = ""
    likelihood_zh: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _money(x: float | None) -> str:
    return "n/a" if x is None else f"{x:,.0f}"


# The event features are capped at 30 days (720 h): beyond that the data says only "far".
_EVENT_CAP_H = 720.0


def _days(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    if hours >= _EVENT_CAP_H:
        return "over 30 days"
    return f"{whole_hours(hours / 24)} days" if hours >= 48 else f"{whole_hours(hours)} hours"


# ------------------------------------------------------------------ assumptions

# Leveraged and inverse funds do not do over several days what their multiple says: they
# reset every day, so the path matters as much as the destination.
_FUNDS = {
    "TQQQ": "TQQQ is a 3x leveraged Nasdaq-100 fund that resets daily: over more than a day it does not return 3x the index, and a choppy market erodes it.",
    "SQQQ": "SQQQ is a 3x inverse Nasdaq-100 fund that resets daily: it rises when the Nasdaq falls, and over more than a day it does not return -3x the index.",
}


def assumptions(r: Any) -> list[Assumption]:  # noqa: ANN401 - an AnalysisReport
    t = r.ticket
    out: list[Assumption] = []
    label = (t.extra or {}).get("horizon_label") if isinstance(t.extra, dict) else None
    out.append(Assumption("hold", f"Held for {whole_hours(r.horizon_h)} hours" + (f" ({label})" if label else ", to the next US regular open" if t.horizon_kind.value == "next_open" else "") + ", then closed."))
    entry = t.entry_price or r.snapshot.prices.get("spot_close")
    if entry:
        out.append(Assumption("entry", f"Entered at the token's last price, {entry:,.2f}, as of {r.snapshot.bar_ts:%d %b %H:%M} UTC."))
    lev = getattr(r, "leverage", None)
    if lev:
        out.append(Assumption("leverage", f"{round(lev['leverage'], 2):g}x on the Bitget perpetual, isolated margin, maintenance margin {lev['mmr']:.2%}"
                              + (" from Bitget's tier for this size." if lev.get("tiers_source") == "bitget" else " (assumed; Bitget's tiers were unavailable).")))
        out.append(Assumption("leverage", "The perp is priced off the token's path; the gap between the two is shocked separately by the basis presets.", "caveat"))
    else:
        out.append(Assumption("leverage", "No leverage: a plain token position. Say \"5x\" to test it on the perpetual."))
    if t.stop_price:
        out.append(Assumption("stop", f"Stop at {t.stop_price:,.2f}. A resting stop fills at the next price there is, so a gap can fill it worse than the stop.", "caveat"))
    else:
        out.append(Assumption("stop", "No stop: the risk is sized on the calibrated 1-in-20 loss instead."))
    if t.account_equity_quote:
        out.append(Assumption("account", f"Account of {t.account_equity_quote:,.0f} USDT; the size limits are shares of it."))
    else:
        out.append(Assumption("account", "Account size not given, so the size limits that depend on it are not checked.", "caveat"))
    a = r.analog
    if a is not None and a.result.ok and a.result.matches:
        ts = sorted(m.ts for m in a.result.matches)
        tokens = {m.ticker for m in a.result.matches}
        out.append(Assumption(
            "history",
            f"The {len(a.result.matches)} past moments compared against run from {ts[0]:%b %Y} to {ts[-1]:%b %Y}, across {len(tokens)} token{'s' if len(tokens) > 1 else ''}; "
            "the future is assumed to resemble them only as much as the calibration page shows it has.",
            "caveat",
        ))
    stress = getattr(r, "stress", None)
    ids = {x.id for x in stress.presets} if stress is not None else set()
    if any(i.startswith("replay_") for i in ids):
        out.append(Assumption(
            "crash replays",
            f"The crash replays apply {t.ticker}'s own stock move from those crises to today's token. The token did not exist then (only the April 2025 shock overlaps its life), "
            "so basis, thin night books and listing effects were not part of what was replayed. The five windows were picked after the fact.",
            "caveat",
        ))
    if any(i.startswith("vol_spike") for i in ids):
        out.append(Assumption(
            "volatility spike",
            "The 2σ and 3σ spike scales volatility by the square root of the hours held over a 24-hour, seven-day year, which counts weekend and overnight hours as if they traded like the day. "
            "Over a weekend that is not true; read the sigma label as approximate.",
            "caveat",
        ))
    if stress is not None and getattr(stress, "monte_carlo", None) is not None:
        out.append(Assumption(
            "monte carlo",
            "The Monte Carlo band redraws blocks of this token's own past hourly returns and adds up the hours held. It uses only hours the token traded, with no volatility scaling "
            "for weekends or news, and it is recorded but not yet scored against outcomes the way the 1-in-20 line is.",
            "caveat",
        ))
    fund = _FUNDS.get(t.ticker.upper())
    if fund:
        out.append(Assumption("instrument", fund, "caveat"))
    basis = r.snapshot.features.get("basis_index_bps")
    if basis is not None:
        out.append(Assumption("fair value", f"Fair value is Bitget's index for the stock; the token sits {basis:+.0f} bps from it now."))
    ex = r.execution
    if ex.exit_quote is not None:
        when = f" at {ex.book_ts:%H:%M} UTC" if ex.book_ts else ""
        out.append(Assumption("exit", f"Exit cost is walked on the {ex.book_source} order book{when}, taker fee on both legs; a thinner book at exit is a separate stress preset.", "caveat" if ex.book_source != "live" else "fact"))
    f = r.snapshot.features
    hte = f.get("hours_to_earnings")
    if hte is not None and hte <= r.horizon_h:
        out.append(Assumption("events", f"Earnings fall inside the hold (in {_days(hte)}); the earnings-gap presets are included.", "caveat"))
    elif hte is not None:
        out.append(Assumption("events", f"No earnings inside the hold ({earnings_ahead(hte)})." if hte >= _EVENT_CAP_H else f"No earnings inside the hold (next in {_days(hte)})."))
    else:
        out.append(Assumption("events", "Earnings timing is not known (no upcoming date on the earnings calendar), so the earnings-gap presets are not tied to this hold.", "caveat"))
    ce = getattr(r, "corporate_events", None)
    if ce:
        from nightwatch.features import corporate as corporate_mod

        inside = ce.get("in_hold") or []
        if inside:
            what = "; ".join(corporate_mod.plain(e) for e in inside)
            out.append(Assumption("corporate events", f"Inside the hold: {what}. The stress presets and the past moments compared do not model it, and how Bitget adjusts the rToken for it is not verified.", "caveat"))
        elif not ce.get("covered"):
            out.append(Assumption("corporate events", "Dividends and splits were not checked: the calendar has not been synced yet.", "caveat"))
        else:
            out.append(Assumption("corporate events", "No ex-dividend date or split inside the hold in the stored calendar (Nasdaq, Yahoo, Bitget notices)."))
    return out


# ---------------------------------------------------------------- failure modes


_SHORT = {
    "gap": "news while the market is shut reprices the stock at the open, with no trading in between",
    "earnings": "the stock gaps on the result at the open",
    "basis": "only the token trades, and it drifts from fair value",
    "liquidity": "selling walks deeper into a thin book",
    "halt": "no way to cut the position for a day",
    "vol": "a move three times what current volatility implies",
}

_MECH_ZH = {
    "gap": ("美股休市期间出现消息——公司公告、宏观数据、海外突发事件",
            "股票开盘时以新价格重新定价，代币立即跟随；中间没有交易，止损来不及起作用"),
    "earnings": ("公司在你的持有期内发布财报", "股票在下次开盘时因财报结果跳空，代币随之变动"),
    "basis": ("只有代币在交易时，它偏离了股票的公允价值",
              "夜间和周末代币价格由它自己较薄的盘口决定，可能出现溢价或折价，开盘后又会被抹平"),
    "liquidity": ("你需要离场时盘口变薄——夜间、周末或交易繁忙时", "卖出会吃掉更深的盘口，所以平仓本身的成本比价格波动还高"),
    "halt": ("你一整天都无法平仓，而价格朝不利方向走", "故障或停牌让你失去了减仓的机会"),
    "vol": ("波动率从现在的水平骤升", "波动幅度达到当前波动率所隐含的两到三倍"),
}

_MECH = {
    "gap": (
        "News lands while the US market is shut - a company announcement, macro data, a shock abroad",
        "the stock reopens at a new price and the token reprices to it at once; there is no trading in between for a stop to act on",
    ),
    "earnings": (
        "The company reports inside your hold",
        "the stock gaps on the result at the next open and the token follows",
    ),
    "basis": (
        "The token drifts away from the stock's fair value while only the token trades",
        "at night and on weekends the token's price is set by its own thin book, and it can trade at a premium or discount the reopen then removes",
    ),
    "liquidity": (
        "The book thins out when you need to leave - nights, weekends, a busy moment",
        "selling walks deeper into the book, so the exit itself costs more than the move",
    ),
    "halt": (
        "You cannot get out for a day while the price moves against you",
        "an outage or a halt removes the option to cut the position",
    ),
    "vol": (
        "Volatility jumps from where it is now",
        "a move two or three times the size the current volatility implies",
    ),
}


def failure_modes(r: Any) -> list[FailureMode]:  # noqa: ANN401, C901 - a list of independent cases
    t = r.ticket
    by_id = {s.id: s for s in r.stress.presets}
    imp = {i.scenario_id: i for i in r.stress.impacts}
    out: list[FailureMode] = []

    def from_preset(key: str, sid: str, title: str, mech: str) -> None:
        s, i = by_id.get(sid), imp.get(sid)
        if s is None or i is None or i.total_pnl_quote is None:
            return
        trig, how = _MECH[mech]
        trig_zh, how_zh = _MECH_ZH[mech]
        recent = (s.calibration or {}).get("recent") if isinstance(s.calibration, dict) else None
        if recent:
            how += f"; this company's last {len(recent)} reactions were " + ", ".join(f"{x:+.1f}%" for x in recent)
            how_zh += f"；这家公司最近 {len(recent)} 次的反应分别为 " + "、".join(f"{x:+.1f}%" for x in recent)
        out.append(FailureMode(key, title, trig, how, i.total_pnl_quote, i.total_pct_of_notional, s.probability_note, "stress presets", _SHORT[mech], _preset_chance(sid),
                               trigger_zh=trig_zh, mechanism_zh=how_zh, likelihood_zh=note_zh(s.probability_note) or ""))

    # This trade's own chains first: what history did after the trader's own line broke,
    # the token snapping back to the stock, and this company's actual earnings reactions.
    out.extend(_own_chains(r))

    from_preset("gap_bad", "closed_window_gap_p5", "A bad gap at the reopen", "gap")
    from_preset("gap_worst", "closed_window_gap_p1", "A severe gap at the reopen", "gap")
    from_preset("earnings", "earnings_gap_typical", "An adverse earnings reaction", "earnings")
    from_preset("basis", "basis_blowout_p99" if "basis_blowout_p99" in by_id else "basis_blowout_p95", "The token disconnects from fair value", "basis")
    from_preset("liquidity", "liquidity_drought", "A thin book on the way out", "liquidity")
    from_preset("halt", "exchange_halt_24h", "Stuck for 24 hours", "halt")
    from_preset("vol", "vol_spike_x3", "A volatility spike", "vol")

    # The worst named crisis, replayed: what this stock did the day the market broke.
    replays = [(s, imp[s.id]) for s in r.stress.presets if s.id.startswith("replay_") and imp.get(s.id) is not None and imp[s.id].total_pnl_quote is not None]
    if replays:
        s, i = min(replays, key=lambda x: x[1].total_pnl_quote)
        crisis = s.name.replace("Replay: ", "")
        from nightwatch.api.intake import preset_zh

        crisis_zh = preset_zh(s.id, s.name).split("：", 1)[-1]
        note = note_zh(s.probability_note)
        out.append(FailureMode(
            "replay", f"A repeat of the {crisis}",
            f"The market breaks the way it did in the {crisis}",
            "the stock moves as it did on that day, and the token follows it at the next open",
            i.total_pnl_quote, i.total_pct_of_notional,
            f"{s.probability_note} - a named crisis, not a frequency", "crash replays",
            f"the {crisis} replayed on this position",
            trigger_zh=f"大盘再次出现{crisis_zh}那样的崩溃",
            mechanism_zh="这只股票的走势与那一天相同，代币在下次开盘时跟随",
            likelihood_zh=f"{note} —— 这是一次具体的历史危机，不是发生频率" if note else "",
        ))

    # A stop that a gap can jump: judged against the worst measured gap.
    paths = r.analog.paths if r.analog else None
    worst_gap = by_id.get("closed_window_gap_p1")
    if t.stop_price and paths is not None and paths.stop_pct is not None and worst_gap is not None:
        stop_d = abs(paths.stop_pct)
        gap_d = abs(worst_gap.price_move_pct)
        if gap_d > stop_d:
            extra = (gap_d - stop_d) / 100.0 * t.notional_quote
            out.append(FailureMode(
                "stop_jumped", "Your stop is jumped",
                "A gap at the reopen larger than your stop distance",
                f"the stop triggers at the first price after the gap, not at {t.stop_price:,.2f}; the 1-in-100 gap ({worst_gap.price_move_pct:+.1f}%) "
                f"is {gap_d - stop_d:.1f} points past your stop ({stop_d:.1f}% away)",
                -(gap_d / 100.0) * t.notional_quote, -gap_d,
                f"{paths.stopped} of {len(paths.paths)} past moments like this hit the stop at all; the extra loss beyond it here is about {extra:,.0f} USDT",
                "stress presets + analogs",
                f"a gap fills the stop well past {t.stop_price:,.2f}",
                0.01,  # it is the 1-in-100 gap that jumps it
                trigger_zh="开盘时的跳空幅度大于你的止损距离",
                mechanism_zh=(f"止损会在跳空后的第一个价格成交，而不是 {t.stop_price:,.2f}；每 100 次出现 1 次的跳空（{worst_gap.price_move_pct:+.1f}%）"
                              f"比你的止损（距现价 {stop_d:.1f}%）还多出 {gap_d - stop_d:.1f} 个百分点"),
                likelihood_zh=f"在 {len(paths.paths)} 个相似的历史时刻中，有 {paths.stopped} 个触及了止损；越过止损之后多出的亏损约 {extra:,.0f} USDT",
            ))

    lev = getattr(r, "leverage", None)
    if lev and lev.get("liquidation_distance_pct") is not None:
        seen = []
        seen_zh = []
        if lev.get("analog_of"):
            seen.append(f"{lev['analog_hits']} of {lev['analog_of']} past moments reached it")
            seen_zh.append(f"{lev['analog_of']} 个相似的历史时刻中有 {lev['analog_hits']} 个触及")
        if lev.get("mc_share") is not None:
            seen.append(f"{lev['mc_share']:.0%} of simulated paths do")
            seen_zh.append(f"{lev['mc_share']:.0%} 的模拟路径触及")
        out.append(FailureMode(
            "liquidation", "Liquidated",
            f"A move of {lev['liquidation_distance_pct']:.1f}% against you at any point in the hold",
            "the exchange closes the position when the margin left falls to the maintenance requirement; the margin is gone and the move cannot be ridden back",
            -float(lev["margin_quote"]), -100.0 / float(lev["leverage"]),
            "; ".join(seen) or "not measured", "Bitget margin tiers + analogs + Monte Carlo",
            "the exchange closes the position and the margin is gone",
            max(x for x in (lev.get("mc_share"), (lev["analog_hits"] / lev["analog_of"]) if lev.get("analog_of") else None) if x is not None)
            if (lev.get("mc_share") is not None or lev.get("analog_of")) else None,
            trigger_zh=f"持有期内任何时刻朝不利方向移动 {lev['liquidation_distance_pct']:.1f}%",
            mechanism_zh="保证金降到维持保证金要求时交易所会平掉仓位；保证金就此损失，无法再等价格回来",
            likelihood_zh="；".join(seen_zh) or "未测量",
        ))

    # Nothing dramatic: the ordinary way a trade loses.
    h = r.analog.horizons.get(r.primary_horizon) if r.analog else None
    c = h.cohort if h is not None else None
    wins, median = (h.pnl_win_rate, h.pnl_median_pct) if h is not None else (None, None)
    if c is not None and c.n and wins is not None and median is not None and wins < 0.5:
        # "The wrong way" is down for a long and up for a short.
        way = "lower" if t.closing_long else "higher"
        out.append(FailureMode(
            "drift", "A quiet drift the wrong way",
            "No event at all",
            f"the price simply ends {way}, as most moments like this one did",
            median / 100.0 * t.notional_quote, median,
            f"{1 - wins:.0%} of {c.n} past moments like this ended {'down' if t.closing_long else 'up'}", "analog cohort",
            f"no event; the price just ends {way}",
            1 - wins,
            trigger_zh="没有任何事件",
            mechanism_zh=f"价格就是慢慢走{'低' if t.closing_long else '高'}，大多数与现在相似的时刻都是这样收场",
            likelihood_zh=f"{c.n} 个相似的历史时刻中有 {1 - wins:.0%} 以{'下跌' if t.closing_long else '上涨'}收场",
        ))

    ranked = _rank(_cap_at_margin(out, lev))
    rec = getattr(getattr(r, "verdict", None), "recommended_notional", None)
    if rec is not None and 0 < rec < t.notional_quote - 1:
        scale = rec / t.notional_quote
        ranked = [replace(m, loss_quote_at_recommended=m.loss_quote * scale) if m.loss_quote is not None else m for m in ranked]
    return ranked


def _own_chains(r: Any) -> list[FailureMode]:  # noqa: ANN401
    """Consequences measured for this trade, not templates."""
    t = r.ticket
    out: list[FailureMode] = []
    plan = getattr(r, "plan_check", None) or {}
    paths = r.analog.paths if r.analog else None
    if plan.get("kind") in ("level", "moving_average", "move") and plan.get("crossed") is not None and plan.get("of") and plan.get("distance_pct") is not None and not plan.get("already"):
        crossed, of, d = int(plan["crossed"]), int(plan["of"]), abs(float(plan["distance_pct"]))
        what = f"'{plan.get('invalidation')}'" if plan.get("invalidation") else "your invalidation"
        mech = f"{crossed} of {of} past moments like this crossed it inside the hold"
        mech_zh = f"{of} 个相似的历史时刻中有 {crossed} 个在持有期内越过了它"
        if t.stop_price and paths is not None and paths.stop_pct is not None and abs(paths.stop_pct) > d and paths.stopped is not None:
            if paths.stopped <= crossed:
                mech += f"; of those, {paths.stopped} went on to your stop and {crossed - paths.stopped} turned back before it"
                mech_zh += f"；其中 {paths.stopped} 个继续跌到你的止损，{crossed - paths.stopped} 个在到止损之前掉头"
            else:
                # The stop is judged on each bar's low and the line on closes, so more can
                # hit the stop than closed past the line; "of those" would be impossible.
                mech += f"; separately, {paths.stopped} of {of} hit your stop when judged on each bar's low"
                mech_zh += f"；另外，按每根 K 线的最低价算，{of} 个里有 {paths.stopped} 个触及了你的止损"
        out.append(FailureMode(
            "invalidation", f"Your own line breaks: {what}",
            f"The price reaches your invalidation, {d:.1f}% away",
            mech + " - so the idea is proven wrong on your own terms",
            -d / 100.0 * t.notional_quote, -d,
            f"{crossed} of {of} past moments like this ({crossed / of:.0%})", "your plan + analogs",
            f"{crossed} of {of} similar moments crossed your line", crossed / of,
            trigger_zh=f"价格到达你设定的失效线，距现价 {d:.1f}%",
            mechanism_zh=mech_zh + " —— 也就是说，按你自己的标准，这个想法被证明是错的",
            likelihood_zh=f"{of} 个相似的历史时刻中有 {crossed} 个（{crossed / of:.0%}）",
        ))
    street = getattr(r, "street", None) or {}
    gap = street.get("token_vs_live_bps")
    if gap is not None and abs(gap) >= CONVERGE_MIN_BPS and ((gap > 0) == t.closing_long):
        out.append(FailureMode(
            "convergence", "The token snaps back to the stock",
            f"The token trades {abs(gap):.0f} bps {'above' if gap > 0 else 'below'} the stock's live price now",
            "at the next open the stock's own price sets the level again and the token is pulled to it, "
            f"so a {'long' if t.closing_long else 'short'} gives that gap up",
            -abs(gap) / 1e4 * t.notional_quote, -abs(gap) / 100.0,
            "the gap to the live price is measured now; how fully it closes is not", "Bitget live quote",
            "the token's premium to the stock closes at the open", None,
            trigger_zh=f"代币现在比股票实时价格{'高' if gap > 0 else '低'} {abs(gap):.0f} bps",
            mechanism_zh=f"下次开盘时，股票自己的价格重新决定水平，代币被拉向它，所以{'做多' if t.closing_long else '做空'}要把这段价差让出去",
            likelihood_zh="与实时价格的价差现在已量出；它会收敛到什么程度没有测量",
        ))
    return out


# A token-vs-stock gap smaller than this is inside ordinary spread and fee noise.
CONVERGE_MIN_BPS = 15.0


def _preset_chance(sid: str) -> float | None:
    """The measured frequency behind a preset, where it has one."""
    if (m := re.fullmatch(r"closed_window_gap_p(\d+)", sid)):
        return int(m.group(1)) / 100.0
    if (m := re.fullmatch(r"basis_blowout_p(\d+)", sid)):
        return (100 - int(m.group(1))) / 100.0
    return None


def _cap_at_margin(modes: list[FailureMode], lev: dict | None) -> list[FailureMode]:
    """With isolated margin a leveraged position cannot lose more than its margin: the
    exchange closes it first. A stress loss past the margin is shown as the margin."""
    if not lev or not lev.get("margin_quote") or lev.get("liquidation_distance_pct") is None:
        return modes
    margin = float(lev["margin_quote"])
    out = []
    for m in modes:
        if m.key != "liquidation" and m.loss_quote is not None and m.loss_quote < -margin:
            m = FailureMode(**{**asdict(m), "loss_quote": -margin, "loss_pct": -100.0 / float(lev["leverage"]), "capped": True,
                               "mechanism": m.mechanism + f"; at {round(lev['leverage'], 2):g}x it is liquidated first, so the loss stops at the {margin:,.0f} USDT margin",
                               "mechanism_zh": (m.mechanism_zh + f"；{round(lev['leverage'], 2):g} 倍杠杆下会先被强平，所以亏损止于 {margin:,.0f} USDT 的保证金") if m.mechanism_zh else ""})
        out.append(m)
    return out


def _rank(modes: list[FailureMode]) -> list[FailureMode]:
    """Largest loss first, so the list, the "worst" label and the chat reply all agree.

    It used to sort by chance times loss, which put a -833 gap above a -2,843 crash replay
    under a heading that said "worst first". Each card still shows how often it happened;
    the order now says only what the heading says. Equal losses (a leveraged position capped
    at its margin) go most-likely first; a mode with no priced loss goes last.
    """
    priced = sorted((m for m in modes if m.loss_quote is not None), key=lambda m: (m.loss_quote, -(m.chance or 0.0)))
    return priced + [m for m in modes if m.loss_quote is None]


# ------------------------------------------------------------------- premise


_EARN = re.compile(r"earning|post[-\s]?earn|guidance|report(?:s|ed)?\s+(?:q\d|results)|财报|业绩", re.I)
_POST = re.compile(r"post[-\s]?earn|after\s+(?:the\s+)?(?:earnings|report|results)|drift|财报后", re.I)
_PRE = re.compile(r"(?:into|ahead\s+of|before|pre[-\s]?)\s*(?:the\s+)?(?:earnings|report|results)|run[-\s]?up|财报前", re.I)
_MACRO = re.compile(r"\bcpi\b|inflation (?:data|print|number|report)|\bjobs? (?:report|data|number)\b|\bnfp\b|payrolls?|\bpce\b|\bgdp\b|retail sales|非农|通胀数据|CPI", re.I)
_PAYOUT = re.compile(r"dividend|\bsplit\b|\bex[-\s]?div|payout|分红|股息|拆股|除息", re.I)
_FED = re.compile(r"\bfed\b|fomc|rate\s+(?:cut|hike|decision)|powell|美联储|议息|降息|加息", re.I)


def premise(r: Any) -> list[str]:  # noqa: ANN401
    """Where the trader's stated reason depends on an event the data can date."""
    thesis = f"{r.ticket.thesis} {r.ticket.invalidation}"
    if not thesis.strip():
        return []
    f = r.snapshot.features
    out: list[str] = []
    since, until = f.get("hours_since_earnings"), f.get("hours_to_earnings")
    if _EARN.search(thesis):
        if _POST.search(thesis) and (since is None or since > 7 * 24):
            out.append(f"Your reason leans on a recent earnings report, but the last one was {_days(since)} ago" + (f" and next: {earnings_ahead(until)}" if until is not None else "") + ".")
        elif _PRE.search(thesis) and (until is None or until > 14 * 24):
            out.append(f"Your reason leans on earnings coming up, but next earnings: {earnings_ahead(until)}, well past this hold.")
        elif not _POST.search(thesis) and not _PRE.search(thesis) and (since is None or since > 7 * 24) and (until is None or until > r.horizon_h + 24):
            last = "no past report on record" if since is None else f"last {_days(since)} ago"
            out.append(f"Your reason mentions earnings, but none fall near this hold ({last}; next: {earnings_ahead(until)}).")
    fomc = f.get("hours_to_fomc")
    if _FED.search(thesis):
        if fomc is None:
            # The FOMC feature looks 30 days ahead; empty means no decision in that window.
            out.append("Your reason mentions the Fed, but there is no FOMC decision in the next 30 days.")
        elif fomc > max(r.horizon_h + 24, 7 * 24):
            out.append(f"Your reason mentions the Fed, but the next FOMC decision is {_days(fomc)} away, after this hold ends.")
    macro = f.get("macro_events_72h")
    if _MACRO.search(thesis) and macro is not None and macro == 0 and r.horizon_h <= 72:
        out.append("Your reason leans on a data release, but no scheduled release (CPI, jobs, PCE, GDP, retail sales) falls in the next 72 hours.")
    ce = getattr(r, "corporate_events", None)
    if _PAYOUT.search(thesis) and ce is not None:
        from nightwatch.features import corporate as corporate_mod

        if ce.get("in_hold"):
            out.append("Your reason mentions a dividend or split; the stored calendar has: " + "; ".join(corporate_mod.plain(e) for e in ce["in_hold"]) + ".")
        elif ce.get("next_after"):
            out.append(f"Your reason mentions a dividend or split, but none falls inside this hold; the next is {corporate_mod.plain(ce['next_after'])}.")
        elif ce.get("covered"):
            out.append("Your reason mentions a dividend or split, but the stored calendar has none inside this hold and none ahead.")
        else:
            out.append("Your reason mentions a dividend or split, but the dividend and split calendar has not been synced, so it could not be checked.")
    # A stop beyond the line that proves the idea wrong: still holding after being wrong.
    plan = getattr(r, "plan_check", None) or {}
    t = r.ticket
    if t.stop_price and plan.get("kind") == "level" and plan.get("level") and not plan.get("already"):
        level = float(plan["level"])
        beyond = t.stop_price < level if t.closing_long else t.stop_price > level
        if beyond:
            out.append(f"Your stop ({t.stop_price:,.2f}) sits beyond your own 'wrong if' level ({level:,.2f}): if the idea is proven wrong you are still holding it.")
    return out
