"""Move re-scored replay forecasts, and the studies built on them, into the live database.

Replays are reproducible: they are what the engine would have said at past moments, so
when the engine changes they have to be rebuilt or the calibration page describes a
version that no longer exists. Rebuilding them takes about an hour of CPU, which is worth
spending on a workstation and not on the small box that is serving the live demo.

The studies have exactly the same shape - half of them need a match-level sweep of the
whole universe, which is twenty minutes the demo box should not spend - so they travel
in the same file. They are copied wholesale rather than merged row by row, because a
study is a statement about one engine against one history: a half-updated set would be
the one thing worse than none.

So: rebuild locally, extract, copy across, merge. Forecast ids are reassigned on insert,
because the target has its own live tickets whose ids would otherwise collide, and the
outcomes and lessons follow their forecast.

    # on the workstation
    python -m nightwatch.cli replay --tickers ... && python -m nightwatch.cli studies
    python deploy/import_replays.py --extract data/nightwatch.sqlite replays.sqlite
    scp replays.sqlite ubuntu@<ip>:/tmp/

    # on the box
    docker compose run --rm -v /tmp:/src api python -m deploy.import_replays --merge /src/replays.sqlite

When only the studies have been rerun - the usual case, because they are recomputed on
every engine change while the replays behind them sit still - ``--studies-only`` moves
those across and leaves the forecasts alone, rather than deleting and reinserting a few
thousand of them under new ids to achieve nothing.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

TABLES = ("forecasts", "forecast_outcomes", "lessons", "studies", "filing_reads", "filing_label_stats")


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
    _copy_studies(src, out)
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


# Tables that travel whole rather than row by row. A study is a statement about one
# engine measured against one history; a filing read cost real tokens and is keyed to
# text that does not change. In both cases a half-updated set is worse than none,
# because nothing in it announces which half is stale.
WHOLESALE = ("studies", "filing_reads", "filing_label_stats")


def _copy_wholesale(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    """Replace the destination's copies of the wholesale tables with the source's."""
    moved = 0
    for table in WHOLESALE:
        ddl = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if ddl is None:
            continue
        rows = src.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608 - name from a fixed tuple
        if not rows:
            continue
        dst.execute(ddl[0].replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS "))
        dst.execute(f"DELETE FROM {table}")  # noqa: S608
        cols = _columns(src, table)
        dst.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", rows)  # noqa: S608
        print(f"  {table}: {len(rows)} rows")
        moved += len(rows)
    return moved


def _copy_studies(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    """Kept as the name the rest of this file calls; the set it moves has grown."""
    return _copy_wholesale(src, dst)


def merge(incoming: Path, target: Path) -> int:
    """Replace the target's replay forecasts with the ones in ``incoming``."""
    src = sqlite3.connect(f"file:{incoming}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    dst.execute("PRAGMA foreign_keys=ON")

    _copy_studies(src, dst)
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


def merge_studies_only(incoming: Path, target: Path) -> int:
    """Move the studies across and leave the forecasts alone.

    The usual case once the box is in sync: the studies are recomputed whenever the
    engine changes, the replays behind them have not moved, and a full merge would
    delete and reinsert a few thousand forecasts under new ids to achieve nothing.
    """
    src = sqlite3.connect(f"file:{incoming}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    n = _copy_wholesale(src, dst)
    dst.commit()
    dst.close()
    src.close()
    print(f"copied {n} rows" if n else "nothing to copy in the extract")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extract", nargs=2, metavar=("SOURCE", "DEST"), help="pull replay rows and studies out of a database")
    ap.add_argument("--merge", metavar="INCOMING", help="merge an extract into the live database")
    ap.add_argument("--studies-only", metavar="INCOMING", help="copy the studies and filing reads across, leaving the forecasts untouched")
    ap.add_argument("--target", default="/data/nightwatch.sqlite", help="database to merge into")
    args = ap.parse_args()
    if args.extract:
        return 0 if extract(Path(args.extract[0]), Path(args.extract[1])) else 1
    if args.merge:
        return 0 if merge(Path(args.merge), Path(args.target)) else 1
    if args.studies_only:
        return 0 if merge_studies_only(Path(args.studies_only), Path(args.target)) else 1
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
