"""Pruning old order books: the same rows go as before, found by id instead of a full
scan, in short batches, so the write lock is never held for the whole table."""

from __future__ import annotations

from datetime import datetime, timedelta

from nightwatch.data.store import Store
from nightwatch.time_utils import UTC, to_epoch_ms

T0 = datetime(2026, 6, 1, tzinfo=UTC)


def _books(store: Store, hours: list[int]) -> None:
    for h in hours:
        ts = to_epoch_ms(T0 + timedelta(hours=h))
        store._conn.execute(
            "INSERT INTO orderbook_snapshots (venue, symbol, ts, observed_at, levels) VALUES ('spot', 'RNVDAUSDT', ?, ?, '[]')", (ts, ts),
        )


def _left(store: Store) -> list[int]:
    return [int((r[0] - to_epoch_ms(T0)) / 3_600_000) for r in store._conn.execute("SELECT ts FROM orderbook_snapshots ORDER BY id").fetchall()]


def test_prunes_exactly_the_rows_before_the_cutoff_in_batches(tmp_path):
    store = Store(tmp_path / "nw.sqlite")
    _books(store, list(range(50)))
    assert store.prune_orderbooks_older_than(T0 + timedelta(hours=23), batch=7) == 23
    assert _left(store) == list(range(23, 50))


def test_nothing_older_means_no_delete_at_all(tmp_path):
    store = Store(tmp_path / "nw.sqlite")
    _books(store, [5, 6, 7])
    assert store.prune_orderbooks_older_than(T0) == 0
    assert _left(store) == [5, 6, 7]


def test_everything_older_and_an_empty_table(tmp_path):
    store = Store(tmp_path / "nw.sqlite")
    assert store.prune_orderbooks_older_than(T0) == 0
    _books(store, [1, 2, 3])
    assert store.prune_orderbooks_older_than(T0 + timedelta(days=1), batch=2) == 3
    assert _left(store) == []


def test_gaps_in_ids_and_a_row_out_of_time_order(tmp_path):
    store = Store(tmp_path / "nw.sqlite")
    _books(store, list(range(20)))
    store._conn.execute("DELETE FROM orderbook_snapshots WHERE id IN (3, 4, 5, 11, 12)")  # hours 2-4 and 10-11: gaps in ids
    _books(store, [2])  # a late row: newest id, old time - older than the cutoff, so it goes too
    got = store.prune_orderbooks_older_than(T0 + timedelta(hours=10), batch=3)
    assert got == 8  # hours 0, 1, 5, 6, 7, 8, 9 and the late 2
    assert _left(store) == [12, 13, 14, 15, 16, 17, 18, 19]


def test_a_row_out_of_time_order_is_never_deleted_when_newer_than_the_cutoff(tmp_path):
    store = Store(tmp_path / "nw.sqlite")
    _books(store, [0, 1, 40, 2, 3, 4, 50, 51])  # 40 recorded early: the binary search may stop before it
    store.prune_orderbooks_older_than(T0 + timedelta(hours=30), batch=2)
    assert {40, 50, 51} <= set(_left(store)) and not {0, 1} & set(_left(store))


def test_every_cutoff_matches_the_plain_delete(tmp_path):
    for cut in range(-1, 32):
        store = Store(tmp_path / f"nw{cut + 1}.sqlite")
        _books(store, [0, 0, 1, 3, 3, 3, 7, 8, 15, 15, 16, 23, 30])
        before = _left(store)
        n = store.prune_orderbooks_older_than(T0 + timedelta(hours=cut), batch=4)
        assert _left(store) == [h for h in before if h >= cut], cut
        assert n == len([h for h in before if h < cut])
        store.close()
