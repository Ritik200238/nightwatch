"""A plan made in advance: one action chosen per way the trade can go wrong.

"Decide now, not at 3 a.m." The report already lists the ways a trade loses money. This turns
the ones that sit at a price into concrete lines (a bad reopen gap is a price, liquidation is a
price, the one-in-twenty loss is a price) with how often history put the trade there, and lets
the trader choose hold / cut half / exit / hedge for each *before* it happens. Saving can arm a
price tripwire on every line in one step, and when one fires the alert repeats the choice:
"You decided in advance: cut half".

Every number is computed from the stored report; nothing here is asked of a model and nothing
here changes a number.

Why it is not in the receipt chain: a receipt hashes the fields in ``receipts.FIELDS``; adding
one would change every existing digest and break verification of the chain already anchored.
A plan keeps its own timestamp and the receipt hash of the forecast it points at; the receipt
already pins that report, but the plan itself is a row on this server and is not tamper-evident.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from nightwatch.journal import tripwires
from nightwatch.time_utils import from_epoch_ms, to_epoch_ms, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    forecast_id INTEGER NOT NULL,
    client TEXT NOT NULL,
    key TEXT NOT NULL,                 -- the scenario: gap_bad | invalidation | liquidation | p5 | ...
    action TEXT NOT NULL,              -- hold | cut_half | exit | hedge
    level REAL NOT NULL,
    direction TEXT NOT NULL,
    label TEXT NOT NULL,               -- the tripwire label this line arms as
    detail TEXT,                       -- size of the action in USDT, as chosen
    tripwire_id TEXT,
    receipt TEXT,                      -- the receipt hash of the forecast this plan points at
    created_at INTEGER NOT NULL,
    PRIMARY KEY (forecast_id, client, key)
);
CREATE INDEX IF NOT EXISTS plans_tripwire ON plans (tripwire_id);
"""

ACTIONS = ("hold", "cut_half", "exit", "hedge")
MAX_SCENARIOS = 4

_ACTION_EN = {"hold": "hold", "cut_half": "cut half", "exit": "exit", "hedge": "hedge with the perp"}
_ACTION_ZH = {"hold": "持有不动", "cut_half": "减仓一半", "exit": "全部离场", "hedge": "用永续合约对冲"}

# The failure modes that sit at a price, and the tripwire label each line arms as.
_PRESET_OF = {"gap_bad": "closed_window_gap_p5", "gap_worst": "closed_window_gap_p1", "earnings": "earnings_gap_typical"}
_LABEL = {"invalidation": "invalidation", "liquidation": "liquidation", "stop_jumped": "stop", "p5": "p5"}
_TITLE_ZH = {"p5": "二十分之一的亏损线"}


class BadPlan(ValueError):
    pass


def _num(x: Any) -> float | None:  # noqa: ANN401
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) and x == x else None


def adverse_price(ref: float, move_pct: float) -> float:
    """The price after a move of ``move_pct`` (a signed price change, as the stress presets
    carry it: already the tail that hurts this side, so it applies as it stands)."""
    return ref * (1.0 + move_pct / 100.0)


def p5_price(ref: float, loss_p5_pct: float, side: str) -> float:
    """The price at the position's one-in-twenty loss. ``loss_p5_pct`` is the position's own
    profit and loss, so a long's loss is a price fall and a short's is a price rise."""
    return ref * (1 + loss_p5_pct / 100.0) if side == "long" else ref * (1 - loss_p5_pct / 100.0)


def _hedge(report: dict[str, Any]) -> dict[str, Any] | None:
    h = (report.get("execution") or {}).get("hedge_quote")
    if not isinstance(h, dict) or not _num(h.get("hedged_notional")) or not h.get("perp_symbol"):
        return None
    return {"perp_symbol": h["perp_symbol"], "notional": float(h["hedged_notional"]), "cost_quote": _num(h.get("total_cost_quote"))}


