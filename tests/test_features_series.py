from datetime import UTC, datetime, timedelta

import numpy as np

from nightwatch.data.models import Bar, Interval, PriceKind, Venue
from nightwatch.data.store import Store
from nightwatch.features.basis import add_basis_columns, basis_by_bucket, closed_vs_open_ratio
from nightwatch.features.series import SeriesSpec, completed_before, load_aligned_hourly

UTC = UTC
# Wed 2026-09-09 00:00 UTC .. Mon 2026-09-14 00:00 UTC covers weekdays, a Friday night and a whole weekend.
START = datetime(2026, 9, 9, tzinfo=UTC)
END = datetime(2026, 9, 14, tzinfo=UTC)
SPEC = SeriesSpec("TSLA", "RTSLAUSDT", "TSLAUSDT", "TSLA")


def bars(venue, symbol, kind, hours, price_fn, *, skip=()):
    out = []
    for h in hours:
        if h in skip:
            continue
        ts = START + timedelta(hours=h)
        p = price_fn(h)
        out.append(Bar(venue=venue, symbol=symbol, interval=Interval.H1, kind=kind, ts=ts, open=p, high=p * 1.001, low=p * 0.999, close=p, volume_quote=1000.0, observed_at=START))
    return out


def seed(store: Store):
    hours = range(0, 120)
    store.upsert_bars(bars(Venue.BITGET_SPOT, "RTSLAUSDT", PriceKind.TRADE, hours, lambda h: 100.0 + 0.01 * h, skip={5, 6, 50}))
    store.upsert_bars(bars(Venue.BITGET_UMCBL, "TSLAUSDT", PriceKind.TRADE, hours, lambda h: 100.0))
    store.upsert_bars(bars(Venue.BITGET_UMCBL, "TSLAUSDT", PriceKind.INDEX, hours, lambda h: 100.0))
    store.upsert_bars(bars(Venue.BITGET_UMCBL, "TSLAUSDT", PriceKind.MARK, hours, lambda h: 100.0))
    # Native bars only during regular session, starting at :30 like Yahoo: Wed & Thu & Fri 13:30..19:30 UTC.
    native = []
    for day in (0, 1, 2):
        for k in range(7):
            ts = START + timedelta(days=day, hours=13, minutes=30) + timedelta(hours=k)
            native.append(Bar(venue=Venue.YAHOO, symbol="TSLA", interval=Interval.H1, ts=ts, open=90, high=91, low=89, close=90.0 + day, observed_at=START))
    store.upsert_bars(native)


def test_alignment_fill_flags_and_native_carry(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        seed(s)
        f = load_aligned_hourly(s, SPEC, START, END)
    assert len(f) == 120 and f.index[0] == START
    # Missing spot hours are forward-filled and flagged; volume zeroed.
    assert f["spot_filled"].sum() == 3
    assert f.loc[START + timedelta(hours=5), "spot_close"] == f.loc[START + timedelta(hours=4), "spot_close"]
    assert f.loc[START + timedelta(hours=5), "spot_vol_quote"] == 0.0
    assert not f["perp_filled"].any()
    # Native: first Yahoo bar starts 13:30 UTC on day 0 -> known at 15:00 grid point; before that NaN.
    assert np.isnan(f.loc[START + timedelta(hours=14), "native_close"])
    assert f.loc[START + timedelta(hours=15), "native_close"] == 90.0
    assert f.loc[START + timedelta(hours=15), "native_close_age_h"] == 0.0
    # Sunday 12:00 UTC: carried from Friday's last bar (close 92, known Fri 21:00), age 39h.
    sunday = START + timedelta(days=4, hours=12)
    assert f.loc[sunday, "native_close"] == 92.0
    assert f.loc[sunday, "native_close_age_h"] > 24
    assert f.loc[sunday, "session"] == "weekend" and f.loc[sunday, "is_closed"]
    # Wednesday 15:00 UTC = 11:00 ET regular session.
    assert f.loc[START + timedelta(hours=15), "session"] == "regular"


def test_completed_before_excludes_open_bar(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        seed(s)
        f = load_aligned_hourly(s, SPEC, START, END)
    as_of = START + timedelta(hours=10, minutes=30)
    c = completed_before(f, as_of)
    assert c.index[-1] == START + timedelta(hours=9)  # bar 10:00-11:00 not yet closed


def test_basis_columns_and_closed_ratio(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        seed(s)
        f = add_basis_columns(load_aligned_hourly(s, SPEC, START, END))
    # spot drifts +1bp/hour above index (100 + 0.01h vs 100) => basis_index ≈ h bps.
    assert abs(f.loc[START + timedelta(hours=40), "basis_index_bps"] - 40.0) < 1e-6
    assert f["basis_index_z"].notna().sum() > 0
    table = basis_by_bucket(f, "basis_index_bps")
    assert {"weekend", "us_regular"} <= set(table.index)
    ratio = closed_vs_open_ratio(f, "basis_index_bps")
    assert ratio is not None and ratio > 1.0  # basis keeps growing into the weekend in this synthetic series


def test_no_perp_spec_yields_nan_perp_columns(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        seed(s)
        f = load_aligned_hourly(s, SeriesSpec("TSLA", "RTSLAUSDT", None, "TSLA"), START, END)
    assert f["perp_close"].isna().all() and f["index_close"].isna().all()
    f = add_basis_columns(f)
    assert f["basis_perp_bps"].isna().all()
