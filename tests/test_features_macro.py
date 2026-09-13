"""Macro columns: published-not-observed, ranked within their own history."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from nightwatch.data.models import MacroRelease
from nightwatch.data.store import Store
from nightwatch.features.macro import MACRO_COLUMNS, build_macro_frame, macro_label

START = datetime(2025, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "m.sqlite")
    rows = []
    for i in range(420):  # a bit over a year of daily values
        day = START + timedelta(days=i)
        rows.append(MacroRelease(series_id="VIXCLS", release_ts=day, name="VIX", value=10.0 + i * 0.1, period=None, source="test", observed_at=day))
        rows.append(MacroRelease(series_id="T10Y2Y", release_ts=day, name="curve", value=0.5, period=None, source="test", observed_at=day))
        rows.append(MacroRelease(series_id="DTWEXBGS", release_ts=day, name="dollar", value=100.0 + i * 0.05, period=None, source="test", observed_at=day))
        rows.append(MacroRelease(series_id="DGS10", release_ts=day, name="10y", value=4.0 + i * 0.001, period=None, source="test", observed_at=day))
    s.upsert_macro(rows)
    yield s
    s.close()


def hourly(days: int, start: datetime = START) -> pd.DatetimeIndex:
    return pd.date_range(start, start + timedelta(days=days), freq="1h", tz="UTC")


def test_every_column_is_produced_and_named(store):
    m = build_macro_frame(store, hourly(300))
    assert list(m.columns) == list(MACRO_COLUMNS)
    assert m["vix_pctl_1y"].notna().any()


def test_a_value_is_not_usable_on_its_own_day(store):
    """The VIX rises every day here, so leaking today's value would show up immediately."""
    idx = hourly(200)
    m = build_macro_frame(store, idx)
    # At midday on day 100 the newest usable value is the one dated day 99.
    at = pd.Timestamp(START + timedelta(days=100, hours=12))
    rank_now = m.loc[at, "vix_pctl_1y"]
    rank_next = m.loc[at + pd.Timedelta(days=1), "vix_pctl_1y"]
    assert rank_now <= rank_next  # never ahead of itself
    early = build_macro_frame(store, hourly(1))
    assert early["vix_pctl_1y"].isna().all()  # day one cannot know day one


def test_a_rising_series_ends_at_the_top_of_its_own_range(store):
    m = build_macro_frame(store, hourly(400))
    assert m["vix_pctl_1y"].iloc[-1] == pytest.approx(100.0)
    assert m["dollar_20d_chg_pct"].iloc[-1] > 0  # twenty days of increases


def test_a_flat_series_sits_at_the_top_because_nothing_exceeds_it(store):
    m = build_macro_frame(store, hourly(300))
    assert m["curve_pctl_1y"].dropna().between(99.9, 100.0).all()


def test_labels_read_like_english():
    assert macro_label(pd.Series({"vix_pctl_1y": 90.0})) == "stressed"
    assert macro_label(pd.Series({"vix_pctl_1y": 65.0})) == "tightening"
    assert macro_label(pd.Series({"vix_pctl_1y": 40.0, "ten_year_20d_chg_bps": 40.0})) == "tightening"
    assert macro_label(pd.Series({"vix_pctl_1y": 10.0})) == "calm"
    assert macro_label(pd.Series({"vix_pctl_1y": 40.0})) == "ordinary"
    assert macro_label(pd.Series({"vix_pctl_1y": None})) == "unknown"


def test_an_empty_store_yields_empty_columns_not_an_error(tmp_path):
    with Store(tmp_path / "empty.sqlite") as s:
        m = build_macro_frame(s, hourly(30))
        assert list(m.columns) == list(MACRO_COLUMNS) and m.isna().all().all()