def scenarios(report: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: C901
    """The top ways this trade fails that sit at a price, worst first, each with the price,
    how often history put it there, and what each action would mean in size."""
    t = report.get("ticket") or {}
    side = t.get("side") or "long"
    ref = tripwires._ref_price(report)
    if not ref:
        return []
    notional = _num(t.get("notional_quote")) or 0.0
    presets = {p.get("id"): p for p in ((report.get("stress") or {}).get("presets") or []) if isinstance(p, dict)}
    pc = report.get("plan_check") or {}
    lev = report.get("leverage") or {}
    out: list[dict[str, Any]] = []

    def add(key: str, price: float | None, mode: dict[str, Any], *, title: str, title_zh: str | None, history: str, chance: float | None, source: str) -> None:
        if price is None or not (0 < price < 1e9) or abs(price - ref) / ref < 1e-6:
            return
        if any(abs(o["price"] - price) / price < 1e-3 for o in out):  # two names for one line: keep the first (worse)
            return
        out.append({
            "key": key, "title": title, "title_zh": title_zh, "price": round(price, 6), "ref_price": round(ref, 6),
            "move_pct": round((price / ref - 1) * 100, 3), "direction": tripwires.direction_for(price, ref, side),
            "label": _LABEL.get(key, "custom"), "loss_quote": mode.get("loss_quote"), "loss_pct": mode.get("loss_pct"),
            "history": history, "chance": chance, "source": source,
        })

    for m in report.get("failure_modes") or []:
        if len(out) >= MAX_SCENARIOS:
            break
        key = m.get("key")
        price: float | None = None
        if key in _PRESET_OF:
            mv = _num((presets.get(_PRESET_OF[key]) or {}).get("price_move_pct"))
            price = adverse_price(ref, mv) if mv is not None else None
        elif key == "invalidation" and pc.get("kind") == "level":
            price = _num(pc.get("level"))
        elif key == "invalidation" and pc.get("kind") == "move" and _num(pc.get("distance_pct")) is not None:
            price = adverse_price(ref, float(pc["distance_pct"]))
        elif key == "liquidation":
            price = _num(lev.get("liquidation_price"))
        elif key == "stop_jumped":
            price = _num(t.get("stop_price"))
        if price is not None:
            add(key, price, m, title=m.get("title") or key, title_zh=m.get("title_zh"), history=m.get("likelihood") or "", chance=_num(m.get("chance")), source=m.get("source") or "")
    # The one-in-twenty line, when there is room and it is not already one of the above.
    hz = ((report.get("analog") or {}).get("horizons") or {}).get(report.get("primary_horizon") or "")
    loss = _num(hz.get("loss_p5_pct")) if isinstance(hz, dict) else None
    if len(out) < MAX_SCENARIOS and loss is not None and loss < 0:
        n = (hz.get("cohort") or {}).get("n")
        add("p5", p5_price(ref, loss, side), {"loss_pct": loss, "loss_quote": loss / 100.0 * notional}, title="The 1-in-20 loss line", title_zh=_TITLE_ZH["p5"],
            history=f"1 in 20 of {n} past moments like this ended at or beyond this line" if n else "1 in 20 past moments like this ended at or beyond this line",
            chance=0.05, source="analog cohort")
    hedge = _hedge(report)
    for s in out:
        s["actions"] = {
            "hold": {"size_quote": 0.0},
            "cut_half": {"size_quote": round(notional / 2, 2)},
            "exit": {"size_quote": round(notional, 2)},
            **({"hedge": {"size_quote": round(hedge["notional"], 2), "perp_symbol": hedge["perp_symbol"], "cost_quote": hedge["cost_quote"]}} if hedge else {}),
        }
    return out


def action_word(action: str, lang: str = "en") -> str:
    return (_ACTION_ZH if lang == "zh" else _ACTION_EN).get(action, action)


def reminder(action: str, detail: str | None, lang: str = "en") -> str:
    """What the alert says when the line is crossed."""
    word = action_word(action, lang)
    if lang == "zh":
        return f"你事先决定：{word}" + (f"（{detail}）" if detail else "") + "。"
    return f"You decided in advance: {word}" + (f" ({detail})" if detail else "") + "."


def _detail(action: str, sc: dict[str, Any]) -> str | None:
    a = sc["actions"].get(action) or {}
    size = a.get("size_quote")
    if action == "hedge" and size:
        return f"short {size:,.0f} USDT of {a.get('perp_symbol')}"
    return f"about {size:,.0f} USDT" if size else None


_SEL = "SELECT key, action, level, direction, label, detail, tripwire_id, receipt, created_at FROM plans"


def _row_view(r: tuple[Any, ...]) -> dict[str, Any]:
    return {"key": r[0], "action": r[1], "level": r[2], "direction": r[3], "label": r[4], "detail": r[5], "tripwire_id": r[6], "receipt": r[7],
            "saved_at": from_epoch_ms(r[8]).isoformat()}


def load(conn: sqlite3.Connection, forecast_id: int, client: str) -> list[dict[str, Any]]:
    return [_row_view(r) for r in conn.execute(f"{_SEL} WHERE forecast_id=? AND client=? ORDER BY created_at, key", (forecast_id, client)).fetchall()]


def for_tripwire(conn: sqlite3.Connection, tripwire_id: str) -> dict[str, Any] | None:
    try:
        r = conn.execute(f"{_SEL} WHERE tripwire_id=? ORDER BY created_at DESC LIMIT 1", (tripwire_id,)).fetchone()
    except sqlite3.OperationalError:  # a database from before plans existed
        return None
    return _row_view(r) if r else None


def alert_note(conn: sqlite3.Connection, tripwire_id: str, lang: str = "en") -> dict[str, Any] | None:
    """The plan behind a tripwire, ready for an alert payload: what was chosen and the line to say."""
    p = for_tripwire(conn, tripwire_id)
    if p is None:
        return None
    return {"key": p["key"], "action": p["action"], "detail": p["detail"], "saved_at": p["saved_at"], "reminder": reminder(p["action"], p["detail"], lang)}


def save(
    conn: sqlite3.Connection, *, forecast_id: int, report: dict[str, Any], choices: dict[str, str], arm: bool, webhook: str | None, lang: str, client: str, now: datetime | None = None
) -> dict[str, Any]:
    """Store the chosen action per scenario; with ``arm``, set a tripwire on each line so the
    alert can remind the trader. Saving again replaces the earlier choice for that scenario."""
    by_key = {s["key"]: s for s in scenarios(report)}
    if not choices:
        raise BadPlan("choose at least one action")
    for k, a in choices.items():
        if k not in by_key:
            raise BadPlan(f"'{k}' is not one of this report's scenarios")
        if a not in ACTIONS or a not in by_key[k]["actions"]:
            raise BadPlan(f"'{a}' is not available for '{k}'")
    now = now or utc_now()
    arm_error: str | None = None
    for k, a in choices.items():
        sc = by_key[k]
        old = conn.execute("SELECT tripwire_id FROM plans WHERE forecast_id=? AND client=? AND key=?", (forecast_id, client, k)).fetchone()
        tid: str | None = old[0] if old else None
        if arm:
            try:
                tid = tripwires.create(conn, forecast_id=forecast_id, report=report, level=sc["price"], label=sc["label"], webhook=webhook, lang=lang, client=client, now=now).get("id")
            except tripwires.TooMany:
                arm_error = "too_many"
            except tripwires.BadLevel:
                arm_error = "bad_level"
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO plans (forecast_id, client, key, action, level, direction, label, detail, tripwire_id, receipt, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (forecast_id, client, k, a, sc["price"], sc["direction"], sc["label"], _detail(a, sc), tid, str(report.get("receipt") or "") or None, to_epoch_ms(now)),
            )
    return {**view(conn, forecast_id, report, client), "arm_error": arm_error}


def view(conn: sqlite3.Connection, forecast_id: int, report: dict[str, Any], client: str) -> dict[str, Any]:
    """The scenarios with this visitor's saved choice on each, and the state of its tripwire."""
    saved = {p["key"]: p for p in load(conn, forecast_id, client)}
    scs = scenarios(report)
    for s in scs:
        p = saved.get(s["key"])
        if p:
            tw = tripwires.get(conn, p["tripwire_id"]) if p["tripwire_id"] else None
            s["chosen"] = {**p, "tripwire_status": tw["status"] if tw else None, "fired_price": tw["fired_price"] if tw else None, "fired_at": tw["fired_at"] if tw else None}
    return {"forecast_id": forecast_id, "receipt": report.get("receipt"), "scenarios": scs, "saved_at": max((p["saved_at"] for p in saved.values()), default=None)}
