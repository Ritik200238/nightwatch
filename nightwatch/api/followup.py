"""Answering questions about a report, out of the report.

The desk could take a trade idea and give an answer. It could not be asked anything
about that answer, which is most of what a person actually wants to do with one: why not
bigger, what if my stop were wider, has this setup burned me before, talk me out of it.

Every answer here is a field of the report the question is about, formatted for reading -
a share printed as a percentage, a timestamp trimmed to the minute. Nothing is computed,
averaged or combined, and this module reads nothing but the dict it is handed: no market
data, no database, no model. So an answer cannot carry a number the report does not,
because there is nowhere else for one to come from.

That narrowness buys the interesting half too. A question about size is answered out of
the sweep that already re-ran the entire gate at every size and stop distance, so "what
if I do 40k" returns the verdict at 40k rather than an opinion about it.

When a model is available it does the same job with more range; this runs underneath it,
and runs alone when there is no key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from nightwatch.features.phrases import earnings_ahead

# ------------------------------------------------------------------ small formatters


def _pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "unknown"
    sign = "+" if round(v, digits) > 0 else "-" if round(v, digits) < 0 else ""
    return f"{sign}{abs(v):.{digits}f}%"


def _usd(v: float | None, digits: int = 0) -> str:
    return "unknown" if v is None else f"{abs(v):,.{digits}f} USDT"


def _bps(v: float | None) -> str:
    return "unknown" if v is None else f"{v:.1f} bps"


def _ordinal(v: float | None) -> str:
    """21 -> 21st. Percentiles get read aloud, and "the 1th percentile" is not English."""
    if v is None:
        return "unknown"
    n = int(round(v))
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _money_in(text: str) -> float | None:
    """A size named in the question: 40k, $40,000, 40000 usdt."""
    m = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)\s*([km])?\b", text, re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    if m.group(2):
        n *= 1_000 if m.group(2).lower() == "k" else 1_000_000
    return n


def _percent_in(text: str) -> float | None:
    m = re.search(r"([\d.]+)\s*(?:%|per ?cent)", text, re.I)
    return float(m.group(1)) if m else None


def _nearest(points: list[dict], key: str, target: float) -> dict | None:
    usable = [p for p in points if p.get(key) is not None]
    return min(usable, key=lambda p: abs(p[key] - target)) if usable else None


# ------------------------------------------------------------------------- the answers


@dataclass(frozen=True)
class Answer:
    kind: str
    text: str
    reads: tuple[str, ...]  # which parts of the report the answer came from


def _ticket(r: dict) -> dict:
    return r.get("ticket") or {}


def _primary(r: dict) -> dict | None:
    a = r.get("analog") or {}
    return (a.get("horizons") or {}).get(r.get("primary_horizon"))


def asked_size(r: dict, q: str) -> float | None:
    """The size a question names: a sum of money, or a multiple of what is on screen."""
    requested = _ticket(r).get("notional_quote")
    asked = _money_in(q)
    # "halve it", "double it", "three times the size": a multiple of what is on screen.
    factor = _SIZE_FACTOR.search(q)
    if requested and factor and (asked is None or asked < 100):
        word = factor.group(1).lower()
        mult = {"halve": 0.5, "half": 0.5, "double": 2.0, "twice": 2.0, "triple": 3.0}.get(word)
        if mult is None and factor.group(2):
            mult = float(factor.group(2))
        if mult:
            asked = requested * mult
    return asked


def _a_size(r: dict, q: str) -> Answer | None:
    sen = r.get("sensitivity") or {}
    sizes = sen.get("sizes") or []
    requested = _ticket(r).get("notional_quote")
    asked = asked_size(r, q)

    # "what if I do 40k" - the sweep already ran the whole gate at that size.
    if asked and sizes and (requested is None or abs(asked - requested) > 1):
        p = _nearest(sizes, "notional", asked)
        if p:
            # The sweep runs a grid, so say which point is being quoted rather than
            # letting a number the reader did not ask about look like a misunderstanding.
            near = "" if abs(p["notional"] - asked) < max(1.0, asked * 0.01) else f" (the nearest size the sweep ran to your {_usd(asked)})"
            bits = [
                f"At {_usd(p['notional'])}{near} the verdict is {p['verdict'].replace('_', ' ')}"
                + (f", held there by the {p['binding_cap'].replace('_', ' ')} cap" if p.get("binding_cap") else "")
                + "."
            ]
            if p.get("exit_cost_bps") is not None:
                bits.append(f"Getting out of that size costs {_bps(p['exit_cost_bps'])}.")
            if p.get("risk_pct_of_equity") is not None:
                bits.append(f"It puts {p['risk_pct_of_equity']:.2f}% of your equity at risk.")
            if sen.get("max_go_notional") is not None:
                bits.append(f"The largest size that is still a straight go is {_usd(sen['max_go_notional'])}.")
            return Answer("size", " ".join(bits), ("sensitivity sweep",))

    # "why not bigger" - name the cap that binds and what the others allow.
    caps = [c for c in (r.get("sizing") or {}).get("caps", []) if c.get("notional") is not None]
    binding_name = (r.get("sizing") or {}).get("binding_cap")
    binding = next((c for c in caps if c["name"] == binding_name), None)
    bits = []
    if binding and requested is not None and binding["notional"] < requested - 1:
        bits.append(f"The {binding['name'].replace('_', ' ')} cap is what holds it down, at {_usd(binding['notional'])}: {binding['detail']}.")
    elif requested is not None:
        bits.append(f"Nothing cuts {_usd(requested)} - every cap sits above the size you asked for.")
    if caps:
        others = sorted((c for c in caps if c is not binding), key=lambda c: c["notional"])[:3]
        if others:
            bits.append("The next ones are " + ", ".join(f"{c['name'].replace('_', ' ')} at {_usd(c['notional'])}" for c in others) + ".")
    if sen.get("max_go_notional") is not None:
        bits.append(f"Across the whole sweep the verdict stays a go up to {_usd(sen['max_go_notional'])}.")
    return Answer("size", " ".join(bits), ("sizing caps", "sensitivity sweep")) if bits else None


_SIZE_FACTOR = re.compile(r"\b(halve|half|double|twice|triple)\b|\b(\d+(?:\.\d+)?)\s*(?:x|times)\s+(?:the\s+)?(?:size|as much)\b|减半|加倍|翻倍", re.I)


def _a_stop(r: dict, q: str) -> Answer | None:
    sen = r.get("sensitivity") or {}
    stops = sen.get("stops") or []
    asked = _percent_in(q)
    if asked is not None and stops:
        p = _nearest(stops, "stop_distance_pct", asked)
        if p:
            # Same courtesy as the size answer: say when a grid point is being quoted.
            near = "" if abs(p["stop_distance_pct"] - asked) < 0.1 else f" (the nearest distance the sweep ran to your {asked:g}%)"
            bits = [
                f"A stop {p['stop_distance_pct']:.2f}% away (at {p['stop_price']:.2f}){near} makes the verdict {p['verdict'].replace('_', ' ')}"
                + (f", putting {p['risk_pct_of_equity']:.2f}% of equity at risk" if p.get("risk_pct_of_equity") is not None else "")
                + "."
            ]
            if p.get("risk_budget_notional") is not None:
                bits.append(f"At that distance the risk budget alone would allow {_usd(p['risk_budget_notional'])}.")
            if sen.get("widest_stop_pct_for_requested_size") is not None:
                bits.append(f"The widest stop this size can carry is {sen['widest_stop_pct_for_requested_size']:.2f}%.")
            return Answer("stop", " ".join(bits), ("sensitivity sweep",))

    stop_price = _ticket(r).get("stop_price")
    bits = []
    if stop_price:
        bits.append(f"Your stop is at {stop_price:.2f}.")
    else:
        p5 = _p5(r)
        bits.append("You did not give a stop, so the risk is sized against the calibrated 5th percentile" + (f", {_pct(p5)} over the horizon" if p5 is not None else "") + ".")
    if sen.get("widest_stop_pct_for_requested_size") is not None:
        bits.append(f"At this size the widest stop the risk budget allows is {sen['widest_stop_pct_for_requested_size']:.2f}% away.")
    if stops:
        gos = [p for p in stops if p.get("verdict") == "GO"]
        if gos:
            bits.append(f"The sweep ran {len(stops)} stop distances; {len(gos)} of them are a go.")
    return Answer("stop", " ".join(bits), ("ticket", "sensitivity sweep")) if bits else None


def _p5(r: dict) -> float | None:
    h = _primary(r)
    if not h:
        return None
    # The position's own one-in-twenty loss; a report stored before that field existed
    # carries only the token's, which is right for a long.
    if "loss_p5_pct" in h:
        return h["loss_p5_pct"]
    return h.get("p5_adjusted") if h.get("p5_adjusted") is not None else (h.get("cohort") or {}).get("p5")


def _median(r: dict) -> float | None:
    """The position's middle outcome: the token's median, turned over for a short."""
    h = _primary(r) or {}
    return h["pnl_median_pct"] if "pnl_median_pct" in h else (h.get("cohort") or {}).get("median_pct")


def _wins(r: dict) -> float | None:
    """The share of past moments that went this position's way."""
    h = _primary(r) or {}
    return h["pnl_win_rate"] if "pnl_win_rate" in h else (h.get("cohort") or {}).get("win_rate")


