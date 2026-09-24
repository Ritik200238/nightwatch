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
_MARKERS_ZH = ("如果", "要是", "假如", "换成", "改成", "只看", "只比较", "呢")
_WHATIF = re.compile("|".join(_MARKERS + _MARKERS_ZH), re.I)


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
        elif self.horizon_kind == "through_weekend":
            bits.append("held through the weekend")
        if self.lenses:
            bits.append(lens_mod.describe(lens_mod.resolve(list(self.lenses))))
        return ", ".join(bits)

    def apply_to(self, ticket: TradeTicket) -> TradeTicket:
        """The same ticket with the asked-for fields replaced, and nothing else touched."""
        kind = HorizonKind(self.horizon_kind) if self.horizon_kind and self.horizon_kind != "through_weekend" else ticket.horizon_kind
        hours = self.horizon_hours if self.horizon_hours else ticket.horizon_hours
        if self.horizon_hours:
            kind = HorizonKind.HOURS
        if self.horizon_kind == "through_weekend":
            from nightwatch.api.intake import horizon_fields

            kind, hours, _label = horizon_fields("through_weekend", None)
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


def rule_change(question: str, ticket: dict, tickers: list[str]) -> Change:
    """The change a what-if asks for, read by rules; empty when they find none.

    The model takes 10-60 s to name a change. The common ones - a holding period, the
    other direction, another token, "only earnings nights" - are shapes the intake rules
    already read, so they are tried first and the model is asked only when they find
    nothing. Anything the question does not state is left as it was.
    """
    from nightwatch.api import intake

    parsed = intake.parse_message(question, tickers)
    cur_ticker = str(ticket.get("ticker") or "").upper()
    ticker = parsed.ticker if parsed.ticker and parsed.ticker.upper() != cur_ticker else None
    side = parsed.side if parsed.side and parsed.side != ticket.get("side") else None
    # "What if I held it" names a holding verb, not a direction: only an explicit flip counts.
    if side == "long" and not re.search(r"\blong\b|\bbuy\b|做多|买入", question, re.I):
        side = None
    kind, hours = parsed.horizon_kind, parsed.horizon_hours
    lenses: tuple[str, ...] = ()
    if intake.asks_to_narrow(question) or re.search(r"\bworse\b|\bbetter\b|更差|更好", question, re.I):
        low = question.lower()
        lenses = tuple(dict.fromkeys(x.name for x in lens_mod.LENSES if any(p in low for p in x.says)))
    return Change(ticker=ticker, side=side, horizon_kind=kind if kind in ("next_open", "window_end", "hours", "through_weekend") else None,
                  horizon_hours=hours if kind == "hours" else None, lenses=lenses)


def ticket_from(report: dict) -> TradeTicket | None:
    """The ticket a stored report was produced from, rebuilt well enough to re-run.

    Only the fields that drive the analysis; the prose fields come along so the written
    plan rule does not fail a ticket the trader already wrote a plan for.
    """
    t = report.get("ticket") or {}
    if not t.get("ticker"):
        return None
    # A narrowing the desk chose itself is not part of what the trader asked for. Left in
    # the rebuilt ticket it would come back as a requested condition, without the note
    # saying why it is there; dropped, the re-run decides again by the same rule.
    lens_ = ((report.get("analog") or {}).get("lens") or {})
    asked_lenses = () if lens_.get("auto") else tuple(t.get("lenses") or ())
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
            lenses=asked_lenses,
            auto_lens=bool(t.get("auto_lens", True)),
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


VERDICT_ZH = {"GO": "可以做", "REDUCE": "建议减仓", "HEDGE": "建议对冲", "REVIEW": "需要复核", "NO_GO": "不建议做"}


def _describe_zh(change: Change) -> str:
    bits = []
    if change.ticker:
        bits.append(f"换成 {change.ticker.upper()}")
    if change.side:
        bits.append("改为做空" if change.side == "short" else "改为做多")
    if change.horizon_hours:
        bits.append(f"持有 {change.horizon_hours:g} 小时")
    elif change.horizon_kind == "through_weekend":
        bits.append("持有过周末")
    elif change.horizon_kind == "next_open":
        bits.append("持有到下一次开盘")
    elif change.horizon_kind == "window_end":
        bits.append("持有到本时段结束")
    if change.lenses:
        bits.append("只比较：" + lens_mod.describe(lens_mod.resolve(list(change.lenses))))
    return "，".join(bits)


def _verdict_zh(v: str) -> str:
    return VERDICT_ZH.get(v, v)


