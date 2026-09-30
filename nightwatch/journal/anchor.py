"""Anchor the receipt chain in Bitcoin, so it can be checked without trusting us.

The receipts (``journal.receipts``) show that no live verdict was changed after its
receipt was written. They are kept by the server that writes the verdicts, so on their
own they cannot rule out the operator rebuilding the whole chain. An outside timestamp
closes that gap: once a day the chain is verified, its head - the latest receipt and
its sequence number - is written to a small text file, and that file is timestamped with
OpenTimestamps. The proof is committed to a Bitcoin block within a few hours, and from
then on anyone can show the file existed by that block's time, using opentimestamps.org
or the `ots verify` command, with no account and nothing to trust but Bitcoin.

What that proves, precisely: every receipt up to that sequence number is fixed as of that
block. A verdict edited later breaks the chain against an anchored head, and ``/verify``
reports it. What it does not prove: anything about verdicts written after the latest
anchor, until the next one.

This runs in the recorder, never in a request: stamping talks to public calendar servers
and can take seconds. The API only reads the files it leaves behind.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from nightwatch.journal import receipts
from nightwatch.time_utils import ensure_utc, utc_now

log = logging.getLogger(__name__)

NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.txt(\.ots)?$")
TIMEOUT_S = 120


def _ots() -> str | None:
    return shutil.which("ots")


def _status_path(txt: Path) -> Path:
    return txt.with_name(txt.name + ".status.json")


def _read_head(txt: Path) -> dict[str, Any]:
    fields = dict(line.split(" ", 1) for line in txt.read_text(encoding="utf-8").splitlines() if " " in line)
    return {"seq": int(fields.get("seq", "0")), "head": fields.get("head", ""), "verified": fields.get("verified", "")}


def stamp(conn: sqlite3.Connection, directory: Path, *, now: datetime | None = None) -> Path | None:
    """Write and timestamp today's head, once a day. Returns the file, or None when there
    was nothing to do or the chain did not verify (a broken chain is never anchored)."""
    now = ensure_utc(now or utc_now())
    directory.mkdir(parents=True, exist_ok=True)
    txt = directory / f"{now:%Y-%m-%d}.txt"
    if txt.exists():
        return None
    check = receipts.verify(conn)
    if not check["ok"] or not check["checked"]:
        log.warning("not anchoring: chain %s", "broken" if not check["ok"] else "empty")
        return None
    txt.write_text(f"Nightwatch receipt chain\nseq {check['checked']}\nhead {check['head']}\nverified {now.isoformat()}\n", encoding="utf-8")
    ots = _ots()
    if ots is None:
        log.warning("ots is not installed; %s written but not timestamped", txt.name)
        return txt
    done = subprocess.run([ots, "stamp", str(txt)], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    if done.returncode != 0:
        log.warning("ots stamp failed: %s", (done.stderr or done.stdout)[-300:])
    _status_path(txt).write_text(json.dumps({"state": "pending", "checked_at": now.isoformat()}), encoding="utf-8")
    return txt


def upgrade(directory: Path, *, now: datetime | None = None) -> int:
    """Ask the calendars for the Bitcoin attestation of every proof still pending.
    Returns how many became complete."""
    ots = _ots()
    if ots is None or not directory.exists():
        return 0
    now = ensure_utc(now or utc_now())
    completed = 0
    for proof in sorted(directory.glob("*.txt.ots")):
        txt = proof.with_suffix("")
        status_file = _status_path(txt)
        status = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {"state": "pending"}
        if status.get("state") == "bitcoin":
            continue
        subprocess.run([ots, "upgrade", str(proof)], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
        info = subprocess.run([ots, "info", str(proof)], capture_output=True, text=True, timeout=TIMEOUT_S, check=False).stdout
        block = re.search(r"BitcoinBlockHeaderAttestation\((\d+)\)", info)
        if block:
            status = {"state": "bitcoin", "block": int(block.group(1)), "checked_at": now.isoformat()}
            completed += 1
        else:
            status = {**status, "state": "pending", "checked_at": now.isoformat()}
        status_file.write_text(json.dumps(status), encoding="utf-8")
    return completed


def tick(db_path: Path, directory: Path) -> None:
    """The recorder's hourly job: stamp today's head if not yet done, upgrade the rest.

    Runs on its own thread with its own connection: the calendars can take a minute to
    answer, and the recorder's loop takes an order-book snapshot every 30 seconds."""
    import threading

    def run() -> None:
        try:
            conn = sqlite3.connect(db_path, timeout=30)
            try:
                stamp(conn, directory)
                upgrade(directory)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 - anchoring must never stop the recorder
            log.exception("anchoring failed")

    if not any(t.name == "anchor-receipts" and t.is_alive() for t in threading.enumerate()):
        threading.Thread(target=run, name="anchor-receipts", daemon=True).start()


def listing(directory: Path) -> list[dict[str, Any]]:
    """Every anchor, newest first: what it fixes and whether Bitcoin has it yet."""
    out: list[dict[str, Any]] = []
    if not directory.exists():
        return out
    for txt in sorted(directory.glob("*.txt"), reverse=True):
        status_file = _status_path(txt)
        status = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {"state": "unstamped"}
        proof = txt.with_name(txt.name + ".ots")
        out.append({
            "name": txt.name, **_read_head(txt), **status,
            "proof": proof.name if proof.exists() else None,
        })
    return out


def consistent(conn: sqlite3.Connection, anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anchors whose head no longer matches the receipt at that sequence number: the chain
    was rebuilt after it was timestamped. Empty when every anchor still holds."""
    bad = []
    for a in anchors:
        got = conn.execute("SELECT digest FROM receipts WHERE seq=?", (a["seq"],)).fetchone()
        if got is None or got[0] != a["head"]:
            bad.append({"name": a["name"], "seq": a["seq"]})
    return bad