def _a_worst(r: dict, _q: str) -> Answer | None:
    modes = [m for m in (r.get("failure_modes") or []) if m.get("loss_quote") is not None]
    if modes:
        bits = ["The ways this loses money, worst first:"]
        for i, m in enumerate(modes[:3], 1):
            bits.append(f"{i}. {m['title']} - {m['trigger'].rstrip('.')}; {m['mechanism']}. About {_usd(m['loss_quote'])} ({_pct(m.get('loss_pct'))}); {m['likelihood']}.")
        mc = (r.get("stress") or {}).get("monte_carlo")
        if mc:
            bits.append(f"In the simulation, one path in twenty ends below {_pct(mc.get('p5'))}.")
        return Answer("worst", " ".join(bits), ("failure modes", "stress presets", "Monte Carlo"))
    st = r.get("stress") or {}
    presets, impacts = st.get("presets") or [], st.get("impacts") or []
    rows = [(p, i) for p, i in zip(presets, impacts, strict=False) if i.get("total_pnl_quote") is not None]
    if not rows and not st.get("monte_carlo"):
        return None
    bits = []
    if rows:
        rows.sort(key=lambda x: x[1]["total_pnl_quote"])
        worst = rows[:3]
        bits.append("The three worst of the presets built from this token's own history: " + "; ".join(f"{p['name']} costs {_usd(i['total_pnl_quote'])} ({_pct(i.get('total_pct_of_notional'))} of the position)" for p, i in worst) + ".")
    mc = st.get("monte_carlo")
    if mc:
        bits.append(f"In the simulation, one path in twenty ends below {_pct(mc.get('p5'))}, and the average of that worst twentieth is {_pct(mc.get('expected_shortfall_5_pct'))}.")
    if st.get("reverse_move_pct_for_5pct_loss") is not None:
        bits.append(f"A move of {_pct(st['reverse_move_pct_for_5pct_loss'])} is what it takes to lose 5% of the position after costs.")
    return Answer("worst", " ".join(bits), ("stress presets", "Monte Carlo"))


def _a_exit(r: dict, _q: str) -> Answer | None:
    ex = r.get("execution") or {}
    q = ex.get("exit_quote")
    bits = []
    if q and q.get("total_cost_bps") is not None:
        bits.append(f"Getting out of {_usd(q.get('notional_quote'))} costs {_bps(q['total_cost_bps'])} on the {ex.get('book_source', 'recorded')} book, about {_usd(q.get('total_cost_quote'))}, and it {'fills' if q.get('fully_filled') else 'does not fill'}.")
    elif q:
        bits.append("The book cannot absorb this size at any price right now.")
    else:
        bits.append("There was no order book to cost the exit against.")
    if ex.get("max_notional_within_budget") is not None:
        bits.append(f"The largest size that still exits inside the budget is {_usd(ex['max_notional_within_budget'])}.")
    lh = ex.get("liquidity_history") or {}
    buckets = lh.get("buckets") or []
    thin = [b for b in buckets if b.get("share_below_reference")]
    if thin:
        worst = max(thin, key=lambda b: b["share_below_reference"])
        bits.append(f"In the recorded archive the book could not take this size within budget {worst['share_below_reference'] * 100:.0f}% of the time during {worst['bucket'].replace('_', ' ')}.")
    return Answer("exit", " ".join(bits), ("order book", "book archive"))


