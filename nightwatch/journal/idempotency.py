"""One answer per send: a chat request id makes a retry return the first answer, not run the trade again.

Why: the web client asks ``/chat/stream`` and, when the stream cannot start or is cut before
its first step, asks plain ``/chat`` with the same message. The server does not cancel the
first request when its client goes away: the worker thread waits for the analysis lock, runs
the analysis and journals it. So a stream that was cut while its turn was still queued is
answered twice, and the same trade is scored and chained twice - a duplicate row in a record
that is shown, counted and audited.

The client now sends one ``request_id`` per user send, the same one on the stream and on its
retry. The first request to arrive claims it (an atomic insert on the primary key, so it
holds across threads, connections and restarts); a second request with the same id waits for
that run and returns its stored answer instead of analysing again.

What is stored: the finished answer, compressed, for one hour, and nothing else about the
visitor - the id is a random string the browser made for this one message. A claim that
never finishes (the process was killed) is taken over after ``STALE_PENDING_S`` and is
cleared when the API starts.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import zlib
from dataclasses import dataclass
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_requests (
    request_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,          -- 'pending' while the first request runs, 'done' once answered
    claimed_at INTEGER NOT NULL,  -- epoch ms
    result BLOB                   -- zlib-compressed JSON of the answer, once done
);
CREATE INDEX IF NOT EXISTS chat_requests_claimed ON chat_requests (claimed_at);
"""

KEEP_S = 3600.0  # an answer is replayable for an hour
STALE_PENDING_S = 180.0  # longer than any request the proxy lets live (115 s), so the owner is gone
WAIT_S = 100.0  # how long a retry waits for the first run before saying it is still running
POLL_S = 0.25

ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def valid(request_id: str | None) -> bool:
    return bool(request_id) and ID.match(request_id or "") is not None


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class Claim:
    owner: bool  # this request is the one that runs
    result: dict[str, Any] | None = None  # the first run's answer, when it has finished
    running: bool = False  # another request holds the claim and has not finished


def claim(conn: sqlite3.Connection, request_id: str, now_ms: int | None = None) -> Claim:
    """Become the run for ``request_id``, or learn what the run that holds it has done."""
    now = _now_ms() if now_ms is None else now_ms
    with conn:
        conn.execute("DELETE FROM chat_requests WHERE claimed_at < ?", (now - int(KEEP_S * 1000),))
        won = conn.execute(
            "INSERT OR IGNORE INTO chat_requests (request_id, state, claimed_at) VALUES (?, 'pending', ?)", (request_id, now)
        ).rowcount == 1
    if won:
        return Claim(owner=True)
    row = conn.execute("SELECT state, claimed_at, result FROM chat_requests WHERE request_id=?", (request_id,)).fetchone()
    if row is None:  # released between the insert and the read: the next claim will win it
        return Claim(owner=False, running=True)
    state, claimed_at, blob = row[0], int(row[1]), row[2]
    if state == "done" and blob is not None:
        return Claim(owner=False, result=json.loads(zlib.decompress(blob)))
    if now - claimed_at > int(STALE_PENDING_S * 1000):
        # The run that claimed it is gone. Exactly one caller gets to take it over.
        with conn:
            took = conn.execute(
                "UPDATE chat_requests SET claimed_at=? WHERE request_id=? AND state='pending' AND claimed_at=?",
                (now, request_id, claimed_at),
            ).rowcount == 1
        if took:
            return Claim(owner=True)
    return Claim(owner=False, running=True)


def finish(conn: sqlite3.Connection, request_id: str, answer: dict[str, Any]) -> None:
    """Store the finished answer for a retry. Never raises: a failed store only means a retry
    would run again, which is how it was before ids existed."""
    try:
        blob = zlib.compress(json.dumps(answer, default=str, separators=(",", ":")).encode(), 6)
        with conn:
            conn.execute("UPDATE chat_requests SET state='done', result=? WHERE request_id=?", (blob, request_id))
    except Exception:  # noqa: BLE001
        abandon(conn, request_id)


def abandon(conn: sqlite3.Connection, request_id: str) -> None:
    """Release a claim whose run failed, so a retry can run instead of waiting on nothing."""
    try:
        with conn:
            conn.execute("DELETE FROM chat_requests WHERE request_id=? AND state='pending'", (request_id,))
    except Exception:  # noqa: BLE001
        pass


def clear_pending(conn: sqlite3.Connection) -> int:
    """At start-up: every claim still pending belongs to a process that no longer exists."""
    with conn:
        return conn.execute("DELETE FROM chat_requests WHERE state='pending'").rowcount


def wait(conn: sqlite3.Connection, request_id: str, timeout_s: float = WAIT_S, poll_s: float = POLL_S) -> Claim:
    """Wait for the run that holds ``request_id``. Returns its answer; or ``Claim(owner=True)``
    when that run failed or went stale and this caller now owns it; or ``running`` on timeout."""
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        got = claim(conn, request_id)
        if got.owner or got.result is not None:
            return got
        if time.monotonic() >= deadline:
            return got
        time.sleep(poll_s)
