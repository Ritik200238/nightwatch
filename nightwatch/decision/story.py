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
from dataclasses import asdict, dataclass
from typing import Any


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
    return f"{hours / 24:.0f} days" if hours >= 48 else f"{hours:.0f} hours"


# ------------------------------------------------------------------ assumptions


def assumptions(r: Any) -> list[Assumption]:  # noqa: ANN401 - an AnalysisReport
    t = r.ticket
    out: list[Assumption] = []
    label = (t.extra or {}).get("horizon_label") if isinstance(t.extra, dict) else None
    out.append(Assumption("hold", f"Held for {r.horizon_h:.0f} hours" + (f" ({label})" if label else ", to the next US regular open" if t.horizon_kind.value == "next_open" else "") + ", then closed."))
    entry = t.entry_price or r.snapshot.prices.get("spot_close")
    if entry:
        out.append(Assumption("entry", f"Entered at the token's last price, {entry:,.2f}, as of {r.snapshot.bar_ts:%d %b %H:%M} UTC."))
    lev = getattr(r, "leverage", None)
    if lev:
        out.append(Assumption("leverage", f"{lev['leverage']:g}x on the Bitget perpetual, isolated margin, maintenance margin {lev['mmr']:.2%}"
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
        out.append(Assumption("events", f"No earnings inside the hold (next in {_days(hte)})."))
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
        out.append(FailureMode(key, title, trig, how, i.total_pnl_quote, i.total_pct_of_notional, s.probability_note, "stress presets", _SHORT[mech]))

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
        out.append(FailureMode(
            "replay", f"A repeat of the {crisis}",
            f"The market breaks the way it did in the {crisis}",
            "the stock moves as it did on that day, and the token follows it at the next open",
            i.total_pnl_quote, i.total_pct_of_notional,
            f"{s.probability_note} - a named crisis, not a frequency", "crash replays",
            f"the {crisis} replayed on this position",
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
            ))

    lev = getattr(r, "leverage", None)
    if lev and lev.get("liquidation_distance_pct") is not None:
        seen = []
        if lev.get("analog_of"):
            seen.append(f"{lev['analog_hits']} of {lev['analog_of']} past moments reached it")
        if lev.get("mc_share") is not None:
            seen.append(f"{lev['mc_share']:.0%} of simulated paths do")
        out.append(FailureMode(
            "liquidation", "Liquidated",
            f"A move of {lev['liquidation_distance_pct']:.1f}% against you at any point in the hold",
            "the exchange closes the position when the margin left falls to the maintenance requirement; the margin is gone and the move cannot be ridden back",
            -float(lev["margin_quote"]), -100.0 / float(lev["leverage"]),
            "; ".join(seen) or "not measured", "Bitget margin tiers + analogs + Monte Carlo",
            "the exchange closes the position and the margin is gone",
        ))

    # Nothing dramatic: the ordinary way a trade loses.
    h = r.analog.horizons.get(r.primary_horizon) if r.analog else None
    c = h.cohort if h is not None else None
    if c is not None and c.n and c.win_rate is not None and c.median_pct is not None and c.win_rate < 0.5:
        out.append(FailureMode(
            "drift", "A quiet drift the wrong way",
            "No event at all",
            "the price simply ends lower, as most moments like this one did",
            c.median_pct / 100.0 * t.notional_quote, c.median_pct,
            f"{1 - c.win_rate:.0%} of {c.n} past moments like this ended down", "analog cohort",
            "no event; the price just ends lower",
        ))

    return sorted(out, key=lambda m: m.loss_quote if m.loss_quote is not None else 0.0)


# ------------------------------------------------------------------- premise


_EARN = re.compile(r"earning|post[-\s]?earn|guidance|report(?:s|ed)?\s+(?:q\d|results)|财报|业绩", re.I)
_POST = re.compile(r"post[-\s]?earn|after\s+(?:the\s+)?(?:earnings|report|results)|drift|财报后", re.I)
_PRE = re.compile(r"(?:into|ahead\s+of|before|pre[-\s]?)\s*(?:the\s+)?(?:earnings|report|results)|run[-\s]?up|财报前", re.I)
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
            out.append(f"Your reason leans on a recent earnings report, but the last one was {_days(since)} ago" + (f" and the next is {_days(until)} away" if until is not None else "") + ".")
        elif _PRE.search(thesis) and (until is None or until > 14 * 24):
            out.append(f"Your reason leans on earnings coming up, but the next report is {_days(until)} away, well past this hold.")
        elif not _POST.search(thesis) and not _PRE.search(thesis) and (since is None or since > 7 * 24) and (until is None or until > r.horizon_h + 24):
            out.append(f"Your reason mentions earnings, but none fall near this hold (last {_days(since)} ago, next in {_days(until)}).")
    fomc = f.get("hours_to_fomc")
    if _FED.search(thesis) and fomc is not None and fomc > max(r.horizon_h + 24, 7 * 24):
        out.append(f"Your reason mentions the Fed, but the next FOMC decision is {_days(fomc)} away, after this hold ends.")
    return out
