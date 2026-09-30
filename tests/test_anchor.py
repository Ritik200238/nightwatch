"""Anchoring the receipt chain: what is written, when it is refused, what breaks it."""

from datetime import UTC, datetime

from nightwatch.journal import anchor, receipts
from tests.test_receipts import _record, journal  # noqa: F401 - fixture

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def test_the_head_is_written_once_a_day_and_matches_the_chain(journal, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(anchor, "_ots", lambda: None)  # no calendar in a test
    for n in range(3):
        _record(journal, n)
    txt = anchor.stamp(journal._conn, tmp_path, now=NOW)
    assert txt is not None and txt.name == "2026-09-29.txt"
    head = receipts.verify(journal._conn)["head"]
    listed = anchor.listing(tmp_path)
    assert listed[0]["seq"] == 3 and listed[0]["head"] == head
    assert anchor.stamp(journal._conn, tmp_path, now=NOW) is None  # once a day
    assert anchor.consistent(journal._conn, listed) == []


def test_a_broken_chain_is_never_anchored(journal, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(anchor, "_ots", lambda: None)
    ids = [_record(journal, n) for n in range(3)]
    with journal._conn:
        journal._conn.execute("UPDATE forecasts SET verdict='NO_GO' WHERE id=?", (ids[1],))
    assert anchor.stamp(journal._conn, tmp_path, now=NOW) is None
    assert not list(tmp_path.glob("*.txt"))


def test_a_chain_rebuilt_after_its_anchor_is_caught(journal, tmp_path, monkeypatch):  # noqa: F811
    """Recomputing every link after an edit makes the chain verify again; the anchored
    head is what still disagrees."""
    monkeypatch.setattr(anchor, "_ots", lambda: None)
    ids = [_record(journal, n) for n in range(3)]
    anchor.stamp(journal._conn, tmp_path, now=NOW)
    with journal._conn:
        journal._conn.execute("UPDATE forecasts SET verdict='NO_GO' WHERE id=?", (ids[1],))
        journal._conn.execute("DELETE FROM receipts")
    receipts.chain_pending(journal._conn)
    assert receipts.verify(journal._conn)["ok"]  # the rebuilt chain is self-consistent...
    assert anchor.consistent(journal._conn, anchor.listing(tmp_path)) == [{"name": "2026-09-29.txt", "seq": 3}]  # ...but not with the anchor


def test_only_anchor_file_names_are_served():
    assert anchor.NAME.match("2026-09-29.txt") and anchor.NAME.match("2026-09-29.txt.ots")
    assert not anchor.NAME.match("../nightwatch.sqlite") and not anchor.NAME.match("2026-09-29.txt.status.json")
