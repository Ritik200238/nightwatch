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


def _a_size(r: dict, q: str) -> Answer | None:
    sen = r.get("sensitivity") or {}
    sizes = sen.get("sizes") or []
    requested = _ticket(r).get("notional_quote")
    asked = _money_in(q)

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
    return h.get("p5_adjusted") if h.get("p5_adjusted") is not None else (h.get("cohort") or {}).get("p5")


def _a_worst(r: dict, _q: str) -> Answer | None:
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
        f"{c['n']} distinct past moments looked like this one. The middle outcome over {r.get('primary_horizon')} was {_pct(c.get('median_pct'))}, "
        f"one in twenty was worse than {_pct(_p5(r))}, and {c['win_rate'] * 100:.0f}% ended positive." if c.get("win_rate") is not None else
        f"{c['n']} distinct past moments looked like this one; the middle outcome was {_pct(c.get('median_pct'))}."
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
        bits.append(f"The tails you see are widened by a factor of {adj.get('k_lo', 0):.2f} fitted on {adj.get('n_fit', 0):,} already-scored forecasts, never on this one.")
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
    return Answer(
        "moments",
        f"The {len(rows)} matched moments, worst first: {line(rows[0])}{middle}; best {line(rows[-1])}. "
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
        bits.append(
            f"Insiders made {s.get('insider_sells', 0)} open-market sales ({_dollars(s.get('insider_sold_value'))}) and "
            f"{s.get('insider_buys', 0)} purchases ({_dollars(s.get('insider_bought_value'))}) in the last 90 days."
        )
    elif re.search(r"insider", q, re.I):
        bits.append("No open-market insider trades in the last 90 days.")
    if s.get("mood_score") is not None:
        bits.append(f"Market-wide fear and greed reads {s['mood_score']:.0f} ({s.get('mood_rating') or ''}).")
    bits.append("None of this moved the size - it has not been tested against what the token did overnight.")
    return Answer("street", " ".join(bits), ("Bitget US-stock data",))


ROUTES: tuple[tuple[str, re.Pattern[str], Any], ...] = (
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
    ("moments", re.compile(r"\bwhich (moments?|days?|hours?)\b|\bshow me\b|\bexamples?\b|\bmatched?\b|\bsimilar (moments?|days?)\b", re.I), _a_moments),
    ("history", re.compile(r"\bhistor\w*\b|\bpast\b|\banalog\w*\b|\bdistribution\b|\bhow many\b|\bsample\b|\bsignificant\b|\bmedian\b|\bodds\b|\bchance\b", re.I), _a_history),
    ("now", re.compile(r"\bright now\b|\bcurrent\b|\bprice\b|\bbasis\b|\bfair value\b|\bwhat.?s happening\b", re.I), _a_now),
)

MENU = (
    "I can answer from this report: why the size is what it is, what a different size or stop would do, "
    "what the worst cases are, what it costs to get out, what history says and how significant that is, "
    "whether this setup has burned you before, the case against it, what hedging costs, what kind of market "
    "this is, what analysts and insiders are doing, and how far to trust any of it."
)

# A question, rather than a new trade idea. Deliberately loose: the caller only reaches
# here when there is a report to ask about and no new ticker was named.
_QUESTIONY = re.compile(r"\?|？|^\s*(why|what|how|when|which|who|where|can|could|should|would|is|are|do|does|did|tell|show|explain|talk)\b|吗|呢|什么|为什么|怎么|多少|能不能|是否|如何|会不会", re.I)


def looks_like_a_question(text: str) -> bool:
    return bool(_QUESTIONY.search(text.strip()))


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
    return Answer("menu", f"I could not find that in this report. {MENU}", ())