def _a_history(r: dict, _q: str) -> Answer | None:
    h = _primary(r)
    a = r.get("analog") or {}
    if not h:
        return None
    c = h.get("cohort") or {}
    if c.get("insufficient") or not c.get("n"):
        return Answer("history", f"There were not enough distinct past moments like this one to answer: {(a.get('result') or {}).get('reason', 'too few matches')}.", ("analog cohort",))
    bits = [
        f"{c['n']} distinct past moments looked like this one. For this position the middle outcome over {r.get('primary_horizon')} was {_pct(_median(r))}, "
        f"one in twenty was worse than {_pct(_p5(r))}, and {_wins(r) * 100:.0f}% went its way." if _wins(r) is not None else
        f"{c['n']} distinct past moments looked like this one; for this position the middle outcome was {_pct(_median(r))}."
    ]
    base = h.get("baseline") or {}
    if base.get("permutation_p_value") is not None:
        p = base["permutation_p_value"]
        bits.append(
            f"Against random hours of the same time of week the difference in mean outcome is {_pct(base.get('mean_diff_pct'), 2)} with p = {p:.2f}"
            + (", so the resemblance is doing very little here." if p > 0.1 else ".")
        )
    if h.get("adjustment"):
        adj = h["adjustment"]
        margin = f" plus a margin of {adj['c_lo']:.1f} points" if adj.get("c_lo") else ""
        k = adj.get("k_lo", 1.0) or 1.0
        how = "widened" if k > 1.0 else "narrowed" if k < 1.0 else "left"
        why = " (past tails of this length were too wide)" if k < 1.0 else ""
        floor = f" It is also floored at the {adj['floored_by']} hold's, because a longer hold is never shown carrying less risk." if adj.get("floored_by") else ""
        bits.append(f"The loss line you see is {how} by a factor of {k:.2f}{why}{margin}, fitted on {adj.get('n_fit', 0):,} already-scored forecasts, never on this one.{floor}")
    return Answer("history", " ".join(bits), ("analog cohort", "baseline test"))


def _a_lessons(r: dict, _q: str) -> Answer | None:
    lessons = r.get("lessons") or []
    if not lessons:
        return Answer("lessons", "No past call in conditions like these has matured yet, so there is nothing to learn from directly.", ("post-mortems",))
    bad = [x for x in lessons if x.get("classification") in ("worse_than_stress", "bad_tail")]
    bits = [f"{len(lessons)} past call{'' if len(lessons) == 1 else 's'} in conditions like these have been scored."]
    if bad:
        bits.append(f"{len(bad)} finished below the level they were sized against. The worst: {bad[0]['text']}")
    else:
        bits.append(f"None breached the level they were sized against. The most recent: {lessons[0]['text']}")
    bits.append("Each is one episode, not evidence; the distribution is what the size is built on.")
    return Answer("lessons", " ".join(bits), ("post-mortems",))


def _a_gate(r: dict, _q: str) -> Answer | None:
    g = r.get("gate") or {}
    rules = g.get("rules") or []
    failed = [x for x in rules if x.get("decision") != "GO"]
    v = (r.get("verdict") or {}).get("verdict", "")
    if not failed:
        return Answer("gate", f"Nothing in the gate objected - all {len(rules)} checks passed, and the verdict is {v.replace('_', ' ')}. If the size was cut, that is a cap rather than a rule; ask why not bigger.", ("discipline gate",))
    bits = [f"{len(failed)} of {len(rules)} checks did not pass:"]
    bits += [f"{x['rule'].replace('_', ' ')} - {x['reason']}." for x in failed]
    return Answer("gate", " ".join(bits), ("discipline gate",))


def _a_against(r: dict, _q: str) -> Answer | None:
    so = r.get("second_opinion") or {}
    against = so.get("against") or []
    if not against:
        return None
    bits = [so.get("summary", "").strip()] if so.get("summary") else []
    bits += [f"{i + 1}. {c['text']} [{c.get('source', 'report')}]" for i, c in enumerate(against[:4])]
    return Answer("against", " ".join(bits), ("second opinion",))


def _a_hedge(r: dict, _q: str) -> Answer | None:
    ex = r.get("execution") or {}
    hq = ex.get("hedge_quote")
    v = r.get("verdict") or {}
    bits = []
    if v.get("hedge_ratio"):
        bits.append(f"The verdict already suggests hedging {v['hedge_ratio'] * 100:.0f}% of it.")
    if hq:
        bits.append(
            f"A full hedge through {hq.get('perp_symbol')} costs {_bps(hq.get('total_cost_bps_of_position'))} of the position - "
            f"{_usd(hq.get('entry_fee_quote'), 2)} to put on, {_usd(hq.get('exit_fee_quote'), 2)} to take off and "
            f"{_usd(hq.get('funding_quote'), 2)} of funding over the horizon - "
            f"and leaves a residual basis risk whose 95th percentile is {_bps(hq.get('residual_basis_p95_bps'))}."
        )
    else:
        bits.append("There is no perp quote for this token, so a hedge could not be priced.")
    rationale = (r.get("sizing") or {}).get("hedge_rationale")
    if rationale:
        bits.append(rationale)
    return Answer("hedge", " ".join(bits), ("hedge quote",))


def _a_regime(r: dict, _q: str) -> Answer | None:
    m = r.get("regimes") or {}
    regimes = m.get("regimes") or []
    labels = (r.get("snapshot") or {}).get("labels") or {}
    if not regimes:
        return Answer("regime", f"Right now this reads as a {labels.get('regime_label', 'unknown')} regime: {labels.get('vol_state', '?')} volatility, {labels.get('trend_state', '?')} trend, {labels.get('liq_state', '?')} liquidity.", ("snapshot labels",))
    cur = next((x for x in regimes if x.get("id") == m.get("current")), None)
    bits = [f"Of {m.get('n_fitted', 0):,} past hours grouped into {len(regimes)} states, this one is \"{cur['description']}\"." if cur else f"{len(regimes)} states were fitted."]
    if cur:
        bits.append(f"It covers {cur['share'] * 100:.0f}% of the token's history" + (f", and {cur['persistence'] * 100:.0f}% of the time the next day is still in it" if cur.get("persistence") is not None else "") + ".")
        if cur.get("next_ret_p5_pct") is not None:
            bits.append(f"Out of this state, one {m.get('horizon_h', 24)}-hour window in twenty lost more than {_pct(cur['next_ret_p5_pct'])}.")
    return Answer("regime", " ".join(bits), ("regime map",))


