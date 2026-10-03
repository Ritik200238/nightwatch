"""Where each headline number on a report came from.

Four kinds, nothing else:

* ``live``     - read from Bitget (order book, margin tiers, MCP) when the report ran.
* ``history``  - measured from past data; ``n`` says how many past moments.
* ``assumed``  - a preset or a policy constant, not measured (stress sizes, caps, a stop
                 the trader typed).
* ``ai``       - written by the Qwen analyst. It never moves a number.

Built from the serialised report, so it uses only facts the report already carries and
can be rebuilt for a stored one. The page turns these structured fields into words (en/zh);
the MCP and JSON output carry them as they are.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

KINDS = ("live", "history", "assumed", "ai")


def _age_s(as_of: Any, ts: Any) -> int | None:
    try:
        a, b = datetime.fromisoformat(str(as_of)), datetime.fromisoformat(str(ts))
        return max(0, round((a - b).total_seconds()))
    except (TypeError, ValueError):
        return None


def preset_provenance(p: dict[str, Any]) -> dict[str, Any]:
    """One stress preset: measured from this token's history when its calibration says
    how many observations it came from, otherwise a fixed multiplier or rule."""
    cal = p.get("calibration") or {}
    src = str(cal.get("source") or "")
    if str(p.get("id", "")).startswith("replay_"):
        return {"kind": "history", "n": 1, "unit": "day", "source": f"{src} ({cal.get('date', '')})".strip()}
    if isinstance(cal.get("n"), int | float) and cal["n"] > 0:
        return {"kind": "history", "n": int(cal["n"]), "unit": "moment", "source": src}
    if src.startswith(("rv_24h", "max(rv")) and "book" not in src:
        return {"kind": "history", "n": None, "unit": "volatility", "source": src}
    if src == "perp funding history":
        return {"kind": "history", "n": None, "unit": "funding", "source": src}
    return {"kind": "assumed", "n": None, "unit": "", "source": src or "preset rule"}


def build(payload: dict[str, Any]) -> dict[str, Any]:
    as_of = payload.get("as_of")
    ex = payload.get("execution") or {}
    an = payload.get("analog") or {}
    gate = payload.get("gate") or {}
    stress = payload.get("stress") or {}
    out: dict[str, Any] = {"kinds": list(KINDS), "items": {}}
    items = out["items"]

    # Exit cost: the Bitget spot book, and how old it was when the verdict was made.
    mode = str(ex.get("book_source") or "none")
    if mode != "none" and (ex.get("exit_quote") or ex.get("book_ts")):
        items["exit_cost"] = {
            "kind": "live", "source": "Bitget spot order book", "feed": "api.bitget.com spot orderbook",
            "ts": ex.get("book_ts"), "age_s": _age_s(as_of, ex.get("book_ts")), "mode": mode, "stale": mode.startswith("recorded ("),
        }

    # History: the analog search over this token's own Bitget candles.
    h = (an.get("horizons") or {}).get(payload.get("primary_horizon")) or {}
    c = h.get("cohort") or {}
    n = c.get("n") if not c.get("insufficient") else None
    hist = {"kind": "history", "source": "past moments like now, from Bitget candles", "n": n, "unit": "moment",
            "n_candidates": (an.get("result") or {}).get("n_candidates"), "horizon": payload.get("primary_horizon")}
    if an:
        items["analog"] = hist

    if gate.get("risk_basis") == "distance to stop":
        items["loss_line"] = {"kind": "assumed", "source": "the stop price you entered", "n": None}
    elif an:
        fit = (h.get("adjustment") or {}).get("n_fit")
        items["loss_line"] = {**hist, "n_fit": fit}

    presets = stress.get("presets") or []
    impacts = stress.get("impacts") or []
    per = {p.get("id"): preset_provenance(p) for p in presets if p.get("id")}
    if per:
        items["stress"] = per
        pairs = [(p, i) for p, i in zip(presets, impacts, strict=False) if isinstance(i.get("total_pnl_quote"), int | float)]
        if pairs:
            worst = min(pairs, key=lambda pi: pi[1]["total_pnl_quote"])[0]
            items["worst_stress"] = {**per.get(worst.get("id"), {}), "preset": worst.get("id")}
    mc = stress.get("monte_carlo")
    if mc:
        items["monte_carlo"] = {"kind": "history", "source": "block bootstrap of this token's hourly returns", "n": mc.get("source_hours"), "unit": "hour", "n_paths": mc.get("n_paths")}

    lev = payload.get("leverage")
    if lev and lev.get("perp_symbol"):
        live = lev.get("tiers_source") == "bitget"
        items["liquidation"] = {
            "kind": "live" if live else "assumed",
            "source": "Bitget perpetual margin tiers for this size" if live else f"{float(lev.get('mmr') or 0) * 100:.1f}% maintenance margin assumed (tiers unavailable)",
            "ts": as_of if live else None, "age_s": 0 if live else None, "n": lev.get("analog_of"), "hits": lev.get("analog_hits"),
        }

    if (payload.get("sizing") or {}).get("caps"):
        items["size"] = {"kind": "assumed", "source": "policy caps: risk budget, concentration, cost budget"}
    items["analyst"] = {"kind": "ai", "source": "Qwen analyst; reads the finished report, never moves a number"}
    return out
