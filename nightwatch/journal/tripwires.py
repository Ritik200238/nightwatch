"""A price tripwire: "tell me if <token> trades through <price>", set from a report.

The invalidation, the stop and the liquidation price are all lines the trader already drew;
this keeps watch on one of them. The recorder checks every armed tripwire against Bitget's
one-minute bars since the last check (their highs and lows, so a wick between two checks is
not missed) and the live ticker. The first time the line is crossed the tripwire fires - once,
never again - and records when and at what price. It then re-runs the desk on the stored
ticket, as a re-check does, so the alert carries the verdict *now*, and POSTs a short JSON
body to the webhook if one was given (the same https-only, public-host-only rule as a watch). A ``tg:<chat id>`` target is
delivered as a Telegram message instead (journal.telegram).

Which way "through" means is fixed when it is armed, from where the line sits against the
price the report was taken at: a line below is crossed on a low at or under it, a line above
on a high at or over it. A long's stop is below and a short's is above, but nothing here
assumes it, so an upside breakout line on a short works the same way.

Why it is not in the receipt chain: a receipt hashes the fields in ``receipts.FIELDS``; adding
one would change every existing digest and break verification of the chain already anchored.
The tripwire keeps its own creation time and the forecast id it points at, and the receipt
already pins that forecast, so the report it hangs off cannot be rewritten; the tripwire
itself is a row on this server and is not tamper-evident.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from nightwatch.journal.watches import BadWebhook, TooMany, _notify, check_webhook, summarise  # noqa: F401
from nightwatch.time_utils import from_epoch_ms, to_epoch_ms, utc_now

log = logging.getLogger("nightwatch.tripwires")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tripwires (
    id TEXT PRIMARY KEY,
    forecast_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    level REAL NOT NULL,
    direction TEXT NOT NULL,                   -- below | above
    label TEXT NOT NULL DEFAULT 'custom',      -- stop | invalidation | liquidation | p5 | custom
    ref_price REAL,
    created_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'armed',      -- armed | fired | expired
    webhook TEXT,
    lang TEXT NOT NULL DEFAULT 'en',
    client TEXT NOT NULL,
    before TEXT NOT NULL,
    checked_to INTEGER NOT NULL,
    fired_at INTEGER,
    fired_price REAL,
    after TEXT,
    error TEXT,
    webhook_status TEXT
);
CREATE INDEX IF NOT EXISTS tripwires_armed ON tripwires (status, created_at);
"""

PER_HOUR = 10
MAX_ARMED = 20  # per visitor, at once
EXPIRES = timedelta(days=30)
LABELS = ("stop", "invalidation", "liquidation", "p5", "custom")

# fetch(ticker, since_ms) -> [(bar_ts_ms, low, high), ...]; the last may be the live ticker.
Fetch = Callable[[str, int], Sequence[tuple[int, float, float]]]


class BadLevel(ValueError):
    pass


def crossed(direction: str, level: float, low: float, high: float) -> bool:
    """Has a bar spanning ``low``..``high`` traded through ``level``?"""
    return low <= level if direction == "below" else high >= level


def direction_for(level: float, ref_price: float | None, side: str) -> str:
    """Which way through the line counts. From the line's place against the price the report
    was taken at; with no price to compare, from the side (a long is stopped below)."""
    if ref_price and ref_price > 0 and level != ref_price:
        return "below" if level < ref_price else "above"
    return "below" if side == "long" else "above"


def _ref_price(report: dict[str, Any]) -> float | None:
    t = report.get("ticket") or {}
    for v in (t.get("entry_price"), ((report.get("snapshot") or {}).get("prices") or {}).get("spot_close")):
        if isinstance(v, int | float) and v > 0:
            return float(v)
    return None