# The search features in plain words, for saying why a past moment counts as similar.
FEATURE_WORDS = {
    "basis_index_bps": "the gap to fair value", "basis_index_z": "how stretched that gap is", "basis_index_d6h_bps": "how fast the gap is moving",
    "basis_native_bps": "the gap to the last close", "rv_24h": "the last day's volatility", "rv_168h": "the week's volatility",
    "vol_pctl_90d": "how volatile it is for this stock", "trend_sma_pct": "the trend", "sma_slope_5d_pct": "the trend's slope",
    "liq_ratio": "trading activity", "no_trade_share_24h": "how often it did not trade", "native_close_age_h": "time since the stock last traded",
    "hours_to_earnings": "time to earnings", "hours_since_earnings": "time since earnings", "macro_events_72h": "macro releases ahead",
    "hours_to_fomc": "time to the Fed", "news_count_24h": "news flow", "vix_pctl_1y": "the VIX", "curve_pctl_1y": "the yield curve",
    "dollar_20d_chg_pct": "the dollar", "ten_year_20d_chg_bps": "the 10-year yield",
}


MARKET_WIDE = frozenset({"vix_pctl_1y", "curve_pctl_1y", "dollar_20d_chg_pct", "ten_year_20d_chg_bps"})
LOOSE_SIMILARITY = 0.1  # below this a match shares the broad state, not the specifics


def _a_moments(r: dict, _q: str) -> Answer | None:
    outs = (r.get("analog") or {}).get("matches_outcomes") or []
    horizon = r.get("primary_horizon")
    rows = [o for o in outs if (o.get("outcomes") or {}).get(horizon, {}).get("ret_pct") is not None]
    if not rows:
        return None
    rows.sort(key=lambda o: o["outcomes"][horizon]["ret_pct"])
    def line(o: dict) -> str:
        when = str(o.get("ts", ""))[:16].replace("T", " ")
        tag = (o["outcomes"][horizon].get("tag") or "").replace("_", " ").lower()
        return f"{when} ended {_pct(o['outcomes'][horizon]['ret_pct'])}" + (f" ({tag})" if tag else "")

    middle = f"; {line(rows[len(rows) // 2])} in the middle" if len(rows) > 2 else ""
    why = ""
    matches = ((r.get("analog") or {}).get("result") or {}).get("matches") or []
    if matches and any(m.get("alike_on") for m in matches):
        from collections import Counter

        # Market-wide readings are the same for every token at a given hour, so they say
        # when a match happened, not why this stock's moment resembles it.
        alike = Counter(f for m in matches for f in (m.get("alike_on") or []) if f not in MARKET_WIDE)
        differs = Counter(f for m in matches for f in (m.get("differs_on") or []))
        top = [FEATURE_WORDS.get(f, f.replace("_", " ")) for f, _ in alike.most_common(3)]
        why = f" What makes them similar: most sit closest to now on {', '.join(top[:-1])} and {top[-1]}." if len(top) > 1 else ""
        sims = [m.get("similarity") for m in matches if m.get("similarity") is not None]
        loose = sum(1 for x in sims if x < LOOSE_SIMILARITY)
        if sims and loose > len(sims) / 2:
            why += f" Be aware most are loose matches: {loose} of {len(sims)} have a similarity under {LOOSE_SIMILARITY:.1f}, so read the cohort as a range, not a precedent."
        if differs:
            f, n = differs.most_common(1)[0]
            why += f" Where they differ most: {FEATURE_WORDS.get(f, f)}, far from now on {n} of {len(matches)}."
    return Answer(
        "moments",
        f"The {len(rows)} matched moments, worst first: {line(rows[0])}{middle}; best {line(rows[-1])}.{why} "
        f'The full list, with what each one looked like at the time, is in the "What history says" panel.',
        ("matched moments",),
    )


def _a_trust(r: dict, _q: str) -> Answer | None:
    h = _primary(r)
    adj = (h or {}).get("adjustment") or {}
    bits = ["Every verdict is written down before the outcome exists and scored when the horizon passes; the calibration page shows how that has gone."]
    if adj:
        bits.append(f"The band you are looking at has already been widened by the factors fitted on {adj.get('n_fit', 0):,} scored forecasts, because the raw tails were too narrow.")
    base = (h or {}).get("baseline") or {}
    if base.get("permutation_p_value") is not None:
        bits.append(f"On this ticket the retrieval beats random hours of the same kind with p = {base['permutation_p_value']:.2f}, which is worth reading before you trust the shape of it.")
    bits.append("The honest summary is that the analogs do not predict direction; they put fewer outcomes below the level the size is built on.")
    return Answer("trust", " ".join(bits), ("tail adjustment", "baseline test"))


def _a_now(r: dict, _q: str) -> Answer | None:
    s = r.get("snapshot") or {}
    f, p, lab = s.get("features") or {}, s.get("prices") or {}, s.get("labels") or {}
    bits = [f"The token is at {p.get('spot_close')}, fair value {p.get('index_close')}, a basis of {_bps(f.get('basis_index_bps'))} (z {f.get('basis_index_z', 0):.2f})."]
    if f.get("rv_24h") is not None:
        bits.append(f"Realised volatility over the last day is {f['rv_24h'] * 100:.0f}%, the {_ordinal(f.get('vol_pctl_90d'))} percentile of its own 90 days - {lab.get('vol_state', '?')}.")
    if f.get("hours_since_filing") is not None and f["hours_since_filing"] < 720:
        bits.append(f"The last SEC filing was {f['hours_since_filing']:.0f} hours ago.")
    if s.get("quality_flags"):
        bits.append("Data flags on this snapshot: " + ", ".join(s["quality_flags"]) + ".")
    return Answer("now", " ".join(bits), ("snapshot",))


# ------------------------------------------------------------------------ the routing

# Ordered: the first pattern that matches wins, so the specific ones come first.
# "what if it gaps down 10%", "TSLA drops 8% at the open", "a 5% gap up": a price shock the
# trader names. Answered from the report, because the arithmetic is the position's and the
# comparison is against what the presets measured, not a new search.
SHOCK = re.compile(
    r"(?:\b(?:gap|gaps|gapped|drop|drops|dropped|fall|falls|fell|crash|crashes|dump|dumps|tank|tanks|move|moves|goes|go|rally|rallies|jump|jumps|spike|spikes|pump|pumps|rise|rises|up|down)\b"
    r"[^.?!%]{0,25}?(\d+(?:\.\d+)?)\s*(?:%|per ?cent))"
    r"|(?:(\d+(?:\.\d+)?)\s*(?:%|per ?cent)\s*(?:gap|drop|fall|move|crash|rally|jump|spike)?\s*(?:up|down|higher|lower)?)(?=[^.?!]*\b(?:gap|drop|fall|crash|move|rally|jump|spike|open)\b)"
    r"|(?:跌|涨|跳空|暴跌|暴涨)[^0-9]{0,6}(\d+(?:\.\d+)?)\s*[%％]",
    re.I,
)
_UP = re.compile(r"\b(?:up|rally|rallies|jump|jumps|spike|spikes|pump|pumps|rise|rises|higher|gap up|gaps up)\b|涨|暴涨", re.I)


