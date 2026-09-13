"""The strongest case against whatever the desk just said.

A verdict that only shows its supporting evidence is a sales pitch. This assembles the
opposite case from the same report: if the answer was go, the facts that most argue
against going; if the answer was no, the facts that argue for taking it smaller. Nothing
is invented and nothing is weighted by opinion — each point quotes a number the report
already computed, and points are ranked by how much money they represent, because that is
the only ordering a trader can act on.

It needs no language model. The narration layer, when a key exists, reads these points;
without one they stand on their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Counterpoint:
    kind: str  # "against" | "for"
    text: str
    magnitude_quote: float | None  # what it is worth in money, for ranking
    source: str  # which part of the report it came from


@dataclass(frozen=True)
class SecondOpinion:
    verdict: str
    against: list[Counterpoint] = field(default_factory=list)
    supporting: list[Counterpoint] = field(default_factory=list)
    summary: str = ""


def _q(x: float | None) -> str:
    return "—" if x is None else f"{x:,.0f}"


def build(report: Any) -> SecondOpinion:  # noqa: C901 - a long list of independent checks
    """``report`` is an AnalysisReport. Everything is read, nothing is recomputed."""
    verdict = report.verdict.verdict.value
    size = report.verdict.recommended_notional or report.ticket.notional_quote
    against: list[Counterpoint] = []
    supporting: list[Counterpoint] = []

    # What the worst preset would cost at the size being recommended.
    worst = None
    for scenario, impact in zip(report.stress.presets, report.stress.impacts, strict=True):
        if impact.total_pct_of_notional is None:
            continue
        if worst is None or impact.total_pct_of_notional < worst[1].total_pct_of_notional:
            worst = (scenario, impact)
    if worst is not None:
        pct = worst[1].total_pct_of_notional
        money = abs(size * pct / 100.0)
        against.append(Counterpoint("against", f"{worst[0].name} would cost {pct:+.1f}% of the position, about {_q(money)} USDT at this size. {worst[0].probability_note}.", money, "stress presets"))

    primary = report.analog.horizons.get(report.primary_horizon) if report.analog else None
    if primary and not primary.cohort.insufficient:
        c = primary.cohort
        p5 = primary.p5_adjusted if primary.p5_adjusted is not None else c.p5
        if p5 is not None:
            # The tail is one idea, so it is one point: where it starts and how far past it went.
            tail = f"One time in twenty, moments like this lost {abs(p5):.1f}% or more over the horizon, about {_q(abs(size * p5 / 100.0))} USDT."
            if c.es5_pct is not None and c.es5_n:
                tail += f" When it did go past that, the average was {c.es5_pct:+.1f}%, on {c.es5_n} episode{'s' if c.es5_n != 1 else ''}."
            against.append(Counterpoint("against", tail, abs(size * (c.es5_pct if c.es5_pct is not None else p5) / 100.0), "analog cohort"))
        if c.win_rate is not None and c.win_rate < 0.5:
            against.append(Counterpoint("against", f"Only {c.win_rate:.0%} of those moments ended positive, on {c.n} episodes.", None, "analog cohort"))
        elif c.win_rate is not None:
            supporting.append(Counterpoint("for", f"{c.win_rate:.0%} of those moments ended positive, on {c.n} episodes.", None, "analog cohort"))
        base = primary.baseline
        if base and base.permutation_p_value is not None and base.permutation_p_value > 0.2:
            against.append(Counterpoint("against", f"The resemblance may be doing nothing: against random hours of the same kind the difference in mean outcome is {base.mean_diff_pct:+.2f}% with p = {base.permutation_p_value:.2f}.", None, "baseline test"))

    ex = report.execution
    if ex.exit_quote and ex.exit_quote.total_cost_bps is not None:
        cost = size * ex.exit_quote.total_cost_bps / 1e4
        against.append(Counterpoint("against", f"Getting out costs {ex.exit_quote.total_cost_bps:.0f} bps on the live book, about {_q(cost)} USDT, before any adverse move.", cost, "order book"))
    lh = getattr(ex, "liquidity_history", None)
    if lh:
        thin = [b for b in lh.buckets if not b.thin and (b.share_below_reference or 0) > 0.2]
        if thin:
            b = max(thin, key=lambda x: x.share_below_reference or 0)
            against.append(Counterpoint("against", f"In the recorded archive the book could not absorb this size within budget {b.share_below_reference:.0%} of the time during {b.bucket.replace('_', ' ')}.", None, "book archive"))

    mc = report.stress.monte_carlo
    if mc is not None:
        against.append(Counterpoint("against", f"The simulation puts the chance of losing more than 5% at {mc.prob_loss_gt.get(5.0, 0):.0%}, with an expected shortfall of {mc.expected_shortfall_5_pct:+.1f}% in the worst twentieth.", abs(size * mc.expected_shortfall_5_pct / 100.0), "Monte Carlo"))

    port = getattr(report, "portfolio", None)
    if port and port.mean_correlation_to_book is not None and port.mean_correlation_to_book > 0.5:
        against.append(Counterpoint("against", f"It moves with what you already hold (mean correlation {port.mean_correlation_to_book:.2f}), so it adds size rather than spreading risk.", None, "portfolio"))

    rm = getattr(report, "regimes", None)
    if rm and rm.current is not None:
        cur = rm.regime(rm.current)
        calm = rm.regimes[0] if rm.regimes else None
        if cur and calm and cur.next_ret_p5_pct is not None and calm.next_ret_p5_pct is not None and cur.id != calm.id:
            worse = cur.next_ret_p5_pct - calm.next_ret_p5_pct
            if worse < -0.25:
                against.append(Counterpoint("against", f"This is not the calm state: its 5th percentile over the horizon is {abs(worse):.1f} points worse than the calmest one.", abs(size * worse / 100.0), "regime map"))

    breached = [x for x in (report.lessons or []) if x.get("classification") == "worse_than_stress"]
    if breached:
        against.append(Counterpoint("against", f"{len(breached)} of the recalled past calls in conditions like these finished below the level they were sized against.", None, "post-mortems"))

    # The case for taking it, which matters when the answer was no.
    caps = sorted((c for c in report.sizing.caps if c.notional is not None), key=lambda c: c.notional)
    if caps and report.ticket.notional_quote > caps[0].notional:
        supporting.append(Counterpoint("for", f"Only the {caps[0].name.replace('_', ' ')} cap stands in the way; at {_q(caps[0].notional)} USDT the same trade passes every check.", caps[0].notional, "sizing caps"))
    if report.sensitivity and report.sensitivity.max_go_notional:
        supporting.append(Counterpoint("for", f"Up to {_q(report.sensitivity.max_go_notional)} USDT this is a straight go.", report.sensitivity.max_go_notional, "size sweep"))
    if ex.hedge_quote and ex.hedge_quote.total_cost_bps_of_position < 30:
        supporting.append(Counterpoint("for", f"A full perp hedge costs {ex.hedge_quote.total_cost_bps_of_position:.0f} bps, which buys out most of the price risk if you want the position anyway.", None, "hedge quote"))

    against.sort(key=lambda c: (c.magnitude_quote is None, -(c.magnitude_quote or 0)))
    supporting.sort(key=lambda c: (c.magnitude_quote is None, -(c.magnitude_quote or 0)))

    def diversify(points: list[Counterpoint], limit: int) -> list[Counterpoint]:
        """Biggest loss first, but one point from every source before any source repeats.

        Ranking purely by money buries the warnings that carry no number, and "this is
        correlated with everything you hold" is not less important for being unpriced.
        """
        groups: dict[str, list[Counterpoint]] = {}
        for c in points:
            groups.setdefault(c.source, []).append(c)
        order = sorted(groups, key=lambda k: -(groups[k][0].magnitude_quote or 0))
        out: list[Counterpoint] = []
        while len(out) < limit and any(groups[k] for k in order):
            for k in order:
                if groups[k]:
                    out.append(groups[k].pop(0))
                    if len(out) >= limit:
                        break
        return out

    against = diversify(against, 8)
    supporting = diversify(supporting, 3)

    if verdict in ("GO", "REDUCE_TO", "HEDGE"):
        head = f"The desk says {verdict.replace('_', ' ').lower()}. The strongest case against it:"
    elif verdict == "NO_GO":
        head = "The desk says no. If you disagree, this is what would have to be true:"
    else:
        head = "The desk cannot decide yet. What is already known:"
    return SecondOpinion(verdict=verdict, against=against, supporting=supporting, summary=head)
