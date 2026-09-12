"""Position sizing and the verdict.

Sizing is the intersection of independent caps, each with a name so the trader sees
which one binds:

* ``risk_budget``  – notional whose loss at the stop (or the analog 5th percentile)
  equals the allowed share of equity
* ``concentration`` – max share of equity in one name
* ``regime``       – the regime multiplier applied to the plan size
* ``exit_liquidity`` – largest size the live book absorbs within the cost budget
* ``stress``       – notional at which the worst *severe* preset stays inside the
  max-loss limit

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
    max_stress_loss_pct: float = 5.0
    hedge_cost_ceiling_bps: float = 30.0  # hedge only if it costs less than this
    hedge_benefit_min_pct: float = 1.5  # ... and removes at least this much p5 loss


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
        caps.append(Cap("concentration", inp.equity * policy.max_position_pct_of_equity / 100.0, f"max {policy.max_position_pct_of_equity}% of equity in one name"))
    # Regime multiplier applies to the requested size.
    caps.append(Cap("regime", ticket.notional_quote * inp.risk_multiplier, f"regime size multiplier {inp.risk_multiplier:.2f} on the requested size"))
    # Exit liquidity.
    if inp.max_exit_notional_within_budget is None:
        caps.append(Cap("exit_liquidity", None, "no order book"))
    else:
        caps.append(Cap("exit_liquidity", inp.max_exit_notional_within_budget, f"largest size the live book absorbs within {policy.exit_cost_budget_bps:.0f} bps"))
    # Stress: scale the requested size so the worst severe preset stays inside the limit.
    if inp.worst_severe_stress_pct is None:
        caps.append(Cap("stress", None, "no stress presets available"))
    elif inp.worst_severe_stress_pct >= -policy.max_stress_loss_pct:
        caps.append(Cap("stress", ticket.notional_quote, f"worst severe preset {inp.worst_severe_stress_pct:+.1f}% is within the {policy.max_stress_loss_pct}% limit"))
    else:
        # Loss scales ~linearly with notional for price moves; exit cost grows faster, so this is a mild overestimate.
        scale = policy.max_stress_loss_pct / abs(inp.worst_severe_stress_pct)
        caps.append(Cap("stress", ticket.notional_quote * scale, f"scaled so the worst severe preset ({inp.worst_severe_stress_pct:+.1f}%) meets the {policy.max_stress_loss_pct}% limit"))
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
            rationale = (f"hedging {hedge_ratio:.0%} costs ~{inp.hedge_cost_bps_of_position:.0f} bps and cuts the 5th-percentile loss from "
                         f"{inp.analog_p5_loss_pct:+.1f}% to {inp.hedge_residual_p5_loss_pct:+.1f}% (basis risk only)")
    return SizingResult(recommended, binding.name, caps, hedge_ratio, rationale)


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
    rec = sizing.recommended_notional
    if rec <= 0:
        reasons.append(f"no size satisfies the {sizing.binding_cap} cap")
        return VerdictResult(Verdict.NO_GO, ticket.notional_quote, 0.0, None, reasons, sizing.caps)
    if rec >= ticket.notional_quote * (1.0 - tolerance):
        reasons.append("requested size is within every cap")
        return VerdictResult(Verdict.GO, ticket.notional_quote, ticket.notional_quote, ticket.hedge_ratio, reasons, sizing.caps)
    reasons.append(f"{sizing.binding_cap} cap binds at {rec:,.0f} (requested {ticket.notional_quote:,.0f})")
    if sizing.hedge_ratio_suggested is not None and sizing.binding_cap in ("risk_budget", "stress", "regime"):
        reasons.append(sizing.hedge_rationale)
        return VerdictResult(Verdict.HEDGE, ticket.notional_quote, ticket.notional_quote, sizing.hedge_ratio_suggested, reasons, sizing.caps)
    return VerdictResult(Verdict.REDUCE_TO, ticket.notional_quote, rec, None, reasons, sizing.caps)
