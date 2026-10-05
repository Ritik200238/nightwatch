"""A small picture for a chat answer: the numbers of the answer, laid out as a card.

The chat answers in sentences. For the questions where a picture helps - a price shock
against the report's own tail, a changed trade against the one on screen, a base rate as a
count out of N, the versions of a trade side by side - the response also carries a ``card``
the page draws as a few bars or rows.

The rule is the follow-up layer's own: a card holds no number the answer or the report on
screen does not already hold. Money at a shock is the position's arithmetic the sentence
prints; everything else is copied out of a field. Nothing here reads market data, the
database or a model, and a card that cannot be built from what it is handed is simply
absent: the answer stands on its own text.
"""

from __future__ import annotations

import logging
from typing import Any

from nightwatch.api import followup

log = logging.getLogger("nightwatch.cards")


def _worst_stress(r: dict) -> tuple[float | None, str | None]:
    """The worst priced stress preset by money, and its name."""
    st = r.get("stress") or {}
    rows = [(p, i) for p, i in zip(st.get("presets") or [], st.get("impacts") or [], strict=False) if i.get("total_pnl_quote") is not None]
    if not rows:
        return None, None
    p, i = min(rows, key=lambda x: x[1]["total_pnl_quote"])
    worst = float(i["total_pnl_quote"])
    lev = r.get("leverage") or {}
    margin = lev.get("margin_quote") if lev.get("liquidation_distance_pct") is not None else None
    if margin:
        worst = max(worst, -float(margin))  # a leveraged position cannot lose more than its margin
    return worst, p.get("name")


def _headline_size(r: dict) -> float | None:
    v = r.get("verdict") or {}
    size = v.get("recommended_notional") if v.get("recommended_notional") is not None else (r.get("ticket") or {}).get("notional_quote")
    return float(size) if size is not None else None


def _exit_bps(r: dict) -> float | None:
    return ((r.get("execution") or {}).get("exit_quote") or {}).get("total_cost_bps")


# ------------------------------------------------------------------------------ shock


def shock_card(r: dict, question: str) -> dict | None:
    m = followup.SHOCK.search(question)
    t = r.get("ticket") or {}
    if not m or not t.get("notional_quote"):
        return None
    size = float(next(g for g in m.groups() if g))
    if not 0 < size < 100:
        return None
    notional = float(t["notional_quote"])
    long_ = (t.get("side") or "long") == "long"
    up = bool(followup._UP.search(question))
    move = size if up else -size  # the stock's move
    pnl_pct = move if long_ else -move  # the position's
    p5_pct, p5_quote = followup._loss_at_size(r)
    worst, worst_name = _worst_stress(r)
    presets = {p["id"]: p for p in ((r.get("stress") or {}).get("presets") or [])}
    p5, p1 = presets.get("closed_window_gap_p5"), presets.get("closed_window_gap_p1")
    past = None
    if p5 or p1:
        n = ((p1 or p5).get("calibration") or {}).get("n")
        beyond = None
        if pnl_pct < 0:  # the presets are the adverse tail only, so only a loss is placed on it
            if p1 and abs(p1.get("price_move_pct") or 0) < size:
                beyond = "1_in_100"
            elif p5 and abs(p5.get("price_move_pct") or 0) < size:
                beyond = "1_in_20"
        past = {"p5_move_pct": (p5 or {}).get("price_move_pct"), "p1_move_pct": (p1 or {}).get("price_move_pct"), "windows": n, "beyond": beyond}
    return {
        "kind": "shock", "ticker": t.get("ticker"), "side": "long" if long_ else "short", "size": notional,
        "move_pct": move, "pnl_pct": pnl_pct, "pnl_quote": notional * pnl_pct / 100.0,
        "p5_pct": p5_pct, "p5_quote": p5_quote, "worst_quote": worst, "worst_name": worst_name, "past": past,
    }


# ----------------------------------------------------------------------------- compare


