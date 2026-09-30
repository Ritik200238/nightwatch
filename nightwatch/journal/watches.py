"""A re-check at the next US close: the same trade, judged again once the market has moved.

A visitor asks for it on a stored report; the recorder finds watches whose time has come,
re-runs the desk on the rebuilt ticket (not journaled, like a what-if: nobody took it) and
keeps the verdict before and after. A webhook, if given, gets a short JSON POST.
Email is not implemented.

The re-check runs 15 minutes after the bell, not at it, so the last bars have landed.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import secrets
import socket
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from nightwatch.time_utils import (
    EARLY_CLOSE,
    ET,
    REGULAR_CLOSE,
    from_epoch_ms,
    is_early_close,
    is_trading_day,
    next_trading_day,
    to_epoch_ms,
    utc_now,
)

log = logging.getLogger("nightwatch.watches")

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    id TEXT PRIMARY KEY,
    forecast_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    due_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | done | failed
    webhook TEXT,
    lang TEXT NOT NULL DEFAULT 'en',
    client TEXT NOT NULL,
    before TEXT NOT NULL,
    after TEXT,
    done_at INTEGER,
    error TEXT,
    webhook_status TEXT
);
CREATE INDEX IF NOT EXISTS watches_due ON watches (status, due_at);
"""

GRACE = timedelta(minutes=15)
PER_HOUR = 10


class BadWebhook(ValueError):
    pass


class TooMany(Exception):
    pass


def _close_utc(d: date) -> datetime:
    t = EARLY_CLOSE if is_early_close(d) else REGULAR_CLOSE
    return datetime.combine(d, t, tzinfo=ET).astimezone(UTC)


def next_us_close(now: datetime) -> datetime:
    """The next regular-session close after ``now`` (13:00 on early-close days)."""
    d = now.astimezone(ET).date()
    if is_trading_day(d) and now < _close_utc(d):
        return _close_utc(d)
    return _close_utc(next_trading_day(d))


def check_webhook(url: str | None) -> str | None:
    """https only, and not a door into the operator's own network."""
    if not url or not url.strip():
        return None
    url = url.strip()
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or len(url) > 500:
        raise BadWebhook("The webhook must be a plain https:// URL.")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise BadWebhook("The webhook host does not resolve.") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise BadWebhook("The webhook must point at a public host.")
    return url


def summarise(report: dict[str, Any]) -> dict[str, Any]:
    v = report.get("verdict") or {}
    g = report.get("gate") or {}
    hz = ((report.get("analog") or {}).get("horizons") or {}).get(report.get("primary_horizon") or "")
    hz = hz if isinstance(hz, dict) else {}
    return {
        "as_of": report.get("as_of"),
        "verdict": v.get("verdict"),
        "recommended_notional": v.get("recommended_notional"),
        "requested_notional": v.get("requested_notional"),
        "gate": g.get("decision"),
        "tail_p5_pct": hz.get("loss_p5_pct"),  # the position's one-in-twenty loss, by side
        "median_pct": hz.get("pnl_median_pct"),
    }


def create(conn: sqlite3.Connection, *, forecast_id: int, report: dict[str, Any], webhook: str | None, lang: str, client: str) -> dict[str, Any]:
    """One pending watch per visitor and report: asking twice returns the first."""
    row = conn.execute("SELECT id FROM watches WHERE forecast_id=? AND client=? AND status='pending'", (forecast_id, client)).fetchone()
    if row:
        return get(conn, row[0]) or {}
    since = to_epoch_ms(utc_now()) - 3_600_000
    if conn.execute("SELECT COUNT(*) FROM watches WHERE client=? AND created_at>=?", (client, since)).fetchone()[0] >= PER_HOUR:
        raise TooMany
    wid = secrets.token_urlsafe(9)
    now = utc_now()
    due = next_us_close(now) + GRACE
    with conn:
        conn.execute(
            "INSERT INTO watches (id, forecast_id, created_at, due_at, webhook, lang, client, before) VALUES (?,?,?,?,?,?,?,?)",
            (wid, forecast_id, to_epoch_ms(now), to_epoch_ms(due), webhook, lang, client, json.dumps(summarise(report))),
        )
    return get(conn, wid) or {}