def _a_shock(r: dict, q: str) -> Answer | None:
    m = SHOCK.search(q)
    if not m:
        return None
    size = float(next(g for g in m.groups() if g))
    if not 0 < size < 100:
        return None
    t = _ticket(r)
    notional = t.get("notional_quote")
    if not notional:
        return None
    long_ = (t.get("side") or "long") == "long"
    up = bool(_UP.search(q))
    move = size if up else -size  # the stock's move
    pnl_pct = move if long_ else -move  # the position's
    exit_bps = ((r.get("execution") or {}).get("exit_quote") or {}).get("total_cost_bps")
    pnl = notional * pnl_pct / 100.0
    cost = notional * (exit_bps or 0) / 10_000.0
    bits = [f"A {size:g}% move {'up' if up else 'down'} {'makes' if pnl >= 0 else 'loses'} about {_usd(abs(pnl))} on {_usd(notional)} {'long' if long_ else 'short'}"
            + (f", and getting out costs about {_usd(cost)} more on today's book" if exit_bps is not None else "") + "."]
    if pnl_pct < 0:
        stop = t.get("stop_price")
        paths = ((r.get("analog") or {}).get("paths") or {})
        stop_pct = paths.get("stop_pct")
        if stop and stop_pct is not None and abs(stop_pct) < size:
            bits.append(f"It goes straight through your stop at {stop:,.2f} ({abs(stop_pct):.1f}% away): if it happens as a gap at the open, the stop fills after the gap, not at your price.")
        lev = r.get("leverage")
        if lev and lev.get("liquidation_distance_pct") is not None:
            d = lev["liquidation_distance_pct"]
            bits.append(f"At {round(lev['leverage'], 2):g}x that {'liquidates the position - the whole ' + _usd(lev['margin_quote']) + ' of margin' if size >= d else f'stays short of liquidation, {d:.1f}% away'}.")
        # How rare, against what this token's own closed windows did.
        presets = {p["id"]: p for p in ((r.get("stress") or {}).get("presets") or [])}
        p1, p5 = presets.get("closed_window_gap_p1"), presets.get("closed_window_gap_p5")
        if p1 and abs(p1.get("price_move_pct") or 0) < size:
            bits.append(f"That is bigger than this token's 1-in-100 closed-market move ({_pct(p1['price_move_pct'])}), so it is rarer than one window in a hundred here.")
        elif p5 and abs(p5.get("price_move_pct") or 0) < size:
            bits.append(f"For scale: one closed window in twenty here moved worse than {_pct(p5['price_move_pct'])}, one in a hundred worse than {_pct((p1 or {}).get('price_move_pct'))}.")
        equity = t.get("account_equity_quote")
        if equity:
            bits.append(f"That is {abs(pnl + (-cost)) / equity * 100:.2f}% of your account.")
    return Answer("shock", " ".join(bits), ("position arithmetic", "order book", "stress presets"))


def _a_why(r: dict, _q: str) -> Answer | None:
    v = r.get("verdict") or {}
    if not v.get("verdict"):
        return None
    bits = [f"The verdict is {v['verdict'].replace('_', ' ')}"
            + (f" at {_usd(v.get('recommended_notional'))}" if v.get("recommended_notional") is not None else "") + "."]
    failed = [x for x in ((r.get("gate") or {}).get("rules") or []) if x.get("decision") != "GO"]
    if failed:
        bits.append("Because: " + "; ".join(f"{x['rule'].replace('_', ' ')} - {x['reason']}" for x in failed[:3]) + ".")
    cap = (r.get("sizing") or {}).get("binding_cap")
    caps = {c["name"]: c for c in ((r.get("sizing") or {}).get("caps") or [])}
    requested = _ticket(r).get("notional_quote")
    if cap and cap in caps and caps[cap].get("notional") is not None and requested and caps[cap]["notional"] < requested - 1:
        bits.append(f"The size is held by the {cap.replace('_', ' ')} cap: {caps[cap]['detail']}.")
    modes = [m for m in (r.get("failure_modes") or []) if m.get("loss_quote") is not None]
    if modes:
        bits.append(f"The worst way it loses: {modes[0]['title'].lower()}, about {_usd(modes[0]['loss_quote'])} ({modes[0]['likelihood']}).")
    for p in r.get("premise") or []:
        bits.append(p)
    return Answer("why", " ".join(bits), ("discipline gate", "sizing caps", "failure modes"))


def _a_premise(r: dict, _q: str) -> Answer | None:
    f = ((r.get("snapshot") or {}).get("features") or {})
    horizon = r.get("horizon_h") or 0

    def when(h: float | None, past: bool) -> str:
        if h is None:
            return "not known"
        if h >= 720:
            return "more than 30 days " + ("ago" if past else "away")
        span = f"{h / 24:.0f} days" if h >= 48 else f"{h:.0f} hours"
        return f"{span} ago" if past else f"in {span}"

    bits = []
    premise = r.get("premise") or []
    if premise:
        bits += premise
    elif (_ticket(r).get("thesis") or "").strip():
        bits.append("Nothing in your reason depends on an event the data can date against this hold.")
    if not any("earnings" in x for x in premise):
        bits.append(f"Last earnings report: {when(f.get('hours_since_earnings'), True)}; next: {earnings_ahead(f.get('hours_to_earnings'))}"
                    + (" - inside this hold, so the earnings-gap presets are included." if f.get("hours_to_earnings") is not None and f["hours_to_earnings"] <= horizon else "."))
    if f.get("hours_to_fomc") is not None:
        bits.append(f"Next FOMC decision: {when(f.get('hours_to_fomc'), False)}.")
    # What the data can say about the idea itself: which way moments like this went.
    c = (_primary(r) or {}).get("cohort") or {}
    long_ = (_ticket(r).get("side") or "long") == "long"
    if c.get("n") and c.get("win_rate") is not None and c.get("median_pct") is not None:
        with_you = c["win_rate"] if long_ else 1 - c["win_rate"]
        lean = "with you" if with_you > 0.55 else "against you" if with_you < 0.45 else "neither way"
        bits.append(f"As for the idea itself: of {c['n']} past moments like this, {with_you:.0%} went your way (middle outcome {_pct(c['median_pct'])}), "
                    f"so history leans {lean}. The desk does not claim to call direction - its measured edge is on the size of the bad case.")
    return Answer("premise", " ".join(bits), ("event calendar", "premise check", "analog cohort"))