def suggest(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The lines the report already holds, ready to arm: the trader's own stop and written
    invalidation, the liquidation price of a leveraged ticket, and the price at the
    position's one-in-twenty loss. Each carries which way it would be crossed."""
    t = report.get("ticket") or {}
    side = t.get("side") or "long"
    ref = _ref_price(report)
    out: list[dict[str, Any]] = []

    def add(label: str, level: Any, note: str = "") -> None:  # noqa: ANN401
        if isinstance(level, int | float) and level > 0 and not any(abs(o["level"] - level) < 1e-9 for o in out):
            out.append({"label": label, "level": round(float(level), 6), "direction": direction_for(float(level), ref, side), "note": note})

    add("stop", t.get("stop_price"))
    pc = report.get("plan_check") or {}
    if pc.get("kind") == "level":
        add("invalidation", pc.get("level"), str(t.get("invalidation") or ""))
    add("liquidation", (report.get("leverage") or {}).get("liquidation_price"))
    hz = ((report.get("analog") or {}).get("horizons") or {}).get(report.get("primary_horizon") or "")
    loss = hz.get("loss_p5_pct") if isinstance(hz, dict) else None
    if ref and isinstance(loss, int | float) and loss < 0:
        # loss_p5_pct is the position's own profit and loss, so a short's loss is a price rise.
        add("p5", ref * (1 + loss / 100.0) if side == "long" else ref * (1 - loss / 100.0))
    return out


def _view(r: tuple[Any, ...]) -> dict[str, Any]:
    def iso(ms: int | None) -> str | None:
        return from_epoch_ms(ms).isoformat() if ms else None

    return {
        "id": r[0], "forecast_id": r[1], "ticker": r[2], "side": r[3], "level": r[4], "direction": r[5], "label": r[6],
        "ref_price": r[7], "created_at": iso(r[8]), "status": r[9],
        "webhook_host": urlparse(r[10]).hostname if r[10] else None,  # the full URL may carry a secret
        "lang": r[11], "before": json.loads(r[12]), "checked_to": iso(r[13]), "fired_at": iso(r[14]), "fired_price": r[15],
        "after": json.loads(r[16]) if r[16] else None, "error": r[17], "webhook_status": r[18],
    }


_SELECT = "SELECT id, forecast_id, ticker, side, level, direction, label, ref_price, created_at, status, webhook, lang, before, checked_to, fired_at, fired_price, after, error, webhook_status FROM tripwires"


def get(conn: sqlite3.Connection, tid: str) -> dict[str, Any] | None:
    r = conn.execute(f"{_SELECT} WHERE id=?", (tid,)).fetchone()
    return _view(r) if r else None


def for_report(conn: sqlite3.Connection, forecast_id: int, client: str) -> list[dict[str, Any]]:
    """The tripwires this visitor set on this report, newest first."""
    rows = conn.execute(f"{_SELECT} WHERE forecast_id=? AND client=? ORDER BY created_at DESC LIMIT 20", (forecast_id, client)).fetchall()
    return [_view(r) for r in rows]


def create(
    conn: sqlite3.Connection, *, forecast_id: int, report: dict[str, Any], level: float, label: str, webhook: str | None, lang: str, client: str, now: datetime | None = None
) -> dict[str, Any]:
    """Arm a tripwire. Asking twice for the same line on the same report returns the first."""
    t = report.get("ticket") or {}
    ticker, side = str(t.get("ticker") or "").upper(), t.get("side") or "long"
    if not ticker:
        raise BadLevel("that report has no ticker to watch")
    if not isinstance(level, int | float) or not (0 < level < 1e9) or level != level:
        raise BadLevel("the price must be a positive number")
    label = label if label in LABELS else "custom"
    ref = _ref_price(report)
    if ref and abs(level - ref) / ref < 1e-6:
        raise BadLevel("that price is the entry price itself")
    dup = conn.execute(
        "SELECT id FROM tripwires WHERE forecast_id=? AND client=? AND status='armed' AND ABS(level-?)<1e-9", (forecast_id, client, float(level))
    ).fetchone()
    if dup:
        return get(conn, dup[0]) or {}
    now = now or utc_now()
    since = to_epoch_ms(now) - 3_600_000
    if conn.execute("SELECT COUNT(*) FROM tripwires WHERE client=? AND created_at>=?", (client, since)).fetchone()[0] >= PER_HOUR:
        raise TooMany
    if conn.execute("SELECT COUNT(*) FROM tripwires WHERE client=? AND status='armed'", (client,)).fetchone()[0] >= MAX_ARMED:
        raise TooMany
    tid = secrets.token_urlsafe(9)
    with conn:
        conn.execute(
            "INSERT INTO tripwires (id, forecast_id, ticker, side, level, direction, label, ref_price, created_at, webhook, lang, client, before, checked_to) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, forecast_id, ticker, side, float(level), direction_for(float(level), ref, side), label, ref, to_epoch_ms(now), webhook, lang, client,
             json.dumps(summarise(report)), to_epoch_ms(now)),
        )
    return get(conn, tid) or {}


