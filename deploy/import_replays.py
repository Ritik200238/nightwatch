"""Move re-scored replay forecasts from one database into another.

Replays are reproducible: they are what the engine would have said at past moments, so
when the engine changes they have to be rebuilt or the calibration page describes a
version that no longer exists. Rebuilding them takes about an hour of CPU, which is worth
spending on a workstation and not on the small box that is serving the live demo.

So: rebuild locally, extract the three tables that hold them, copy that across, and merge
it in here. Ids are reassigned on insert, because the target has its own live tickets
whose ids would otherwise collide, and the outcomes and lessons follow their forecast.

    # on the workstation
    python deploy/import_replays.py --extract data/nightwatch.sqlite replays.sqlite
    scp replays.sqlite ubuntu@<ip>:/tmp/

    # on the box
    docker compose run --rm -v /tmp:/src api python -m deploy.import_replays --merge /src/replays.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

TABLES = ("forecasts", "forecast_outcomes", "lessons")


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def extract(source: Path, dest: Path) -> int:
    """Copy every replay forecast, with its outcome and lesson, into a small new file."""
    if dest.exists():
        dest.unlink()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    out = sqlite3.connect(dest)
    for table in TABLES:
        ddl = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if ddl is None:
            continue
        # No foreign keys in the extract: it is a transport format, not a database.
        out.execute(ddl[0].replace(" REFERENCES forecasts(id)", ""))

    ids = [r[0] for r in src.execute("SELECT id FROM forecasts WHERE kind='replay'").fetchall()]
    if not ids:
        print("no replay forecasts to extract")
        return 0
    marks = ",".join("?" * len(ids))
    for table, where in (("forecasts", f"id IN ({marks})"), ("forecast_outcomes", f"forecast_id IN ({marks})"), ("lessons", f"forecast_id IN ({marks})")):
        cols = _columns(src, table)
        if not cols:
            continue
        rows = src.execute(f"SELECT * FROM {table} WHERE {where}", ids).fetchall()
        out.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", rows)
        print(f"  {table}: {len(rows)} rows")
    out.commit()
    out.close()
    src.close()
    print(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return len(ids)


def merge(incoming: Path, target: Path) -> int:
    """Replace the target's replay forecasts with the ones in ``incoming``."""
    src = sqlite3.connect(f"file:{incoming}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    dst.execute("PRAGMA foreign_keys=ON")

    old = [r[0] for r in dst.execute("SELECT id FROM forecasts WHERE kind='replay'").fetchall()]
    if old:
        marks = ",".join("?" * len(old))
        for table in ("forecast_outcomes", "lessons"):
            if dst.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                dst.execute(f"DELETE FROM {table} WHERE forecast_id IN ({marks})", old)
        dst.execute(f"UPDATE trade_log SET forecast_id=NULL WHERE forecast_id IN ({marks})", old)
        dst.execute(f"DELETE FROM forecasts WHERE id IN ({marks})", old)
        print(f"removed {len(old)} replay forecasts already here")

    f_cols = [c for c in _columns(src, "forecasts") if c in _columns(dst, "forecasts")]
    insert_cols = [c for c in f_cols if c != "id"]
    o_cols = [c for c in _columns(src, "forecast_outcomes") if c in _columns(dst, "forecast_outcomes")]
    l_cols = [c for c in _columns(src, "lessons") if c in _columns(dst, "lessons")] if dst.execute("SELECT 1 FROM sqlite_master WHERE name='lessons'").fetchone() else []

    n = 0
    for row in src.execute(f"SELECT {','.join(f_cols)} FROM forecasts").fetchall():
        record = dict(zip(f_cols, row, strict=True))
        old_id = record["id"]
        cur = dst.execute(
            f"INSERT INTO forecasts ({','.join(insert_cols)}) VALUES ({','.join('?' * len(insert_cols))})",
            [record[c] for c in insert_cols],
        )
        new_id = cur.lastrowid
        for table, cols in (("forecast_outcomes", o_cols), ("lessons", l_cols)):
            if not cols:
                continue
            for sub in src.execute(f"SELECT {','.join(cols)} FROM {table} WHERE forecast_id=?", (old_id,)).fetchall():
                values = dict(zip(cols, sub, strict=True))
                values["forecast_id"] = new_id
                dst.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [values[c] for c in cols])
        n += 1
    dst.commit()
    print(f"merged {n} replay forecasts")
    dst.close()
    src.close()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extract", nargs=2, metavar=("SOURCE", "DEST"), help="pull replay rows out of a database")
    ap.add_argument("--merge", metavar="INCOMING", help="merge an extract into the live database")
    ap.add_argument("--target", default="/data/nightwatch.sqlite", help="database to merge into")
    args = ap.parse_args()
    if args.extract:
        return 0 if extract(Path(args.extract[0]), Path(args.extract[1])) else 1
    if args.merge:
        return 0 if merge(Path(args.merge), Path(args.target)) else 1
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