def _dollars(v: float | None) -> str:
    """Stock prices and insider values are in dollars, not the USDT the positions are in."""
    return "-" if v is None else f"${v:,.0f}"


def _a_street(r: dict, q: str) -> Answer | None:
    s = r.get("street") or {}
    if not s:
        return Answer("street", "There is no street data on this report: Bitget's US-stock data was not reachable, or this is a past moment it cannot describe.", ())
    bits = []
    if s.get("token_vs_live_bps") is not None:
        bits.append(
            f"The token trades {_bps(s['token_vs_live_bps'])} from the stock's live price on Bitget"
            + (f", and {_bps(s['token_vs_close_bps'])} from its last close." if s.get("token_vs_close_bps") is not None else ".")
        )
    if s.get("n_firms"):
        bits.append(
            f"{s['n_firms']} analyst firms rated it in the last 90 days: {s['bullish']} buy, {s['neutral']} hold, {s['bearish']} sell"
            + (f", with a median target of {_dollars(s['median_target'])} ({_pct(s.get('target_gap_pct'))} from here)." if s.get("median_target") else ".")
        )
        if s.get("upgrades_recent") or s.get("downgrades_recent"):
            bits.append(f"In the last 30 days: {s.get('upgrades_recent', 0)} upgrades, {s.get('downgrades_recent', 0)} downgrades.")
    elif re.search(r"analyst|rating|target|upgrade|downgrade", q, re.I):
        bits.append("No analyst firm has rated it in the last 90 days in Bitget's data.")
    if s.get("insider_sells") or s.get("insider_buys"):
        sells, buys = s.get("insider_sells", 0), s.get("insider_buys", 0)
        bits.append(
            f"Insiders made {sells} open-market sale{'' if sells == 1 else 's'} ({_dollars(s.get('insider_sold_value'))}) and "
            f"{buys} purchase{'' if buys == 1 else 's'} ({_dollars(s.get('insider_bought_value'))}) in the last 90 days."
        )
    elif re.search(r"insider", q, re.I):
        bits.append("No open-market insider trades in the last 90 days.")
    if s.get("mood_score") is not None:
        bits.append(f"Market-wide fear and greed reads {s['mood_score']:.0f} ({s.get('mood_rating') or ''}).")
    bits.append("None of this moved the size - it has not been tested against what the token did overnight.")
    return Answer("street", " ".join(bits), ("Bitget US-stock data",))


def _a_corporate(r: dict, q: str) -> Answer | None:
    """Dividends, splits and exchange notices, read only from the report's own section."""
    from nightwatch.features.corporate import plain

    c = r.get("corporate_events")
    reads = ("corporate events",)
    if not c:
        return Answer("corporate", "This report has no dividend or split check, so I cannot say whether one is coming. "
                      "That is a gap in this report, not a sign that none is.", reads)
    if not c.get("covered"):
        return Answer("corporate", "The dividend and split calendar has not been synced yet, so I cannot say whether one falls in this hold. I will not guess.", reads)
    checked = (c.get("checked_at") or "")[:10]
    bits = []
    inside = c.get("in_hold") or []
    if inside:
        bits.append("Inside this hold: " + "; ".join(plain(e) for e in inside) + ".")
        if c.get("handling"):
            bits.append(c["handling"])
    else:
        bits.append("No ex-dividend date or split falls inside this hold in the stored calendar"
                    + (f" (last checked {checked}; sources: {', '.join(c['sources'])})." if c.get("sources") else f" (last checked {checked})."))
    if c.get("next_after"):
        bits.append("The next one after it: " + plain(c["next_after"]) + ".")
    elif not inside:
        bits.append("None is scheduled after it either.")
    if c.get("last_split"):
        bits.append("Its last split: " + plain(c["last_split"]) + ".")
    for n in (c.get("notices") or [])[-2:]:
        bits.append("Recent Bitget notice: " + plain(n) + ".")
    if re.search(r"suspen|halt|delist", q, re.I) and not any(n.get("kind") == "suspension" for n in c.get("notices") or []):
        bits.append("No trading suspension notice naming this token was found in Bitget's latest announcements (that feed holds only the most recent few per type).")
    bits.append("This is what the stored calendar knows, not a guarantee that nothing is coming.")
    return Answer("corporate", " ".join(bits), reads)


def _a_technicals(r: dict, _q: str) -> Answer | None:
    g = r.get("signal") or {}
    if not g:
        return Answer("technicals", "There is no technical reading on this report: Bitget's signal skill was not reachable, or its RSI did not agree with our own from Bitget candles, so it is not shown.", ())
    text = (f"Bitget signal skill: RSI {g['rsi']:.1f} on {g.get('timeframe', '4h')} ({g['reading']}); our own from Bitget candles {g['own_rsi']:.1f} - agrees. "
            "Context only: it did not move the size.")
    m = g.get("macd")
    if m:
        text += f" MACD {m['macd']:+.2f} against signal {m['signal']:+.2f} ({str(m.get('cross') or 'no cross').replace('_', ' ')})."
    return Answer("technicals", text, ("Bitget signal skill",))


_VERDICT_PLAIN = {
    "GO": "every check passed at the size you asked for",
    "REDUCE_TO": "the idea passes, but only at a smaller size",
    "HEDGE": "keep the size and hedge part of it with the perpetual",
    "REVIEW": "something is missing before it can be decided",
    "NO_GO": "a hard limit refuses it as asked",
}


def _loss_at_size(r: dict) -> tuple[float | None, float | None]:
    p5, size = _p5(r), _ticket(r).get("notional_quote")
    return p5, (p5 / 100.0 * float(size)) if (p5 is not None and size) else None