def _row(key: str, unit: str, before: Any, after: Any) -> dict | None:  # noqa: ANN401
    return None if before is None and after is None else {"key": key, "unit": unit, "before": before, "after": after}


def compare_card(before: dict, after: dict) -> dict | None:
    """A what-if re-run: the trade on screen, then the changed one, row by row."""
    if not (after.get("verdict") or {}).get("verdict"):
        return None
    wb, _ = _worst_stress(before)
    wa, _ = _worst_stress(after)
    rows = [
        _row("verdict", "verdict", (before.get("verdict") or {}).get("verdict"), after["verdict"]["verdict"]),
        _row("size", "usd", _headline_size(before), _headline_size(after)),
        _row("p5", "pct", followup._p5(before), followup._p5(after)),
        _row("worst", "usd", wb, wa),
        _row("exit", "bps", _exit_bps(before), _exit_bps(after)),
    ]
    return {"kind": "compare", "ticker": (after.get("ticket") or {}).get("ticker"), "rows": [x for x in rows if x]}


def size_card(r: dict, question: str) -> dict | None:
    """"Halve it", "what about 40k": the sweep's point at that size beside the one asked for."""
    sizes = (r.get("sensitivity") or {}).get("sizes") or []
    requested = (r.get("ticket") or {}).get("notional_quote")
    asked = followup.asked_size(r, question)
    if not (sizes and asked and requested) or abs(asked - requested) <= 1:
        return None
    p = followup._nearest(sizes, "notional", asked)
    if not p:
        return None
    here = followup._nearest(sizes, "notional", float(requested))
    same = here is not None and abs(here["notional"] - requested) <= max(1.0, requested * 0.01)
    rows = [
        _row("verdict", "verdict", (r.get("verdict") or {}).get("verdict"), p["verdict"]),
        _row("size", "usd", float(requested), p["notional"]),
        # The sweep's worst severe preset, as a share of the position at each size.
        _row("worst_pct", "pct", here.get("worst_severe_pct") if same else None, p.get("worst_severe_pct")),
        _row("exit", "bps", _exit_bps(r), p.get("exit_cost_bps")),
    ]
    return {"kind": "compare", "ticker": (r.get("ticket") or {}).get("ticker"), "rows": [x for x in rows if x]}


# --------------------------------------------------------------------------- base rate


def base_rate_card(facts: dict) -> dict | None:
    if not facts or not (facts.get("windows") or facts.get("conditional")):
        return None
    keep = ("ticker", "move_pct", "up", "weekend", "windows", "conditional")
    return {"kind": "base_rate", **{k: facts.get(k) for k in keep}}


# ------------------------------------------------------------------------------- ways


def ways_card(rows: list[dict], size: float | None) -> dict | None:
    from nightwatch.api import ways

    if not rows:
        return None
    best = ways.pick(rows, size) if size is not None else None
    keep = ("label", "verdict", "size", "hours", "p5_pct", "p5_quote", "worst_quote", "exit_bps")
    return {
        "kind": "ways",
        "rows": [{**{k: x.get(k) for k in keep}, "label_zh": ways.LABEL_ZH.get(x["label"])} for x in rows],
        "pick": best["label"] if best else None,
    }


# --------------------------------------------------------------------------- the entry


def card_for(out: dict[str, Any], context: dict | None, question: str) -> dict | None:
    """The card for one chat answer, or None. Never raises: a card is an extra."""
    try:
        mode, kind = out.get("mode"), out.get("answer_kind")
        if mode == "base_rate":
            return base_rate_card(out.get("base_rate") or {})
        if mode == "ways":
            rows = out.get("ways") or []
            return ways_card(rows, (context or {}).get("ticket", {}).get("notional_quote") if context else None)
        if context is None:
            return None
        if mode == "what_if" and out.get("report"):
            return compare_card(context, out["report"])
        if kind == "shock":
            return shock_card(context, question)
        if kind == "size":
            return size_card(context, question)
    except Exception as exc:  # noqa: BLE001 - the answer stands without its card
        log.warning("card skipped: %s", exc)
    return None
