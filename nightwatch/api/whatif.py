"""Answering a what-if by running it, rather than by describing it.

The follow-up layer answers from the report already on the screen. Some questions are
not in it. "What if I held it twelve hours instead", "was it worse on earnings nights",
"what about NVDA" - none of those are a rearrangement of numbers that have been
computed. They are a different report, and the only honest way to produce one is to run
the desk again.

So the model's job here is the same as it is for lenses: turn a sentence into fields
from a fixed schema, and nothing else. It says *what changed* - the token, the side, how
long the position is held, which past moments count as comparable - and the engine does
every computation that follows. The comparison a trader reads is assembled from the two
reports' own fields, so there is no step at which a number could be invented.

Size and stop are deliberately not changeable here. The sensitivity sweep already ran
the whole gate across a grid of both, so those questions are answered instantly from the
report on the screen; re-running for them would be slower and no more correct.

The interesting part is not that the distribution moves. It is that the *verdict* moves
with it. Asking "only earnings nights" on TSLA takes the one-in-twenty loss from -3.3%
to -10.6%, and a desk that sizes off the loss tail cuts the position accordingly. That
is the whole product in one exchange.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime

from nightwatch.analog import lens as lens_mod
from nightwatch.api.followup import Answer, _p5, _pct, _primary, _usd
from nightwatch.decision.ticket import HorizonKind, Side, TradeTicket

# Fields a what-if may touch. Anything outside this set is not a what-if the desk knows
# how to run, which is a better failure than running something adjacent to the question.
FIELDS = ("ticker", "side", "horizon_kind", "horizon_hours", "lenses")

# A question worth spending a model call and a re-run on. Deliberately loose: a false
# positive costs one parse that comes back empty and falls through to the rules layer,
# while a false negative silently answers a counterfactual with the original report.
_MARKERS = (
    r"what if", r"what about", r"how about", r"instead", r"rather than", r"compared? (?:to|with)",
    r"\bonly\b", r"\bjust\b", r"\bversus\b", r"\bvs\.?\b", r"would it", r"\bif i (?:held|hold|went|go|was|were|did)\b",
)
_WHATIF = re.compile("|".join(_MARKERS), re.I)


def looks_like_a_what_if(question: str, *, tickers: tuple[str, ...] = (), current: str = "") -> bool:
    """Whether this question is asking about a different report from the one on screen.

    Three ways in: an explicit counterfactual marker, a phrase that names one of the
    search conditions, or a token that is not the one the report is about. The lens
    phrasings come from the lens definitions themselves, so a condition added there is
    routable here without anything being kept in step by hand.
    """
    q = question.lower()
    if _WHATIF.search(q):
        return True
    for x in lens_mod.LENSES:
        if any(phrase in q for phrase in x.says):
            return True
    return any(t.lower() in re.findall(r"[a-z]+", q) for t in tickers if t.upper() != current.upper())


@dataclass(frozen=True)
class Change:
    """What the trader asked to vary, in the desk's own vocabulary.

    Every field is optional and an unset field means "as it was". A change that sets
    nothing is not a refusal to answer - it is the model saying this question is not a
    what-if, which sends it back to the layer that answers from the report.
    """

    # A message that plainly names another token is taken as a fresh trade idea before it
    # ever reaches here, which is the better reading of "what about 20k of NVDA". This
    # field catches the rest - a token mentioned in a way the intake parser does not spot.
    ticker: str | None = None
    side: str | None = None
    horizon_kind: str | None = None
    horizon_hours: float | None = None
    lenses: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not any((self.ticker, self.side, self.horizon_kind, self.horizon_hours, self.lenses))

    def describe(self) -> str:
        bits = []
        if self.ticker:
            bits.append(self.ticker.upper())
        if self.side:
            bits.append("short instead" if self.side == "short" else "long instead")
        if self.horizon_hours:
            bits.append(f"held {self.horizon_hours:g}h")
        elif self.horizon_kind == "window_end":
            bits.append("held to the end of this closed window")
        elif self.horizon_kind == "next_open":
            bits.append("held to the next US open")
        if self.lenses:
            bits.append(lens_mod.describe(lens_mod.resolve(list(self.lenses))))
        return ", ".join(bits)

    def apply_to(self, ticket: TradeTicket) -> TradeTicket:
        """The same ticket with the asked-for fields replaced, and nothing else touched."""
        kind = HorizonKind(self.horizon_kind) if self.horizon_kind else ticket.horizon_kind
        hours = self.horizon_hours if self.horizon_hours else ticket.horizon_hours
        if self.horizon_hours:
            kind = HorizonKind.HOURS
        return replace(
            ticket,
            ticker=(self.ticker or ticket.ticker).upper(),
            side=Side(self.side) if self.side else ticket.side,
            horizon_kind=kind,
            horizon_hours=hours,
            # Names the model invented are dropped rather than guessed at, exactly as
            # they are on the way in from a ticket.
            lenses=tuple(x.name for x in lens_mod.resolve(list(self.lenses))) if self.lenses else ticket.lenses,
        )


def ticket_from(report: dict) -> TradeTicket | None:
    """The ticket a stored report was produced from, rebuilt well enough to re-run.

    Only the fields that drive the analysis; the prose fields come along so the written
    plan rule does not fail a ticket the trader already wrote a plan for.
    """
    t = report.get("ticket") or {}
    if not t.get("ticker"):
        return None
    try:
        return TradeTicket(
            ticker=str(t["ticker"]).upper(),
            side=Side(t.get("side") or "long"),
            notional_quote=float(t.get("notional_quote") or 0.0),
            account_equity_quote=t.get("account_equity_quote"),
            horizon_kind=HorizonKind(t.get("horizon_kind") or "next_open"),
            horizon_hours=t.get("horizon_hours"),
            stop_price=t.get("stop_price"),
            target_price=t.get("target_price"),
            thesis=t.get("thesis") or "",
            invalidation=t.get("invalidation") or "",
            hedge_ratio=t.get("hedge_ratio"),
            lenses=tuple(t.get("lenses") or ()),
        )
    except (TypeError, ValueError):
        return None


def as_of_of(report: dict) -> datetime | None:
    """The moment the report was taken, so the re-run answers the same night.

    A what-if run against the current hour would be comparing two different moments as
    well as two different questions, and the difference between them could not be
    attributed to the change the trader asked about.
    """
    raw = report.get("as_of")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _cohort(r: dict) -> dict:
    h = _primary(r) or {}
    return h.get("cohort") or {}


def _n(r: dict) -> int | None:
    c = _cohort(r)
    return int(c["n"]) if c.get("n") else None


def _lens_note(after: dict) -> str:
    """The desk's own words when a narrowed search could not be honoured."""
    lens = (after.get("analog") or {}).get("lens") or {}
    if lens.get("names") and not lens.get("applied"):
        return lens.get("refused") or ""
    return ""


