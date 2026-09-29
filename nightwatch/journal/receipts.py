"""A receipt for every verdict, chained, so a past call cannot be quietly rewritten.

The scorecard is only worth something if the forecasts it scores are the ones that were
made. Each journaled forecast gets a receipt: a SHA-256 over the claim as it was written -
what was asked, what the desk said, the stated tails - and over the previous receipt.
Changing any recorded field of any forecast, or deleting one, breaks every receipt after
it, and ``verify`` finds the first break.

What a receipt covers is the claim, not the market's answer: the outcome is recomputed
from stored prices and is not something the desk writes an opinion into. The ``taken``
flag is left out because a trader may change it.

Only live verdicts (``kind = 'ticket'``) are chained. Replays are research rows, deleted
and rebuilt whenever the replay is re-run, and are checked a different way: anyone can
regenerate them from the code and the stored bars.

What it does not prove: the chain is kept by the same server that writes the forecasts,
so it shows nothing was altered *after* its receipt was written, not that the operator
could not have rebuilt the whole chain. Rows that existed before receipts did were chained
on 29 September 2026, when the table was created, and prove nothing before that date.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from nightwatch.time_utils import to_epoch_ms, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    forecast_id INTEGER PRIMARY KEY REFERENCES forecasts(id),
    seq INTEGER NOT NULL UNIQUE,
    prev TEXT NOT NULL,
    digest TEXT NOT NULL,
    chained_at INTEGER NOT NULL
);
"""

GENESIS = "0" * 64
KIND = "ticket"  # live verdicts; replays are regenerated, not chained
# The claim, as written. Everything the desk said about the trade, and the inputs hash
# that pins what it was looking at; not `taken`, which the trader may change later.
FIELDS = (
    "id", "created_at", "kind", "ticker", "side", "notional", "as_of", "bar_ts", "horizon_h", "horizon_end", "entry_price",
    "snapshot_hash", "analog_n", "analog_scope", "p5", "p25", "p50", "p75", "p95", "es5", "mc_p5", "mc_p95",
    "verdict", "recommended_notional",
)


def _canonical(row: dict[str, Any]) -> str:
    claim = {k: row.get(k) for k in FIELDS}
    claim["payload_sha256"] = hashlib.sha256((row.get("payload") or "").encode()).hexdigest()
    return json.dumps(claim, sort_keys=True, separators=(",", ":"), default=str)


def digest(prev: str, row: dict[str, Any]) -> str:
    return hashlib.sha256((prev + "\n" + _canonical(row)).encode()).hexdigest()


def _row(conn: sqlite3.Connection, forecast_id: int) -> dict[str, Any] | None:
    cur = conn.execute(f"SELECT {', '.join(FIELDS)}, payload FROM forecasts WHERE id=?", (forecast_id,))
    got = cur.fetchone()
    return dict(zip([*FIELDS, "payload"], got, strict=True)) if got else None


def _head(conn: sqlite3.Connection) -> tuple[int, str]:
    got = conn.execute("SELECT seq, digest FROM receipts ORDER BY seq DESC LIMIT 1").fetchone()
    return (int(got[0]), str(got[1])) if got else (0, GENESIS)


def append(conn: sqlite3.Connection, forecast_id: int) -> str:
    """Chain one forecast. Called inside the transaction that wrote it, so the receipt
    and the row it covers are committed together or not at all."""
    row = _row(conn, forecast_id)
    if row is None:
        raise KeyError(forecast_id)
    seq, prev = _head(conn)
    d = digest(prev, row)
    conn.execute("INSERT INTO receipts (forecast_id, seq, prev, digest, chained_at) VALUES (?,?,?,?,?)",
                 (forecast_id, seq + 1, prev, d, to_epoch_ms(utc_now())))
    return d


def chain_pending(conn: sqlite3.Connection) -> int:
    """Chain every forecast that has no receipt yet, oldest id first: rows written before
    receipts existed, or by a bulk import that bypassed the journal."""
    ids = [r[0] for r in conn.execute(
        f"SELECT f.id FROM forecasts f LEFT JOIN receipts r ON r.forecast_id=f.id WHERE r.forecast_id IS NULL AND f.kind='{KIND}' ORDER BY f.id")]
    with conn:
        for fid in ids:
            append(conn, fid)
    return len(ids)


def receipt(conn: sqlite3.Connection, forecast_id: int) -> dict[str, Any] | None:
    got = conn.execute("SELECT seq, prev, digest, chained_at FROM receipts WHERE forecast_id=?", (forecast_id,)).fetchone()
    if not got:
        return None
    return {"forecast_id": forecast_id, "seq": got[0], "prev": got[1], "digest": got[2], "chained_at": got[3]}


def verify(conn: sqlite3.Connection, *, upto: int | None = None) -> dict[str, Any]:
    """Recompute the chain from the first receipt and report the first break, if any.

    A break is a receipt whose digest no longer matches the row it covers (the row was
    changed), a receipt whose ``prev`` is not the one before it (the chain was cut or
    reordered), or a receipt whose forecast is gone (a row was deleted).
    """
    rows = conn.execute("SELECT r.seq, r.forecast_id, r.prev, r.digest, r.chained_at FROM receipts r ORDER BY r.seq").fetchall()
    prev, n, first_break, first_chained = GENESIS, 0, None, None
    for seq, fid, stored_prev, stored_digest, chained_at in rows:
        if upto is not None and seq > upto:
            break
        first_chained = first_chained if first_chained is not None else chained_at
        row = _row(conn, fid)
        reason = None
        if stored_prev != prev:
            reason = "the receipt does not follow the one before it"
        elif row is None:
            reason = "the forecast it covers has been deleted"
        elif digest(prev, row) != stored_digest:
            reason = "the forecast no longer matches its receipt"
        if reason:
            first_break = {"seq": seq, "forecast_id": fid, "reason": reason}
            break
        prev, n = stored_digest, n + 1
    unchained = conn.execute(f"SELECT COUNT(*) FROM forecasts f LEFT JOIN receipts r ON r.forecast_id=f.id WHERE r.forecast_id IS NULL AND f.kind='{KIND}'").fetchone()[0]
    return {
        "ok": first_break is None, "checked": n, "head": prev, "first_break": first_break,
        "unchained": int(unchained), "chained_since": first_chained,
    }
