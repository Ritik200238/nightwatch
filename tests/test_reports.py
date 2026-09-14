"""Keeping a finished report: small, capped, and exactly what was argued."""

from __future__ import annotations

from nightwatch.data.store import Store
from nightwatch.journal.reports import ReportStore


def test_a_report_survives_the_round_trip(tmp_path):
    store = Store(tmp_path / "r.sqlite")
    rs = ReportStore(store)
    body = {"verdict": {"verdict": "GO"}, "snapshot": {"content_hash": "abc", "features": {"rv_24h": 0.2}}, "when": None}
    rs.save(1, body)
    assert rs.get(1) == body
    assert rs.get(2) is None
    store.close()


def test_saving_the_same_id_twice_replaces_it(tmp_path):
    store = Store(tmp_path / "r.sqlite")
    rs = ReportStore(store)
    rs.save(7, {"verdict": "GO"})
    rs.save(7, {"verdict": "NO_GO"})
    assert rs.get(7) == {"verdict": "NO_GO"} and rs.count() == 1
    store.close()


def test_only_the_most_recent_are_kept(tmp_path):
    """A demo box has 38 GB of disk. A report nobody has opened in a month is not worth it."""
    store = Store(tmp_path / "r.sqlite")
    rs = ReportStore(store)
    for i in range(1, 9):
        rs.save(i, {"n": i}, keep=5)
    assert rs.count() == 5
    assert rs.get(1) is None and rs.get(8) == {"n": 8}
    store.close()


def test_the_body_is_stored_compressed(tmp_path):
    store = Store(tmp_path / "r.sqlite")
    rs = ReportStore(store)
    # Report payloads are mostly repeated JSON keys; they should not be kept verbatim.
    body = {"rows": [{"ticker": "TSLA", "side": "long", "notional_quote": 20000.0} for _ in range(200)]}
    rs.save(1, body)
    raw = store._conn.execute("SELECT LENGTH(body) FROM reports WHERE forecast_id=1").fetchone()[0]
    import json

    assert raw < len(json.dumps(body)) / 4
    assert rs.get(1) == body
    store.close()