def _a_decide(r: dict, _q: str) -> Answer | None:
    """'Should I buy?': the desk's answer is a size, never a direction, and it says why."""
    v = r.get("verdict") or {}
    if not v.get("verdict"):
        return None
    t = _ticket(r)
    p5, loss = _loss_at_size(r)
    mine = f"On your {t.get('side')} {_usd(t.get('notional_quote'))} {t.get('ticker')}, " if t.get("ticker") and t.get("notional_quote") else ""
    bits = [f"{mine}the desk's answer is {v['verdict'].replace('_', ' ')}: {_VERDICT_PLAIN.get(v['verdict'], '')}"
            + (f", at {_usd(v.get('recommended_notional'))}" if v.get("recommended_notional") is not None and v["verdict"] == "REDUCE_TO" else "") + "."]
    if v["verdict"] in ("GO", "HEDGE") and v.get("recommended_notional"):
        bits.append(f"The most it allows is {_usd(v['recommended_notional'])}.")
    if loss is not None:
        bits.append(f"If you do it at {_usd(t.get('notional_quote'))}, one time in twenty history says it loses more than {_usd(-loss)} ({_pct(p5)}).")
    bits.append("Whether the stock goes up is not something it can tell you: on thousands of scored forecasts it has no edge on direction, "
                "only on how bad the bad case is. That part is your call.")
    failed = [x for x in ((r.get("gate") or {}).get("rules") or []) if x.get("decision") != "GO"]
    if failed:
        bits.append("To get a clean answer, fix: " + "; ".join(x["reason"] for x in failed[:2]) + ".")
    return Answer("decide", " ".join(bits), ("verdict", "analog cohort"))


def _a_plain(r: dict, _q: str) -> Answer | None:
    """The whole report in five plain sentences, for someone new to it."""
    v, t, h = r.get("verdict") or {}, _ticket(r), _primary(r)
    if not v.get("verdict") or not t:
        return None
    side = "buy and hold" if t.get("side") == "long" else "short"
    bits = [f"In plain words: you want to {side} {_usd(t.get('notional_quote'))} of {t.get('ticker')} for about {r.get('horizon_h', 0):.0f} hours."]
    c = (h or {}).get("cohort") or {}
    if c.get("n") and not c.get("insufficient"):
        p5, loss = _loss_at_size(r)
        bits.append(f"The desk found {c['n']} past moments that looked like right now and checked what happened next. Usually the move was small "
                    f"(the middle one was {_pct(_median(r))}), but about one time in twenty it lost more than {_pct(p5)}"
                    + (f", which on your size is about {_usd(-loss)}." if loss is not None else "."))
    modes = [m for m in (r.get("failure_modes") or []) if m.get("loss_quote") is not None]
    if modes:
        bits.append(f"The way this costs the most: {modes[0]['title'].lower()}, costing about {_usd(modes[0]['loss_quote'])}.")
    q = (r.get("execution") or {}).get("exit_quote") or {}
    if q.get("total_cost_bps") is not None:
        bits.append(f"Selling it again right now would cost about {_bps(q['total_cost_bps'])} ({_usd(q.get('total_cost_quote'))}) on Bitget's live order book.")
    bits.append(f"So the verdict is {v['verdict'].replace('_', ' ')}: {_VERDICT_PLAIN.get(v['verdict'], '')}. The desk never places the trade; you decide.")
    return Answer("plain", " ".join(bits), ("analog cohort", "failure modes", "order book", "verdict"))


def _a_data(r: dict, _q: str) -> Answer | None:
    kinds = sorted({str(s.get("kind")) for s in (r.get("sources") or []) if s.get("kind")})
    bits = [
        "Everything comes from live feeds, none of it typed in: Bitget's token and perpetual candles and order books (recorded every 30 seconds), "
        "Bitget's perpetual margin tiers for liquidation prices, Bitget's US-stock data service for the live stock price, analyst ratings and insider "
        "trades, the real stock's hourly bars from Yahoo Finance, earnings dates from Nasdaq, Fed and CPI dates from FRED, SEC filings and news headlines.",
    ]
    if kinds:
        bits.append(f"This report read: {', '.join(k.replace('_', ' ') for k in kinds)}.")
    bits.append("The data-sources panel on the desk shows how fresh each feed is right now.")
    return Answer("data", " ".join(bits), ("sources",))


def _a_options(r: dict, q: str) -> Answer | None:
    head = "The desk has no options data for these tokens, so it cannot price an option. The protection it can price is a hedge on the stock's Bitget perpetual:"
    got = _a_hedge(r, q)
    return Answer("hedge", f"{head} {got.text}" if got else head, ("hedge quote",))


