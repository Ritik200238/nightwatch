"""Position sizing and the verdict.

Sizing is the intersection of independent caps, each with a name so the trader sees
which one binds:

* ``risk_budget``  – notional whose loss at the stop (or the analog 5th percentile)
  equals the allowed share of equity
* ``concentration`` – max share of equity in one name
* ``regime``       – the regime multiplier applied to the plan size
* ``exit_liquidity`` – largest size the live book absorbs within the cost budget
* ``stress``       – the largest notional at which the worst *severe* preset's loss,
  in quote terms, stays inside the allowed share of equity
* ``book_tail``    – with holdings given: the largest notional at which the whole book's
  one-in-twenty loss stays inside the allowed share of equity (see ``DecisionContext``)

The verdict then compares the requested size with the recommended one and folds in
the analog evidence and hedge economics:

* ``GO``         – requested size within every cap and gate passed
* ``REDUCE_TO``  – gate passed but a cap binds below the request
* ``HEDGE``      – downside is dominated by the underlying move and a perp hedge is
  cheap relative to it: recommend hedging a share instead of cutting
* ``NO_GO``      – gate failed, or no size satisfies the caps
* ``REVIEW``     – gate needs inputs before anything can be recommended
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from nightwatch.decision.gate import GateDecision, GateReport
from nightwatch.decision.ticket import TradeTicket


class Verdict(str, Enum):
    GO = "GO"
    REDUCE_TO = "REDUCE_TO"
    HEDGE = "HEDGE"
    NO_GO = "NO_GO"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class SizingPolicy:
    risk_pct_of_equity: float = 1.0
    max_position_pct_of_equity: float = 25.0
    exit_cost_budget_bps: float = 25.0
    max_stress_loss_pct: float = 5.0  # reverse stress: the move that loses this % of the position
    max_stress_loss_pct_of_equity: float = 5.0  # stress cap: worst severe preset may cost this much of equity
    hedge_cost_ceiling_bps: float = 30.0  # hedge only if it costs less than this
    hedge_benefit_min_pct: float = 1.5  # ... and removes at least this much p5 loss
    max_book_tail_pct_of_equity: float = 4.0  # the whole book's one-in-twenty loss may cost this much of equity


@dataclass(frozen=True)
class Cap:
    name: str
    notional: float | None  # None = not computable
    detail: str


@dataclass(frozen=True)
class SizingInputs:
    entry_price: float
    equity: float | None
    stop_distance_pct: float | None
    analog_p5_loss_pct: float | None
    risk_multiplier: float
    max_exit_notional_within_budget: float | None
    worst_severe_stress_pct: float | None  # e.g. -6.1 (% of notional) at the requested size
    hedge_cost_bps_of_position: float | None
    hedge_residual_p5_loss_pct: float | None  # p5 loss after hedging (basis only)
    stress_cap_notional: float | None = None  # solved by the caller, which can re-price the scenarios
    # Holdings: the book's tail is measured on history the caller holds, so it solves this
    # too. None = no book, no equity, or no history to measure it on; the cap is then absent.
    book_tail_cap_notional: float | None = None
    book_tail_detail: str = ""
    same_name_exposure_quote: float = 0.0  # already held in this name, running the same way


@dataclass(frozen=True)
class SizingResult:
    recommended_notional: float | None
    binding_cap: str | None
    caps: list[Cap] = field(default_factory=list)
    hedge_ratio_suggested: float | None = None
    hedge_rationale: str = ""


@dataclass(frozen=True)
class VerdictResult:
    verdict: Verdict
    requested_notional: float
    recommended_notional: float | None
    hedge_ratio: float | None
    reasons: list[str]
    caps: list[Cap]


def compute_caps(ticket: TradeTicket, inp: SizingInputs, policy: SizingPolicy = SizingPolicy()) -> list[Cap]:
    caps: list[Cap] = []
    # Risk budget.
    loss_pct = inp.stop_distance_pct if inp.stop_distance_pct is not None else (abs(min(inp.analog_p5_loss_pct, 0.0)) if inp.analog_p5_loss_pct is not None else None)
    basis = "stop distance" if inp.stop_distance_pct is not None else "analog p5 loss"
    if inp.equity is None or loss_pct is None or loss_pct <= 0:
        caps.append(Cap("risk_budget", None, "needs equity and a stop or analog distribution"))
    else:
        n = inp.equity * policy.risk_pct_of_equity / 100.0 / (loss_pct / 100.0)
        caps.append(Cap("risk_budget", n, f"{policy.risk_pct_of_equity}% of equity at risk over a {loss_pct:.2f}% {basis}"))
    # Concentration.
    if inp.equity is None:
        caps.append(Cap("concentration", None, "needs equity"))
    else:
        room = inp.equity * policy.max_position_pct_of_equity / 100.0
        if inp.same_name_exposure_quote > 0:
            # What is already held in the name counts: two 15% positions in one stock are a 30% position.
            caps.append(Cap("concentration", max(0.0, room - inp.same_name_exposure_quote),
                            f"max {policy.max_position_pct_of_equity}% of equity in one name, and {inp.same_name_exposure_quote:,.0f} of it is already held"))
        else:
            caps.append(Cap("concentration", room, f"max {policy.max_position_pct_of_equity}% of equity in one name"))
    # Regime multiplier applies to the requested size.
    caps.append(Cap("regime", ticket.notional_quote * inp.risk_multiplier, f"regime size multiplier {inp.risk_multiplier:.2f} on the requested size"))
    # Exit liquidity.
    if inp.max_exit_notional_within_budget is None:
        caps.append(Cap("exit_liquidity", None, "no order book"))
    else:
        caps.append(Cap("exit_liquidity", inp.max_exit_notional_within_budget, f"largest size the live book absorbs within {policy.exit_cost_budget_bps:.0f} bps"))
    # Stress: the worst severe preset must not cost more than a set share of equity.
    # A limit expressed as a share of the *position* cannot be a size cap: the loss and
    # the position shrink together, so the ratio never improves. Equity is the anchor.
    limit = policy.max_stress_loss_pct_of_equity
    worst = inp.worst_severe_stress_pct
    if inp.stress_cap_notional is not None:
        detail = f"worst severe preset {worst:+.1f}% of notional; the largest size whose loss stays inside {limit}% of equity" if worst is not None else f"largest size whose worst severe loss stays inside {limit}% of equity"
        caps.append(Cap("stress", max(0.0, inp.stress_cap_notional), detail))
    elif worst is None:
        caps.append(Cap("stress", None, "no stress presets available"))
    elif inp.equity is None:
        caps.append(Cap("stress", None, "needs equity to bound the stress loss"))
    else:
        # First-order fallback: the loss per unit of notional is taken as fixed. Exit
        # cost grows faster than size, so this overestimates the safe size slightly.
        cap = inp.equity * limit / 100.0 / (abs(worst) / 100.0)
        caps.append(Cap("stress", cap, f"worst severe preset {worst:+.1f}% of notional; approximately the largest size within {limit}% of equity"))
    if inp.book_tail_cap_notional is not None:
        caps.append(Cap("book_tail", max(0.0, inp.book_tail_cap_notional), inp.book_tail_detail or f"largest size whose book-wide one-in-twenty loss stays inside {policy.max_book_tail_pct_of_equity}% of equity"))
    return caps


def recommend_size(ticket: TradeTicket, inp: SizingInputs, policy: SizingPolicy = SizingPolicy()) -> SizingResult:
    caps = compute_caps(ticket, inp, policy)
    computable = [c for c in caps if c.notional is not None]
    if not computable:
        return SizingResult(None, None, caps)
    binding = min(computable, key=lambda c: c.notional)
    recommended = max(0.0, float(binding.notional))

    hedge_ratio = None
    rationale = ""
    if (
        inp.hedge_cost_bps_of_position is not None
        and inp.analog_p5_loss_pct is not None
        and inp.hedge_residual_p5_loss_pct is not None
        and inp.hedge_cost_bps_of_position <= policy.hedge_cost_ceiling_bps
        and (abs(inp.analog_p5_loss_pct) - abs(inp.hedge_residual_p5_loss_pct)) >= policy.hedge_benefit_min_pct
    ):
        # Hedge the share needed to bring the request inside the binding cap, capped at 100%.
        if recommended < ticket.notional_quote:
            hedge_ratio = min(1.0, 1.0 - recommended / ticket.notional_quote)
            # At ratio h the loss is the blend of the unhedged and fully-hedged distributions,
            # not the fully-hedged residual on its own - quoting the residual at a partial ratio
            # overstates how much of the loss the suggested hedge actually removes.
            at_ratio_p5 = (1.0 - hedge_ratio) * inp.analog_p5_loss_pct + hedge_ratio * inp.hedge_residual_p5_loss_pct
            full_hedge_note = " (fully hedged)" if hedge_ratio >= 1.0 - 1e-9 else ""
            rationale = (f"hedging {hedge_ratio:.0%}{full_hedge_note} costs ~{inp.hedge_cost_bps_of_position:.0f} bps and cuts the 5th-percentile loss from "
                         f"{inp.analog_p5_loss_pct:+.1f}% to about {at_ratio_p5:+.1f}% at that ratio (basis risk only)")
    return SizingResult(recommended, binding.name, caps, hedge_ratio, rationale)


_CAP_PLAIN = {
    "risk_budget": "the loss if the stop is hit would exceed the share of equity you allow at risk",
    "concentration": "more than that would put too much of your equity in one name",
    "regime": "the current market regime calls for a smaller position than requested",
    "exit_liquidity": "the live order book can absorb only that much within the exit-cost budget",
    "stress": "the worst severe stress scenario would cost more than the allowed share of equity at a larger size",
    "book_tail": "a larger size would push the whole book's one-in-twenty loss past the allowed share of equity",
}


def plain_cap_reason(sizing: SizingResult, rec: float) -> str:
    """Which cap binds and why, in words a trader reads without the cap's code name."""
    name = sizing.binding_cap or ""
    cap = next((c for c in sizing.caps if c.name == name), None)
    why = _CAP_PLAIN.get(name, f"the {name.replace('_', ' ')} limit binds")
    if name == "exit_liquidity" and cap is not None:
        m = re.search(r"within (\d+) bps", cap.detail)
        if m:
            why = f"the live order book can absorb only that much within the {m.group(1)} bps exit-cost budget"
    return f"Size held at {rec:,.0f} USDT: {why}"


