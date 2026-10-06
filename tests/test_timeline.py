"""The market-clock timeline around a hold."""

from datetime import UTC, datetime, timedelta

from nightwatch.decision.timeline import build


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_friday_evening_hold_runs_over_the_weekend_to_monday_open():
    # Fri 2026-03-06 22:00 UTC = 17:00 ET (EST): the session just closed.
    tl = build(_dt("2026-03-06T22:00:00"), 60)
    assert tl["market_open_at_as_of"] is False
    assert tl["next_open"] == "2026-03-09T13:30:00+00:00"  # Monday 09:30 EDT (DST began Mar 8)
    assert tl["hold_end"] == "2026-03-09T10:00:00+00:00"
    assert tl["sessions"][0]["close"] == "2026-03-06T21:00:00+00:00"


def test_inside_a_session_it_is_open_and_next_open_is_tomorrow():
    tl = build(_dt("2026-03-10T15:00:00"), 6)  # Tue 11:00 EDT
    assert tl["market_open_at_as_of"] is True
    assert tl["sessions"][0]["open"] == "2026-03-10T13:30:00+00:00"
    assert tl["next_open"] == "2026-03-11T13:30:00+00:00"


def test_holiday_is_skipped_and_early_close_respected():
    # Good Friday 2026-04-03 is shut: from Thursday evening the next open is Monday.
    tl = build(_dt("2026-04-02T22:00:00"), 24)
    assert tl["next_open"] == "2026-04-06T13:30:00+00:00"
    # Day after Thanksgiving closes at 13:00 ET.
    tl = build(_dt("2026-11-27T15:00:00"), 2)
    assert tl["sessions"][0]["close"] == "2026-11-27T18:00:00+00:00"


def test_sessions_cover_the_hold_and_beyond():
    t = _dt("2026-03-10T15:00:00")
    tl = build(t, 72)
    last_open = datetime.fromisoformat(tl["sessions"][-1]["open"])
    assert last_open >= t + timedelta(hours=72)


def test_scheduled_weekend_asked_midweek_is_one_closed_window_from_fridays_close():
    from types import SimpleNamespace

    from nightwatch.pipeline.analyze import _hold_start
    from nightwatch.stress.scenarios import closed_windows_in_hold

    tue = _dt("2026-03-10T15:00:00")  # Tue 11:00 EDT
    ticket = SimpleNamespace(extra={"horizon_label": "the coming weekend, Friday's close to Monday's open"})
    start = _hold_start(ticket, tue)
    assert start == _dt("2026-03-13T20:00:00").replace(tzinfo=UTC)  # Fri 16:00 EDT
    # From now a 65.5 h hold would span three nights; from Friday's close it is the one weekend.
    assert closed_windows_in_hold(tue, 65.5) == 3
    assert closed_windows_in_hold(start, 65.5) == 1
    tl = build(tue, 65.5, hold_start=start)
    assert tl["hold_start"] == start.isoformat()
    assert tl["as_of"] == tue.isoformat()
    assert datetime.fromisoformat(tl["hold_end"]) == start + timedelta(hours=65.5)


def test_a_plain_hold_starts_now():
    from types import SimpleNamespace

    from nightwatch.pipeline.analyze import _hold_start

    tue = _dt("2026-03-10T15:00:00").replace(tzinfo=UTC)
    assert _hold_start(SimpleNamespace(extra={}), tue) == tue
    assert "hold_start" not in build(tue, 6)
