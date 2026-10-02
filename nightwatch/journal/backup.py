"""Nightly copy of the live database, safe to take while the recorder and API write.

sqlite3's online backup API copies a consistent snapshot without stopping writers (a plain
file copy of a WAL database can be torn). The copy is gzipped and only the newest few are
kept. It runs on its own thread so the recorder loop never waits on it.
"""

from __future__ import annotations

import gzip
import logging
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from nightwatch.time_utils import UTC

log = logging.getLogger(__name__)

PREFIX = "nightwatch-"
KEEP = 7
_running = threading.Lock()


def newest_age_s(backup_dir: Path) -> float | None:
    files = list(backup_dir.glob(f"{PREFIX}*.sqlite.gz"))
    return time.time() - max(f.stat().st_mtime for f in files) if files else None


def backup_now(db_path: Path, backup_dir: Path, *, keep: int = KEEP, today: datetime | None = None) -> Path:
    """Back up ``db_path`` to ``backup_dir/nightwatch-YYYYMMDD.sqlite.gz`` and prune."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (today or datetime.now(UTC)).strftime("%Y%m%d")
    raw = backup_dir / f"{PREFIX}{stamp}.sqlite"
    gz = backup_dir / f"{raw.name}.gz"
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
        try:
            dst = sqlite3.connect(raw)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        tmp = gz.with_suffix(".gz.part")
        with raw.open("rb") as f_in, gzip.open(tmp, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        tmp.replace(gz)
    finally:
        raw.unlink(missing_ok=True)
    for old in sorted(backup_dir.glob(f"{PREFIX}*.sqlite.gz"))[:-keep]:
        old.unlink(missing_ok=True)
    log.info("database backup %s: %.1f MB", gz.name, gz.stat().st_size / 1e6)
    return gz


def backup_in_background(db_path: Path, backup_dir: Path) -> None:
    """Start a backup on a thread and return at once; one at a time, failures logged."""
    if not _running.acquire(blocking=False):
        return

    def run() -> None:
        try:
            backup_now(db_path, backup_dir)
        except Exception as exc:  # noqa: BLE001 - a failed backup must never touch the recorder
            log.warning("database backup failed: %s", exc)
        finally:
            _running.release()

    threading.Thread(target=run, name="db-backup", daemon=True).start()
