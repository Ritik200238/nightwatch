"""A hold said to end "tomorrow" ends on the next day's session, never this morning's.

The finding that started this: "Long NVDA overnight into tomorrow's US open, 10k", typed on a
Friday before the open, was answered as "held for 0.8 h" - the open that was fifty minutes
away - because the rules read "overnight" as "to the next open" and the next open, before
9:30, is today's. "Tomorrow" names another day, so the hold must end on it.

What is pinned here is the one correction and, as importantly, everything that must not move:
"overnight" and "tonight" mean the next open as before, an explicit length wins, the weekend
words keep their own rule, and between midnight and the pre-market the word is left alone
because a person awake then often means "later today".
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nightwatch.analog.outcomes import structural_horizons
from nightwatch.api import intake, intake_zh
from nightwatch.api.llm import ParsedIntent, chat_turn
from tests.test_llm import FakeClient, state  # noqa: F401 - fixture
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - the fixture the state fixture needs

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
TICKERS = ["TSLA", "NVDA", "AAPL"]


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# 2026-10-06 is a Tuesday, 2026-10-09 a Friday, 2026-10-10 a Saturday, 2026-10-11 a Sunday.
TUE_PRE, TUE_DAY, TUE_POST, TUE_NIGHT = at(2026, 10, 6, 8, 40), at(2026, 10, 6, 11), at(2026, 10, 6, 17), at(2026, 10, 6, 23, 30)
FRI_PRE, FRI_DAY, FRI_POST = at(2026, 10, 9, 8, 40), at(2026, 10, 9, 11), at(2026, 10, 9, 17)
SAT, SUN_NIGHT = at(2026, 10, 10, 12), at(2026, 10, 11, 20)


@pytest.fixture
def clock(monkeypatch):
    """Pin the wall clock the parser reads; returns a setter."""
    holder = {"now": TUE_DAY}
    monkeypatch.setattr("nightwatch.time_utils.utc_now", lambda: holder["now"].astimezone(UTC))

    def set_now(when: datetime) -> None:
        holder["now"] = when

    return set_now


def read(text: str):
    return intake.read_conversation([{"role": "user", "content": text}], TICKERS, None)


# --- the helper ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "now, hours",
    [
        (TUE_PRE, 24.83),    # this morning's open is 50 minutes away; tomorrow's is Wednesday 09:30
        (TUE_DAY, 22.5),     # already tomorrow's: unchanged from "the next open"
        (TUE_POST, 16.5),
        (TUE_NIGHT, 10.0),
        (FRI_PRE, 72.83),    # Friday before the open: Monday's open, not today's
        (FRI_DAY, 70.5),
        (FRI_POST, 64.5),
        (SAT, 45.5),
        (SUN_NIGHT, 13.5),
    ],
)
def test_tomorrows_open_is_the_first_trading_days_open_after_today(now, hours):
    assert intake.hours_until_tomorrow("open", now) == pytest.approx(hours, abs=0.01)


@pytest.mark.parametrize("now", [TUE_DAY, TUE_POST, TUE_NIGHT, FRI_DAY, FRI_POST, SAT, SUN_NIGHT])
def test_whenever_the_next_open_already_is_tomorrows_the_two_agree(now):
    got = intake.hours_until_tomorrow("open", now)
    assert got == pytest.approx(structural_horizons(now.astimezone(UTC))["next_open"], abs=0.01)


def test_the_hours_are_the_difference_of_real_instants_across_a_clock_change():
    # US clocks go back on Sunday 1 Nov 2026 (02:00 EDT -> 01:00 EST): the weekend is an hour longer.
    assert intake.hours_until_tomorrow("open", at(2026, 10, 30, 8, 40)) == pytest.approx(73.83, abs=0.01)
    # ...and forward on Sunday 8 Mar 2026: an hour shorter.
    assert intake.hours_until_tomorrow("open", at(2026, 3, 6, 8, 40)) == pytest.approx(71.83, abs=0.01)


def test_a_holiday_tomorrow_moves_it_to_the_next_session_and_an_early_close_is_honoured():
    # Thanksgiving, Thursday 26 Nov 2026: closed. Friday 27 Nov is an early close at 13:00.
    wed = at(2026, 11, 25, 8, 40)
    assert intake.hours_until_tomorrow("open", wed) == pytest.approx(48.83, abs=0.01)  # Friday 09:30
    assert intake.hours_until_tomorrow("close", at(2026, 11, 25, 11)) == pytest.approx(50.0, abs=0.01)  # Friday 13:00


def test_tomorrows_close_is_never_todays():
    assert intake.hours_until_tomorrow("close", TUE_DAY) == pytest.approx(29.0, abs=0.01)  # Wednesday 16:00
    assert intake.hours_until_tomorrow("close", TUE_PRE) == pytest.approx(31.33, abs=0.01)
    assert intake.hours_until_tomorrow("close", FRI_DAY) == pytest.approx(77.0, abs=0.01)  # Monday 16:00


def test_between_midnight_and_the_pre_market_the_word_is_not_applied():
    # 01:00 on a Wednesday: "tomorrow" is ambiguous (later today, or Thursday). Not guessed.
    assert intake.hours_until_tomorrow("open", at(2026, 10, 7, 1, 0)) is None
    assert intake.hours_until_tomorrow("open", at(2026, 10, 7, 3, 59)) is None
    assert intake.hours_until_tomorrow("open", at(2026, 10, 7, 4, 0)) == pytest.approx(29.5, abs=0.01)  # Thursday 09:30


# --- the parser: what changes ---------------------------------------------------------------


def test_the_reported_sentence_on_a_friday_before_the_open_runs_to_monday(clock):
    clock(FRI_PRE)
    p = read("Long NVDA overnight into tomorrow's US open, 10k")
    assert p.horizon_kind == "hours"
    assert p.horizon_hours == pytest.approx(72.83, abs=0.01)


@pytest.mark.parametrize(
    "text",
    [
        "Long NVDA 10k until tomorrow",
        "long NVDA 10k till tomorrow's open",
        "long NVDA 10k into tomorrow's open",
        "long NVDA 10k to tomorrow's US open",
        "long NVDA 10k for tomorrow's open",
        "Long NVDA overnight into tomorrow's US open, 10k",
    ],
)
def test_every_way_of_naming_tomorrows_open_runs_to_the_next_days_open(clock, text):
    clock(TUE_PRE)
    p = read(text)
    assert (p.horizon_kind, round(p.horizon_hours, 2)) == ("hours", 24.83)


def test_tomorrows_close_is_read_as_a_close(clock):
    clock(TUE_DAY)
    p = read("long NVDA 10k until tomorrow's close")
    assert (p.horizon_kind, round(p.horizon_hours, 2)) == ("hours", 29.0)


# --- the parser: what must not change -----------------------------------------------------------


def test_in_session_and_after_hours_tomorrows_open_is_the_next_open_exactly_as_before(clock):
    for now in (TUE_DAY, TUE_POST, TUE_NIGHT, FRI_DAY, FRI_POST, SAT, SUN_NIGHT):
        clock(now)
        p = read("Long NVDA overnight into tomorrow's US open, 10k")
        assert (p.horizon_kind, p.horizon_hours) == ("next_open", None), now


def test_overnight_and_tonight_before_the_open_are_left_as_they_were(clock):
    """Said at 08:40, "overnight" is ambiguous (this morning's open, or tonight's hold). It is
    documented, not guessed: the kind stays next_open."""
    clock(FRI_PRE)
    for text in ("long NVDA 10k overnight", "long NVDA 10k tonight", "long NVDA 10k until the open", "long NVDA 10k"):
        p = read(text)
        assert p.horizon_kind in ("next_open", None) and p.horizon_hours is None, text


def test_an_explicit_length_wins_over_tomorrow(clock):
    clock(FRI_PRE)
    p = read("long NVDA 10k for 8 hours, until tomorrow")
    assert (p.horizon_kind, p.horizon_hours) == ("hours", 8.0)
    p = read("long NVDA 10k for 2 days into tomorrow's open")
    assert (p.horizon_kind, p.horizon_hours) == ("hours", 48.0)


def test_the_weekend_and_named_day_words_keep_their_own_rule(clock):
    clock(TUE_PRE)
    assert read("long NVDA 10k over the weekend, flat tomorrow").horizon_kind == "through_weekend"
    p = read("long NVDA 10k until Thursday, not tomorrow")
    assert p.horizon_kind == "hours" and p.horizon_hours == pytest.approx(48.83, abs=0.01)  # Thursday 09:30, from Tue 08:40


def test_a_message_that_only_mentions_tomorrow_in_passing_is_not_a_horizon(clock):
    clock(FRI_PRE)
    for text in ("long NVDA 10k, earnings are tomorrow", "long NVDA 10k, I'm away tomorrow"):
        p = read(text)
        assert p.horizon_kind in ("next_open", None) and p.horizon_hours is None, text


def test_between_midnight_and_the_pre_market_tomorrow_is_left_alone(clock):
    clock(at(2026, 10, 7, 1, 0))
    p = read("long NVDA 10k into tomorrow's open")
    assert p.horizon_kind in ("next_open", None) and p.horizon_hours is None


# --- Chinese --------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["做多英伟达 1万U 到明天开盘", "做多英伟达 1万U，持有到明日开盘", "做多英伟达 1万U 拿到明天美股开盘"])
def test_chinese_tomorrows_open_before_the_open(clock, text):
    clock(FRI_PRE)
    p = read(text)
    assert p.ticker == "NVDA" and p.horizon_kind == "hours"
    assert p.horizon_hours == pytest.approx(72.83, abs=0.01)


def test_chinese_tomorrows_close_and_the_unchanged_words(clock):
    clock(TUE_DAY)
    p = read("做多英伟达 1万U 到明天收盘")
    assert (p.horizon_kind, round(p.horizon_hours, 2)) == ("hours", 29.0)
    clock(FRI_PRE)
    p = read("做多英伟达 1万U 过夜")
    assert (p.horizon_kind, p.horizon_hours) == ("next_open", None)
    p = read("做多英伟达 1万U 3小时 到明天开盘")
    assert (p.horizon_kind, p.horizon_hours) == ("hours", 3.0), "an explicit length wins"
    p = read("做多英伟达 1万U，明天有财报")
    assert p.horizon_kind in ("next_open", None) and p.horizon_hours is None, "a passing mention is not a horizon"
    assert intake_zh.read("做多英伟达 1万U 到明天开盘", {"NVDA"})["horizon_kind"] == "hours"


# --- the model path ---------------------------------------------------------------------------------


def test_when_the_model_reads_the_message_tomorrow_still_means_tomorrow(clock, state, monkeypatch):  # noqa: F811
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    """A message asking to narrow the history goes to the model, which says next_open for
    "into tomorrow's open". Said before the open, that is the open fifty minutes away: the
    rules' calendar reading of "tomorrow" is kept."""
    clock(FRI_PRE)
    intent = ParsedIntent(kind="analyze", ticker="TSLA", side="long", notional_quote=20_000.0, horizon_kind="next_open", lenses=["earnings_soon"], reply="ok")
    text = "long 20k TSLA into tomorrow's open, only earnings nights"
    out = chat_turn(state, [{"role": "user", "content": text}], account_equity=200_000.0, client=FakeClient(intent))
    assert out["parsed_by"] != "rules", "this one went to the model"
    assert out["ticket"]["horizon_kind"] == "hours"
    assert out["ticket"]["horizon_hours"] == pytest.approx(72.83, abs=0.01)


def test_the_model_path_leaves_an_ordinary_next_open_alone(clock, state, monkeypatch):  # noqa: F811
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    clock(FRI_PRE)
    intent = ParsedIntent(kind="analyze", ticker="TSLA", side="long", notional_quote=20_000.0, horizon_kind="next_open", lenses=["earnings_soon"], reply="ok")
    out = chat_turn(state, [{"role": "user", "content": "long 20k TSLA overnight, only earnings nights"}], account_equity=200_000.0, client=FakeClient(intent))
    assert out["ticket"]["horizon_kind"] == "next_open"