def compare(before: dict, after: dict, change: Change) -> Answer:
    """What changed between two reports of the same night, in the order a trader reads.

    Every number is copied from one of the two reports. The only judgement this function
    makes is which of them are worth printing, and that judgement is the same every time.
    """
    what = change.describe() or "that change"
    refused = _lens_note(after)
    if refused:
        return Answer("what_if", f"I cannot answer that one honestly: {refused}.", ("analog cohort",))

    bits = [f"Re-run with {what}, against the same moment:"]

    nb, na = _n(before), _n(after)
    scope = (after.get("analog") or {}).get("scope")
    if na is None:
        reason = ((after.get("analog") or {}).get("result") or {}).get("reason", "too few matches")
        bits.append(f"there were not enough distinct past moments to answer ({reason}).")
        return Answer("what_if", " ".join(bits), ("analog cohort",))
    if nb is not None and nb != na:
        bits.append(f"the cohort is {na} past moments instead of {nb}")
    else:
        bits.append(f"the cohort is {na} past moments")
    if scope == "pooled" and (before.get("analog") or {}).get("scope") != "pooled":
        bits[-1] += ", searched across the pooled history because one token's own past does not hold enough of them"
    bits[-1] += "."

    cb, ca = _cohort(before), _cohort(after)
    hb, ha = before.get("primary_horizon"), after.get("primary_horizon")
    horizon = f" over {ha}" if ha and ha != hb else ""
    same = cb.get("median_pct") == ca.get("median_pct") and _p5(before) == _p5(after)
    if same:
        # A lens that filtered nothing, or a change the distribution did not feel. Saying
        # "moves from -3.3% to -3.3%" is true and reads like a mistake.
        bits.append(f"The middle outcome{horizon} and the one-in-twenty loss are unchanged, at {_pct(ca.get('median_pct'))} and {_pct(_p5(after))}.")
    else:
        bits.append(
            f"The middle outcome{horizon} moves from {_pct(cb.get('median_pct'))} to {_pct(ca.get('median_pct'))}, "
            f"and the one-in-twenty loss from {_pct(_p5(before))} to {_pct(_p5(after))}."
        )

    vb, va = (before.get("verdict") or {}), (after.get("verdict") or {})
    if va.get("verdict"):
        cap = (after.get("sizing") or {}).get("binding_cap")
        held = f", held by the {cap.replace('_', ' ')} cap" if cap else ""
        if vb.get("verdict") and (vb.get("verdict") != va.get("verdict") or abs((vb.get("recommended_notional") or 0) - (va.get("recommended_notional") or 0)) > 1):
            bits.append(
                f"The verdict moves from {vb['verdict']} at {_usd(vb.get('recommended_notional'))} "
                f"to {va['verdict']} at {_usd(va.get('recommended_notional'))}{held}."
            )
        else:
            bits.append(f"The verdict is unchanged: {va['verdict']} at {_usd(va.get('recommended_notional'))}{held}.")

    return Answer("what_if", " ".join(bits), ("analog cohort", "gate and sizing", "re-run"))