def decide(ticket: TradeTicket, gate: GateReport, sizing: SizingResult, *, tolerance: float = 0.05) -> VerdictResult:
    reasons: list[str] = []
    if gate.decision == GateDecision.NO_GO:
        reasons.extend(gate.reasons)
        return VerdictResult(Verdict.NO_GO, ticket.notional_quote, sizing.recommended_notional, None, reasons, sizing.caps)
    if gate.decision == GateDecision.REVIEW_REQUIRED:
        reasons.extend(gate.reasons)
        return VerdictResult(Verdict.REVIEW, ticket.notional_quote, sizing.recommended_notional, None, reasons, sizing.caps)
    if sizing.recommended_notional is None:
        reasons.append("no cap could be computed; provide equity and a stop")
        return VerdictResult(Verdict.REVIEW, ticket.notional_quote, None, None, reasons, sizing.caps)
    # Passed, but with things the trader should read before acting.
    reasons.extend(gate.advisories)
    rec = sizing.recommended_notional
    if rec <= 0:
        reasons.append(f"No size is allowed: {_CAP_PLAIN.get(sizing.binding_cap or '', 'a limit binds')}")
        return VerdictResult(Verdict.NO_GO, ticket.notional_quote, 0.0, None, reasons, sizing.caps)
    if rec >= ticket.notional_quote * (1.0 - tolerance):
        reasons.append("requested size is within every cap")
        return VerdictResult(Verdict.GO, ticket.notional_quote, ticket.notional_quote, ticket.hedge_ratio, reasons, sizing.caps)
    reasons.append(f"{plain_cap_reason(sizing, rec)} (requested {ticket.notional_quote:,.0f}).")
    if sizing.hedge_ratio_suggested is not None and sizing.binding_cap in ("risk_budget", "stress", "regime"):
        reasons.append(sizing.hedge_rationale)
        return VerdictResult(Verdict.HEDGE, ticket.notional_quote, ticket.notional_quote, sizing.hedge_ratio_suggested, reasons, sizing.caps)
    return VerdictResult(Verdict.REDUCE_TO, ticket.notional_quote, rec, None, reasons, sizing.caps)
