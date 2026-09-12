from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nightwatch.time_utils import (
    ET,
    HourOfWeekBucket,
    Session,
    classify_session,
    closed_window_bounds,
    floor_to_interval,
    hour_of_week_bucket,
    is_early_close,
    is_trading_day,
    next_trading_day,
    nyse_early_closes,
    nyse_holidays,
    previous_trading_day,
)

UTC = UTC


def et(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# --- holiday calendar --------------------------------------------------------------


def test_2026_full_holiday_set():
    assert nyse_holidays(2026) == frozenset(
        {
            date(2026, 1, 1),  # New Year's Day (Thu)
            date(2026, 1, 19),  # MLK
            date(2026, 2, 16),  # Presidents'
            date(2026, 4, 3),  # Good Friday (Easter Apr 5)
            date(2026, 5, 25),  # Memorial
            date(2026, 6, 19),  # Juneteenth (Fri)
            date(2026, 7, 3),  # Independence Day observed (Jul 4 is Sat)
            date(2026, 9, 7),  # Labor Day
            date(2026, 11, 26),  # Thanksgiving
            date(2026, 12, 25),  # Christmas (Fri)
        }
    )


def test_2025_includes_special_closure_and_sunday_rules():
    h = nyse_holidays(2025)
    assert date(2025, 1, 9) in h  # national day of mourning
    assert date(2025, 4, 18) in h  # Good Friday
    assert date(2025, 7, 4) in h
    assert date(2025, 12, 25) in h


def test_new_year_on_saturday_is_not_observed_on_friday():
    # 2028-01-01 is a Saturday: NYSE does not close Fri 2027-12-31.
    assert date(2027, 12, 31) not in nyse_holidays(2027)
    assert date(2028, 1, 1) not in nyse_holidays(2028)
    assert is_trading_day(date(2027, 12, 31))


def test_sunday_holiday_observed_monday():
    # Christmas 2022 was a Sunday -> observed Monday Dec 26.
    assert date(2022, 12, 26) in nyse_holidays(2022)


def test_early_closes_2026():
    assert nyse_early_closes(2026) == frozenset({date(2026, 11, 27), date(2026, 12, 24)})
    # Jul 3 2026 is itself the observed holiday, so it is NOT an early close.
    assert not is_early_close(date(2026, 7, 3))


def test_early_close_jul3_when_weekday_and_not_holiday():
    assert date(2025, 7, 3) in nyse_early_closes(2025)


def test_trading_day_navigation_over_holiday_weekend():
    # Fri 2026-09-04 -> Mon 09-07 is Labor Day -> next trading day Tue 09-08.
    assert next_trading_day(date(2026, 9, 4)) == date(2026, 9, 8)
    assert previous_trading_day(date(2026, 9, 8)) == date(2026, 9, 4)


# --- session classification --------------------------------------------------------


@pytest.mark.parametrize(
    "ts, expected",
    [
        (et(2026, 9, 10, 3, 59), Session.NIGHT),
        (et(2026, 9, 10, 4, 0), Session.PRE),
        (et(2026, 9, 10, 9, 29), Session.PRE),
        (et(2026, 9, 10, 9, 30), Session.REGULAR),
        (et(2026, 9, 10, 15, 59), Session.REGULAR),
        (et(2026, 9, 10, 16, 0), Session.POST),
        (et(2026, 9, 10, 19, 59), Session.POST),
        (et(2026, 9, 10, 20, 0), Session.NIGHT),
        (et(2026, 9, 12, 12, 0), Session.WEEKEND),
        (et(2026, 9, 13, 23, 0), Session.WEEKEND),
        (et(2026, 9, 7, 12, 0), Session.HOLIDAY),  # Labor Day
        (et(2026, 11, 27, 12, 59), Session.REGULAR),  # early close day
        (et(2026, 11, 27, 13, 0), Session.POST),
        (et(2026, 11, 27, 17, 0), Session.NIGHT),
    ],
)
def test_session_boundaries(ts, expected):
    assert classify_session(ts).session == expected


def test_closed_window_spans_whole_weekend_and_holiday():
    # Fri 2026-09-04 16:00 ET close -> Tue 2026-09-08 09:30 ET open (Labor Day Monday).
    sat = et(2026, 9, 5, 15, 0)
    close, open_ = closed_window_bounds(sat)
    assert close == et(2026, 9, 4, 16, 0).astimezone(UTC)
    assert open_ == et(2026, 9, 8, 9, 30).astimezone(UTC)
    info = classify_session(sat)
    assert info.is_closed
    assert info.seconds_since_close == (sat - close).total_seconds()
    assert info.seconds_until_open == (open_ - sat).total_seconds()
    # Same window id for any instant inside the stretch.
    assert classify_session(et(2026, 9, 7, 3, 0)).closed_window_id == info.closed_window_id


def test_regular_session_has_no_closed_window():
    ts = et(2026, 9, 10, 12, 0)
    assert closed_window_bounds(ts) is None
    info = classify_session(ts)
    assert info.seconds_since_close == 0 and info.seconds_until_open == 0
    assert info.closed_window_id is None


def test_pre_session_bounds_point_to_previous_close_and_todays_open():
    ts = et(2026, 9, 10, 5, 0)
    info = classify_session(ts)
    assert info.regular_close_utc == et(2026, 9, 9, 16, 0).astimezone(UTC)
    assert info.regular_open_utc == et(2026, 9, 10, 9, 30).astimezone(UTC)


def test_dst_transition_keeps_et_wall_clock():
    # 2026-03-08 is the US spring-forward Sunday; Monday open must still be 09:30 ET.
    info = classify_session(et(2026, 3, 8, 12, 0))
    assert info.regular_open_utc == et(2026, 3, 9, 9, 30).astimezone(UTC)
    assert info.regular_open_utc.astimezone(ZoneInfo("America/New_York")).hour == 9


# --- hour-of-week buckets ----------------------------------------------------------


@pytest.mark.parametrize(
    "ts, bucket",
    [
        (et(2026, 9, 10, 12, 0), HourOfWeekBucket.US_REGULAR),
        (et(2026, 9, 10, 5, 0), HourOfWeekBucket.US_PRE),
        (et(2026, 9, 10, 17, 0), HourOfWeekBucket.US_POST),
        (et(2026, 9, 10, 22, 0), HourOfWeekBucket.WEEKNIGHT),
        (et(2026, 9, 11, 21, 0), HourOfWeekBucket.FRIDAY_NIGHT),
        (et(2026, 9, 12, 10, 0), HourOfWeekBucket.WEEKEND),
        (et(2026, 9, 13, 21, 0), HourOfWeekBucket.SUNDAY_NIGHT),
        (et(2026, 9, 7, 10, 0), HourOfWeekBucket.HOLIDAY),
    ],
)
def test_hour_of_week_bucket(ts, bucket):
    assert hour_of_week_bucket(ts) == bucket


# --- helpers ----------------------------------------------------------------------


def test_floor_to_interval():
    ts = datetime(2026, 9, 10, 13, 47, 12, tzinfo=UTC)
    assert floor_to_interval(ts, timedelta(hours=1)) == datetime(2026, 9, 10, 13, tzinfo=UTC)
    assert floor_to_interval(ts, timedelta(minutes=5)) == datetime(2026, 9, 10, 13, 45, tzinfo=UTC)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        classify_session(datetime(2026, 9, 10, 12, 0))
