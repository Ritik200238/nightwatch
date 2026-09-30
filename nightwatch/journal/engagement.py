"""Product evidence: did anyone use the desk, and did it help them.

Everything here is about the desk's visitors, so the rule is to keep as little of them
as possible. No IP address and no browser id is ever written down: a visitor is a salted
SHA-256 of the anonymous random id their browser made (or, if the browser sent none, of
the address the request came from). The salt is ``NIGHTWATCH_SALT``; without it a random
one is made per process, which still separates visitors within a run but makes the same
person look new after a restart, so ``usage`` says whether the salt is stable.

Requests that carry ``x-nw-internal: 1`` (or ``?nw_internal=1``) are the operator's own
testing. They are kept out of every count so the numbers are not flattered by us.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from nightwatch.time_utils import from_epoch_ms, to_epoch_ms, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    forecast_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    useful INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    lang TEXT NOT NULL DEFAULT 'en',
    client TEXT NOT NULL,          -- salted hash, never an address
    internal INTEGER NOT NULL DEFAULT 0,
    UNIQUE (forecast_id, client)
);
CREATE INDEX IF NOT EXISTS feedback_client_time ON feedback (client, created_at);

CREATE TABLE IF NOT EXISTS verdict_marks (
    forecast_id INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL,
    lang TEXT NOT NULL DEFAULT 'en',
    client TEXT NOT NULL,
    internal INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chat_counts (
    day TEXT NOT NULL,
    lang TEXT NOT NULL,
    kind TEXT NOT NULL,
    n INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, lang, kind)
);
"""

NOTE_MAX = 500
FEEDBACK_PER_HOUR = 10
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_RANDOM_SALT = secrets.token_hex(16)


def salt() -> str:
    return os.environ.get("NIGHTWATCH_SALT") or _RANDOM_SALT


def salt_is_stable() -> bool:
    return bool(os.environ.get("NIGHTWATCH_SALT"))


def hash_client(browser_id: str | None, address: str | None) -> str:
    """A visitor as a salted hash. The browser's random id wins; the address is only a
    fallback for callers that send none, and is hashed here and never kept."""
    if browser_id and _ID.match(browser_id):
        raw = "id:" + browser_id
    else:
        raw = "ip:" + (address or "unknown")
    return hashlib.sha256((salt() + "\n" + raw).encode()).hexdigest()[:32]


def clean_note(text: str | None) -> str:
    """Strip links and addresses: a visitor's contact details are not something this
    table should ever hold, and a note is shown to other people."""
    t = _CTRL.sub(" ", text or "")
    t = _EMAIL.sub("[removed]", _URL.sub("[removed]", t))
    return re.sub(r"\s+", " ", t).strip()[:NOTE_MAX]


def norm_lang(lang: str | None) -> str:
    return "zh" if (lang or "").lower().startswith("zh") else "en"


def _now_ms() -> int:
    return to_epoch_ms(utc_now())


class RateLimited(Exception):
    pass


class Duplicate(Exception):
    pass


def add_feedback(conn: sqlite3.Connection, *, forecast_id: int, useful: bool, note: str, lang: str, client: str, internal: bool) -> None:
    since = _now_ms() - int(timedelta(hours=1).total_seconds() * 1000)
    n = conn.execute("SELECT COUNT(*) FROM feedback WHERE client=? AND created_at>=?", (client, since)).fetchone()[0]
    if n >= FEEDBACK_PER_HOUR:
        raise RateLimited
    try:
        with conn:
            conn.execute(
                "INSERT INTO feedback (forecast_id, created_at, useful, note, lang, client, internal) VALUES (?,?,?,?,?,?,?)",
                (int(forecast_id), _now_ms(), 1 if useful else 0, clean_note(note), norm_lang(lang), client, 1 if internal else 0),
            )
    except sqlite3.IntegrityError as exc:
        raise Duplicate from exc


def mark_verdict(conn: sqlite3.Connection, forecast_id: int, *, lang: str, client: str, internal: bool) -> None:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO verdict_marks (forecast_id, created_at, lang, client, internal) VALUES (?,?,?,?,?)",
            (int(forecast_id), _now_ms(), norm_lang(lang), client, 1 if internal else 0),
        )


def count_chat(conn: sqlite3.Connection, *, kind: str, lang: str) -> None:
    day = utc_now().strftime("%Y-%m-%d")
    with conn:
        conn.execute(
            "INSERT INTO chat_counts (day, lang, kind, n) VALUES (?,?,?,1) ON CONFLICT(day, lang, kind) DO UPDATE SET n = n + 1",
            (day, norm_lang(lang), (kind or "other")[:40]),
        )


def usage(conn: sqlite3.Connection) -> dict[str, Any]:
    def q(sql: str) -> list[tuple]:
        return conn.execute(sql).fetchall()

    marks = "FROM verdict_marks WHERE internal=0"
    fb = "FROM feedback WHERE internal=0"
    starts = [r[0] for r in (q("SELECT MIN(created_at) FROM verdict_marks"), q("SELECT MIN(created_at) FROM feedback")) if r[0][0] is not None]
    since = min(s[0] for s in starts) if starts else None
    notes = q(f"SELECT created_at, useful, note, lang {fb} AND note<>'' ORDER BY created_at DESC LIMIT 10")
    return {
        "counted_since": from_epoch_ms(since).isoformat() if since else None,
        "live_verdicts": q(f"SELECT COUNT(*) {marks}")[0][0],
        "journal_live_verdicts_all_time": q("SELECT COUNT(*) FROM forecasts WHERE kind='ticket'")[0][0],
        "distinct_anonymous_clients": q(f"SELECT COUNT(DISTINCT client) {marks}")[0][0],
        "clients_stable_across_restarts": salt_is_stable(),
        "by_language": {r[0]: r[1] for r in q(f"SELECT lang, COUNT(*) {marks} GROUP BY lang")},
        "feedback": {"useful": q(f"SELECT COUNT(*) {fb} AND useful=1")[0][0], "not_useful": q(f"SELECT COUNT(*) {fb} AND useful=0")[0][0]},
        "last_notes": [
            # Stripped again on the way out, so a row written by an older build stays clean.
            {"at": from_epoch_ms(r[0]).isoformat(), "useful": bool(r[1]), "note": clean_note(r[2]), "lang": r[3]}
            for r in notes
        ],
        "follow_ups_by_answer_kind": {r[0]: r[1] for r in q("SELECT kind, SUM(n) FROM chat_counts GROUP BY kind ORDER BY SUM(n) DESC")},
        "note": "No accounts. Only a salted hash of an anonymous random id from the visitor's browser is kept. "
        "Requests marked x-nw-internal: 1 are excluded.",
    }