def get(conn: sqlite3.Connection, wid: str) -> dict[str, Any] | None:
    r = conn.execute(
        "SELECT id, forecast_id, created_at, due_at, status, webhook, lang, before, after, done_at, error, webhook_status FROM watches WHERE id=?",
        (wid,),
    ).fetchone()
    if r is None:
        return None

    def iso(ms: int | None) -> str | None:
        return from_epoch_ms(ms).isoformat() if ms else None

    before = json.loads(r[7])
    after = json.loads(r[8]) if r[8] else None
    return {
        "id": r[0], "forecast_id": r[1], "created_at": iso(r[2]), "due_at": iso(r[3]), "status": r[4],
        "webhook_host": urlparse(r[5]).hostname if r[5] else None,  # the full URL may carry a secret
        "lang": r[6], "before": before, "after": after, "moved": _moved(before, after) if after else None,
        "done_at": iso(r[9]), "error": r[10], "webhook_status": r[11],
        "email": "not implemented",
    }


def _moved(b: dict[str, Any], a: dict[str, Any]) -> bool:
    return b.get("verdict") != a.get("verdict") or abs((b.get("recommended_notional") or 0) - (a.get("recommended_notional") or 0)) > 1


def _notify(url: str, body: dict[str, Any]) -> str:
    import httpx

    try:
        check_webhook(url)  # the address may have changed since it was accepted
        r = httpx.post(url, json=body, timeout=5.0, follow_redirects=False)
        return f"http {r.status_code}"
    except Exception as exc:  # noqa: BLE001 - a dead webhook must not stop the re-check
        return f"failed: {type(exc).__name__}"


def run_due(
    conn: sqlite3.Connection,
    rerun: Callable[[dict[str, Any]], dict[str, Any]],
    load_report: Callable[[int], dict[str, Any] | None],
    *,
    now: datetime | None = None,
) -> int:
    """Re-check every watch whose time has come. ``rerun(stored_report)`` returns the new
    report dict. Returns how many were finished (done or failed)."""
    now_ms = to_epoch_ms(now or utc_now())
    due = conn.execute("SELECT id, forecast_id, webhook, before FROM watches WHERE status='pending' AND due_at<=?", (now_ms,)).fetchall()
    for wid, fid, hook, before_json in due:
        after: dict[str, Any] | None = None
        err: str | None = None
        try:
            stored = load_report(fid)
            if stored is None:
                raise LookupError("the stored report is no longer kept")
            after = summarise(rerun(stored))
        except Exception as exc:  # noqa: BLE001 - one bad watch must not block the rest
            err = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("watch %s failed: %s", wid, err)
        hook_status = None
        if hook and after is not None:
            before = json.loads(before_json)
            hook_status = _notify(hook, {"watch_id": wid, "forecast_id": fid, "before": before, "after": after, "moved": _moved(before, after)})
        with conn:
            conn.execute(
                "UPDATE watches SET status=?, after=?, done_at=?, error=?, webhook_status=? WHERE id=?",
                ("done" if after is not None else "failed", json.dumps(after) if after else None, to_epoch_ms(utc_now()), err, hook_status, wid),
            )
    return len(due)


def make_rerun(ctx: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:  # noqa: ANN401
    """The re-check itself: rebuild the ticket, run the desk as of now, journal nothing."""
    from nightwatch.api.whatif import ticket_from
    from nightwatch.pipeline.analyze import analyze

    def rerun(stored: dict[str, Any]) -> dict[str, Any]:
        ticket = ticket_from(stored)
        if ticket is None:
            raise ValueError("the stored report has no ticket to re-run")
        return analyze(ctx, ticket, record=False).to_dict()

    return rerun