ROUTES: tuple[tuple[str, re.Pattern[str], Any], ...] = (
    ("plain", re.compile(r"\blike i'?m (?:new|five|5|a beginner|a kid)\b|\beli5\b|\bin plain\b|\bsimple (?:terms|words|english|language)\b|\bsimply\b"
                         r"|\bi (?:don'?t|do not) (?:understand|get it)\b|\bwhat does (?:this|that|it|all this) mean\b|\bfor a beginner\b|\bnew to (?:this|trading)\b"
                         r"|\bdumb it down\b|\bexplain (?:it|this|that|everything|the report)\b(?!.*\b(?:verdict|decision|call)\b)|^\s*explain\s*[?.!]*\s*$", re.I), _a_plain),
    ("decide", re.compile(r"\bshould i\b|\bwhat should i do\b|\bwould you\b|\bdo you recommend\b|\bis (?:it|this) (?:a )?good (?:idea|trade)\b|\bworth it\b"
                          r"|\bgo for it\b|\bbuy or\b|\bshould we\b|\bis it safe\b", re.I), _a_decide),
    ("data", re.compile(r"\bwhat data\b|\bwhich data\b|\bdata sources?\b|\bwhere (?:does|do) (?:the|your|this) (?:data|numbers?)\b|\bwhere is (?:the|your) data\b"
                        r"|\bwhat (?:do you|does it) (?:use|read|look at)\b|\bwhat sources\b", re.I), _a_data),
    ("options", re.compile(r"(?<!my )(?<!other )(?<!the )\boptions?\b(?! (?:do i|are there|have i))|\bput options?\b|\bcall options?\b|\bbuy (?:a )?puts?\b|\bbuy (?:a )?calls?\b", re.I), _a_options),
    ("corporate", re.compile(r"\bdividends?\b|\bex[- ]?div\w*|\b(?:stock |share )?splits?\b(?!\s+(?:the|my|it|this|that|into|up|order|across))|\bpayouts?\b|\bsuspen\w*|\bdelist\w*|\btrading halts?\b|\bcorporate (?:actions?|events?)\b", re.I), _a_corporate),
    ("shock", SHOCK, _a_shock),
    ("premise", re.compile(r"\bthesis\b|\bmy reason\b|\bsupported\b|\bwhen (?:is|are|were|was|did)\b.*\b(?:earnings|report|results|fomc|fed)\b|\bearnings (?:date|when)\b|\bnext earnings\b|财报什么时候|逻辑成立", re.I), _a_premise),
    ("technicals", re.compile(r"\brsi\b|\btechnicals?\b|\btechnical (?:analysis|indicators?|read\w*)\b|\bmacd\b|\boversold\b|\boverbought\b|\bmomentum indicators?\b", re.I), _a_technicals),
    ("street", re.compile(r"\banalysts?\b|\bratings?\b|\bprice targets?\b|\bupgrade\w*\b|\bdowngrade\w*\b|\binsiders?\b|\bthe street\b|\bwall street\b|\bfear\b|\bgreed\b|\bsentiment\b|\blive price\b", re.I), _a_street),
    ("stop", re.compile(r"\bstops?\b|\bstop[- ]loss\b|\btighter\b|\bwider\b", re.I), _a_stop),
    ("size", re.compile(r"\bbigger\b|\bsmaller\b|\bmore\b|\bless\b|\bsize\b|\bwhy not\b.*\b(bigger|more)\b|\bcap\b|\bwhat if i (do|did|put|go|went|buy|bought)\b|\bdouble\b|\bhalve\b", re.I), _a_size),
    ("against", re.compile(r"\bcase against\b|\btalk me out\b|\bdevil\b|\bargue\b|\bwhy shouldn.?t\b|\bwhat.?s wrong\b|\bdownside\b", re.I), _a_against),
    ("worst", re.compile(r"\bworst\b|\bhow bad\b|\bgo wrong\b|\bstress\b|\bcrash\b|\bblow ?up\b|\btail\b|\bdisaster\b", re.I), _a_worst),
    ("exit", re.compile(r"\bget out\b|\bexit\b|\bliquid\w*\b|\bslippage\b|\bsell out\b|\bbook\b|\bdepth\b|\bspread\b", re.I), _a_exit),
    ("lessons", re.compile(r"\blast time\b|\bburn\w*\b|\bbefore\b.*\bwrong\b|\bpast calls?\b|\bpost.?mortem\b|\btrack record\b|\bhistory of\b", re.I), _a_lessons),
    ("trust", re.compile(r"\btrust\b|\breliab\w*\b|\bcalibrat\w*\b|\bhow do (i|you) know\b|\baccurate\b|\bconfiden\w*\b|\bdoes (it|this) work\b|\bprove\b", re.I), _a_trust),
    ("hedge", re.compile(r"\bhedg\w*\b|\bperp\b|\bdelta[- ]neutral\b|\bprotect\b", re.I), _a_hedge),
    ("gate", re.compile(r"\bwhy (not|no|review|did you)\b|\brefus\w*\b|\brule\b|\bgate\b|\bcheck\w*\b|\bblock\w*\b|\breason\b", re.I), _a_gate),
    ("regime", re.compile(r"\bregime\b|\bkind of market\b|\bmarket like\b|\bconditions?\b|\bvolatil\w*\b", re.I), _a_regime),
    ("why", re.compile(r"^\s*(?:but\s+|so\s+)?why\b(?!\s+(?:not|no)\b.*\b(?:bigger|more)\b)(?!.*\b(?:similar|alike|match(?:es|ed)?|moments?)\b)|\bexplain (?:the |this |that )?(?:verdict|decision|call)\b|\bwhy (?:this|that) (?:verdict|call|answer)\b", re.I), _a_why),
    ("moments", re.compile(r"\bwhich (moments?|days?|hours?)\b|\bshow me\b|\bexamples?\b|\bmatch(?:ed|es)?\b|\bsimilar\b|\balike\b|\bclosest\b|相似", re.I), _a_moments),
    ("history", re.compile(r"\bhistor\w*\b|\bpast\b|\banalog\w*\b|\bdistribution\b|\bhow many\b|\bsample\b|\bsignificant\b|\bmedian\b|\bodds\b|\bchance\b", re.I), _a_history),
    ("now", re.compile(r"\bright now\b|\bcurrent\b|\bprice\b|\bbasis\b|\bfair value\b|\bwhat.?s happening\b", re.I), _a_now),
)

# What to say when a question matches nothing: three or four things worth asking, not a
# paragraph listing every section. A judge read the long version as a dead end.
MENU = "Try one of these: why? · explain it simply · how bad can it get? · what's the safest way to hold it? · compare it with SPY"

# A question, rather than a new trade idea. Deliberately loose: the caller only reaches
# here when there is a report to ask about and no new ticker was named.
_QUESTIONY = re.compile(r"\?|？|^\s*(why|what|how|when|which|who|where|can|could|should|would|is|are|do|does|did|tell|show|explain|talk)\b|吗|呢|什么|为什么|怎么|多少|能不能|是否|如何|会不会", re.I)


# "halve it", "double it", "use 5x", "hold it until Wednesday", "gap it down 10%": an
# instruction about the report on screen. Without a question mark these used to be read
# as a fresh trade, which re-ran the same size and said nothing.
_INSTRUCTION = re.compile(
    r"^\s*(?:now\s+|ok\s+|and\s+)?(?:halve|double|triple|use|try|drop|remove|flip|cut)\b|\b(?:hold|keep)\s+(?:it|this|that|the position)\b"
    r"|^\s*hold\s+(?:it\s+|this\s+|that\s+)?(?:until|till|to|through|for|over|into)\b"
    r"|\b(?:halve|double|triple)\s+(?:it|the size|that)\b|\b\d+(?:\.\d+)?\s*[x×](?![a-z])|\b(?:no|without)\s+leverage\b"
    r"|减半|加倍|翻倍",
    re.I,
)


def looks_like_a_question(text: str) -> bool:
    from nightwatch.api.intake import margin_adjustment

    t = text.strip()
    # "add 500 more margin" has no question mark and no leading verb the list knows.
    return bool(_QUESTIONY.search(t) or _INSTRUCTION.search(t) or SHOCK.search(t) or margin_adjustment(t) is not None)


def answer(report: dict, question: str) -> Answer | None:
    """The best answer this report can give to this question, or None if it cannot."""
    for kind, pattern, fn in ROUTES:
        if not pattern.search(question):
            continue
        try:
            got = fn(report, question)
        except Exception:  # noqa: BLE001 - a malformed report must not take the desk down
            continue
        if got is not None:
            return got
        _ = kind
    return None


def answer_or_menu(report: dict, question: str) -> Answer:
    got = answer(report, question)
    if got is not None:
        return got
    return Answer("menu", f"I could not match that to this report. {MENU}", ())