def compare(before: dict, after: dict, change: Change, lang: str = "en") -> Answer:
    """What changed between two reports of the same night, in the order a trader reads.

    Every number is copied from one of the two reports. The only judgement this function
    makes is which of them are worth printing, and that judgement is the same every time.
    ``lang`` changes the words, never the numbers.
    """
    zh = lang == "zh"
    what = (_describe_zh(change) if zh else change.describe()) or ("这个改动" if zh else "that change")
    refused = _lens_note(after)
    if refused:
        text = f"这个问题我无法如实回答：{refused}。" if zh else f"I cannot answer that one honestly: {refused}."
        return Answer("what_if", text, ("analog cohort",))

    bits = [f"按“{what}”在同一时刻重新计算：" if zh else f"Re-run with {what}, against the same moment:"]
    join = "" if zh else " "

    nb, na = _n(before), _n(after)
    scope = (after.get("analog") or {}).get("scope")
    if na is None:
        reason = ((after.get("analog") or {}).get("result") or {}).get("reason", "too few matches")
        bits.append(f"相似的历史时刻不够多，无法回答（{reason}）。" if zh else f"there were not enough distinct past moments to answer ({reason}).")
        return Answer("what_if", join.join(bits), ("analog cohort",))
    widened = scope == "pooled" and (before.get("analog") or {}).get("scope") != "pooled"
    if zh:
        cohort = f"相似时刻 {na} 个（原来 {nb} 个）" if nb is not None and nb != na else f"相似时刻 {na} 个"
        if widened:
            cohort += "，因单一代币历史不足，改用所有代币的合并历史"
        bits.append(cohort + "。")
    else:
        cohort = f"the cohort is {na} past moments instead of {nb}" if nb is not None and nb != na else f"the cohort is {na} past moments"
        if widened:
            cohort += ", searched across the pooled history because one token's own past does not hold enough of them"
        bits.append(cohort + ".")

    cb, ca = _cohort(before), _cohort(after)
    hb, ha = before.get("primary_horizon"), after.get("primary_horizon")
    # Changing how long the position is held changes what the two medians are measured
    # over, so both windows are named. "Moves from +0.2% to 0.0% over 6h" would quietly
    # compare two numbers that are not measured over the same thing.
    moved_h = bool(hb and ha and hb != ha)
    unchanged = cb.get("median_pct") == ca.get("median_pct") and _p5(before) == _p5(after)
    if zh:
        fh, th = (f"（{hb}）", f"（{ha}）") if moved_h else ("", "")
        if unchanged:
            bits.append(f"中位结果和最差二十分之一不变：{_pct(ca.get('median_pct'))} 和 {_pct(_p5(after))}。")
        else:
            bits.append(f"中位结果从 {_pct(cb.get('median_pct'))}{fh} 变为 {_pct(ca.get('median_pct'))}{th}，最差二十分之一从 {_pct(_p5(before))} 变为 {_pct(_p5(after))}。")
    else:
        from_h = f" over {hb}" if moved_h else ""
        to_h = f" over {ha}" if ha and (not hb or hb != ha) else ""
        if unchanged:
            # A lens that filtered nothing, or a change the distribution did not feel.
            # Saying "moves from -3.3% to -3.3%" is true and reads like a mistake.
            bits.append(f"The middle outcome{to_h} and the one-in-twenty loss are unchanged, at {_pct(ca.get('median_pct'))} and {_pct(_p5(after))}.")
        else:
            bits.append(
                f"The middle outcome moves from {_pct(cb.get('median_pct'))}{from_h} to {_pct(ca.get('median_pct'))}{to_h}, "
                f"and the one-in-twenty loss from {_pct(_p5(before))} to {_pct(_p5(after))}."
            )

    vb, va = (before.get("verdict") or {}), (after.get("verdict") or {})
    if va.get("verdict"):
        cap = (after.get("sizing") or {}).get("binding_cap")
        moved = bool(vb.get("verdict")) and (
            vb.get("verdict") != va.get("verdict") or abs((vb.get("recommended_notional") or 0) - (va.get("recommended_notional") or 0)) > 1
        )
        if zh:
            from nightwatch.api.intake import CAP_ZH

            held = f"，受{CAP_ZH.get(cap, cap.replace('_', ' '))}上限约束" if cap else ""
            if moved:
                bits.append(
                    f"结论从 {_verdict_zh(vb['verdict'])}（{_usd(vb.get('recommended_notional'))}）"
                    f"变为 {_verdict_zh(va['verdict'])}（{_usd(va.get('recommended_notional'))}）{held}。"
                )
            else:
                bits.append(f"结论不变：{_verdict_zh(va['verdict'])}，{_usd(va.get('recommended_notional'))}{held}。")
        else:
            held = f", held by the {cap.replace('_', ' ')} cap" if cap else ""
            if moved:
                bits.append(
                    f"The verdict moves from {vb['verdict']} at {_usd(vb.get('recommended_notional'))} "
                    f"to {va['verdict']} at {_usd(va.get('recommended_notional'))}{held}."
                )
            else:
                bits.append(f"The verdict is unchanged: {va['verdict']} at {_usd(va.get('recommended_notional'))}{held}.")

    return Answer("what_if", join.join(bits), ("analog cohort", "gate and sizing", "re-run"))