def run_armed(
    conn: sqlite3.Connection,
    fetch: Fetch,
    rerun: Callable[[dict[str, Any]], dict[str, Any]],
    load_report: Callable[[int], dict[str, Any] | None],
    *,
    now: datetime | None = None,
) -> int:
    """Check every armed tripwire; fire the ones crossed. Returns how many fired."""
    now = now or utc_now()
    now_ms = to_epoch_ms(now)
    fired = 0
    rows = conn.execute(
        "SELECT id, forecast_id, ticker, level, direction, webhook, before, checked_to, created_at, lang FROM tripwires WHERE status='armed'"
    ).fetchall()
    for tid, fid, ticker, level, direction, hook, before_json, checked_to, created_at, lang in rows:
        if now_ms - created_at > EXPIRES.total_seconds() * 1000:
            with conn:
                conn.execute("UPDATE tripwires SET status='expired' WHERE id=? AND status='armed'", (tid,))
            continue
        try:
            bars = list(fetch(ticker, checked_to))
        except Exception as exc:  # noqa: BLE001 - one dead symbol must not stop the others
            log.warning("tripwire %s: no prices: %s", tid, exc)
            continue
        hit = next(((ts, lo, hi) for ts, lo, hi in sorted(bars) if crossed(direction, level, lo, hi)), None)
        if hit is None:
            with conn:
                conn.execute("UPDATE tripwires SET checked_to=? WHERE id=? AND status='armed'", (max([now_ms - 120_000, *[b[0] for b in bars]]), tid))
            continue
        ts, lo, hi = hit
        price = lo if direction == "below" else hi
        # Claim it before anything slow happens: the status flip is what makes it fire once.
        with conn:
            claimed = conn.execute(
                "UPDATE tripwires SET status='fired', fired_at=?, fired_price=? WHERE id=? AND status='armed'", (ts, price, tid)
            ).rowcount
        if claimed != 1:
            continue
        fired += 1
        after: dict[str, Any] | None = None
        err: str | None = None
        try:
            stored = load_report(fid)
            if stored is None:
                raise LookupError("the stored report is no longer kept")
            after = summarise(rerun(stored))
        except Exception as exc:  # noqa: BLE001 - the alert still stands without the verdict
            err = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("tripwire %s fired but the re-run failed: %s", tid, err)
        hook_status = None
        if hook:
            hook_status = _notify(hook, {
                "tripwire_id": tid, "forecast_id": fid, "ticker": ticker, "level": level, "direction": direction,
                "fired_at": from_epoch_ms(ts).isoformat(), "fired_price": price, "before": json.loads(before_json), "after": after,
            }, lang)
        with conn:
            conn.execute("UPDATE tripwires SET after=?, error=?, webhook_status=? WHERE id=?", (json.dumps(after) if after else None, err, hook_status, tid))
    return fired


def make_fetch(spot: Any, perp: Any, entries: Sequence[Any]) -> Fetch:  # noqa: ANN401
    """Bars from Bitget since the last check, and the live ticker for the gap after them.
    The perpetual's symbol where the token has one, else the spot token."""
    from nightwatch.data.models import Interval

    by_ticker = {e.ticker: e for e in entries}

    def fetch(ticker: str, since_ms: int) -> list[tuple[int, float, float]]:
        e = by_ticker.get(ticker)
        if e is None:
            raise LookupError(f"{ticker} is not in the universe")
        client, symbol = (perp, e.perp_symbol) if e.perp_symbol else (spot, e.spot_symbol)
        gap_min = max(1.0, (to_epoch_ms(utc_now()) - since_ms) / 60_000)
        interval, minutes = (Interval.M1, 1) if gap_min <= 900 else (Interval.M15, 15) if gap_min <= 9000 else (Interval.H1, 60)
        bars = client.get_recent_bars(symbol, interval, limit=min(1000, int(gap_min / minutes) + 3))
        out = [(to_epoch_ms(b.ts), b.low, b.high) for b in bars if to_epoch_ms(b.ts) >= since_ms]
        tk = client.get_ticker(symbol)
        if tk.last:
            out.append((to_epoch_ms(utc_now()), tk.last, tk.last))
        return out

    return fetch
