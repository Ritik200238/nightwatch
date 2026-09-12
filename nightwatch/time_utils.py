"""Time, US equity market calendar, and session classification.

Everything downstream (features, analog search, stress presets) depends on knowing,
for any instant, whether the *underlying* US market is open, and if not, how long it
has been shut and when it reopens. Getting this wrong silently corrupts every
"closed-market" statistic, so this module is deliberately explicit and fully tested.

Conventions
-----------
* All timestamps handed around the codebase are timezone-aware ``datetime`` in UTC.
* Market rules are evaluated in ``America/New_York`` (ET) after conversion.
* Holiday rules follow the NYSE calendar (observed-day rules included) plus an
  override list for one-off closures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np

UTC = timezone.utc
ET = ZoneInfo("America/New_York")

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
PRE_OPEN = time(4, 0)
POST_CLOSE = time(20, 0)
POST_CLOSE_EARLY = time(17, 0)  # after a 13:00 close the post session ends at 17:00

# One-off full closures not derivable from rules (national days of mourning etc.).
# Extend as needed; dates are ET calendar dates.
SPECIAL_CLOSURES: frozenset[date] = frozenset(
    {
        date(2025, 1, 9),  # National day of mourning, President Carter
    }
)


class Session(str, Enum):
    """Where the underlying US equity market is at a given instant."""

    PRE = "pre"  # 04:00–09:30 ET on a trading day
    REGULAR = "regular"  # 09:30–16:00 ET (or 09:30–13:00 on early-close days)
    POST = "post"  # 16:00–20:00 ET (13:00–17:00 on early-close days)
    NIGHT = "night"  # trading-day evening/early morning outside pre/post
    WEEKEND = "weekend"  # Saturday / Sunday ET
    HOLIDAY = "holiday"  # weekday full-day market holiday


CLOSED_SESSIONS = frozenset({Session.NIGHT, Session.WEEKEND, Session.HOLIDAY})


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def ensure_utc(ts: datetime) -> datetime:
    """Return ``ts`` as an aware UTC datetime; reject naive input loudly."""
    if ts.tzinfo is None:
        raise ValueError("naive datetime passed where an aware UTC datetime is required")
    return ts.astimezone(UTC)


def from_epoch_ms(ms: int | str | float) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC)


def to_epoch_ms(ts: datetime) -> int:
    return int(ensure_utc(ts).timestamp() * 1000)


def index_epoch_ns(index) -> "np.ndarray":  # noqa: ANN001
    """Epoch nanoseconds (int64) for a tz-aware DatetimeIndex, independent of the
    index's stored resolution (pandas ≥ 3 defaults to microseconds, so ``asi8`` must
    not be assumed to be nanoseconds)."""
    return index.tz_convert("UTC").as_unit("ns").asi8.astype("int64")


def floor_to_interval(ts: datetime, interval: timedelta) -> datetime:
    """Floor an aware datetime to a multiple of ``interval`` since the Unix epoch."""
    ts = ensure_utc(ts)
    seconds = int(interval.total_seconds())
    if seconds <= 0:
        raise ValueError("interval must be positive")
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)


# --------------------------------------------------------------------------------------
# Holiday calendar
# --------------------------------------------------------------------------------------


def _easter_sunday(year: int) -> date:
    """Gregorian Easter (Anonymous / Meeus-Jones-Butcher algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    length = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * length) // 451
    month, day = divmod(h + length - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) given weekday (Mon=0) of a month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month // 12), (month % 12) + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date, *, saturday_to_friday: bool = True) -> date | None:
    """NYSE observed-day rule: Sunday → Monday; Saturday → Friday (except when the
    Friday would be in the previous year, i.e. New Year's Day, which is not observed)."""
    if d.weekday() == 6:
        return d + timedelta(days=1)
    if d.weekday() == 5:
        if not saturday_to_friday:
            return None
        return d - timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def nyse_holidays(year: int) -> frozenset[date]:
    """Full-day NYSE closures for ``year`` (observed dates)."""
    days: set[date] = set()

    new_year = _observed(date(year, 1, 1), saturday_to_friday=False)
    if new_year is not None:
        days.add(new_year)
    days.add(_nth_weekday(year, 1, 0, 3))  # Martin Luther King Jr. Day
    days.add(_nth_weekday(year, 2, 0, 3))  # Presidents' Day
    days.add(_easter_sunday(year) - timedelta(days=2))  # Good Friday
    days.add(_last_weekday(year, 5, 0))  # Memorial Day
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))  # Juneteenth
    days.add(_observed(date(year, 7, 4)))  # Independence Day
    days.add(_nth_weekday(year, 9, 0, 1))  # Labor Day
    days.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving
    days.add(_observed(date(year, 12, 25)))  # Christmas
    # New Year's Day of *next* year observed on Dec 31 never happens (rule 7.2),
    # so nothing to add for the year boundary.

    days.update(d for d in SPECIAL_CLOSURES if d.year == year)
    return frozenset(days)


@lru_cache(maxsize=64)
def nyse_early_closes(year: int) -> frozenset[date]:
    """Days the regular session ends at 13:00 ET."""
    days: set[date] = set()
    holidays = nyse_holidays(year)

    day_after_thanksgiving = _nth_weekday(year, 11, 3, 4) + timedelta(days=1)
    days.add(day_after_thanksgiving)

    jul3 = date(year, 7, 3)
    if jul3.weekday() < 5 and jul3 not in holidays:
        days.add(jul3)

    dec24 = date(year, 12, 24)
    if dec24.weekday() < 5 and dec24 not in holidays:
        days.add(dec24)

    return frozenset(days)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def is_early_close(d: date) -> bool:
    return is_trading_day(d) and d in nyse_early_closes(d.year)


def next_trading_day(d: date) -> date:
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def previous_trading_day(d: date) -> date:
    d = d - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


# --------------------------------------------------------------------------------------
# Session classification
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionInfo:
    """Where the US market is at ``ts`` and the surrounding regular-session bounds."""

    ts_utc: datetime
    session: Session
    et_date: date
    is_closed: bool
    regular_open_utc: datetime  # regular open of the current-or-next trading day
    regular_close_utc: datetime  # regular close of the current-or-previous trading day
    seconds_since_close: float  # 0 while regular session is open
    seconds_until_open: float  # 0 while regular session is open
    closed_window_id: str | None  # stable id for the contiguous closed stretch


def _regular_bounds(d: date) -> tuple[datetime, datetime]:
    close_t = EARLY_CLOSE if is_early_close(d) else REGULAR_CLOSE
    open_utc = datetime.combine(d, REGULAR_OPEN, tzinfo=ET).astimezone(UTC)
    close_utc = datetime.combine(d, close_t, tzinfo=ET).astimezone(UTC)
    return open_utc, close_utc


def classify_session(ts: datetime) -> SessionInfo:
    """Classify an instant against the NYSE calendar.

    The closed-window id lets callers group every observation between one regular
    close and the next regular open, which is exactly the unit the product reasons
    about ("what happened during *this* weekend / *this* night").
    """
    return _classify_session_cached(ensure_utc(ts))


@lru_cache(maxsize=400_000)
def _classify_session_cached(ts: datetime) -> SessionInfo:
    # Feature frames classify every hour of every ticker; the calendar answer for a
    # given instant never changes, so it is memoised across tickers and calls.
    et = ts.astimezone(ET)
    d = et.date()
    t = et.time()

    if not is_trading_day(d):
        session = Session.WEEKEND if d.weekday() >= 5 else Session.HOLIDAY
    else:
        close_t = EARLY_CLOSE if is_early_close(d) else REGULAR_CLOSE
        post_end = POST_CLOSE_EARLY if is_early_close(d) else POST_CLOSE
        if PRE_OPEN <= t < REGULAR_OPEN:
            session = Session.PRE
        elif REGULAR_OPEN <= t < close_t:
            session = Session.REGULAR
        elif close_t <= t < post_end:
            session = Session.POST
        else:
            session = Session.NIGHT

    # Surrounding regular-session bounds.
    if is_trading_day(d):
        open_today, close_today = _regular_bounds(d)
        if ts < open_today:
            prev_d = previous_trading_day(d)
            _, prev_close = _regular_bounds(prev_d)
            regular_open, regular_close = open_today, prev_close
        elif ts < close_today:
            regular_open, regular_close = open_today, close_today
        else:
            nxt = next_trading_day(d)
            nxt_open, _ = _regular_bounds(nxt)
            regular_open, regular_close = nxt_open, close_today
    else:
        prev_d = previous_trading_day(d)
        nxt_d = next_trading_day(d)
        _, regular_close = _regular_bounds(prev_d)
        regular_open, _ = _regular_bounds(nxt_d)

    in_regular = session == Session.REGULAR
    since_close = 0.0 if in_regular else max(0.0, (ts - regular_close).total_seconds())
    until_open = 0.0 if in_regular else max(0.0, (regular_open - ts).total_seconds())

    closed_window_id = None
    if not in_regular:
        closed_window_id = f"{regular_close.isoformat()}|{regular_open.isoformat()}"

    return SessionInfo(
        ts_utc=ts,
        session=session,
        et_date=d,
        is_closed=not in_regular,
        regular_open_utc=regular_open,
        regular_close_utc=regular_close,
        seconds_since_close=since_close,
        seconds_until_open=until_open,
        closed_window_id=closed_window_id,
    )


class HourOfWeekBucket(str, Enum):
    """Coarse bucket used as an analog-search feature and for cohort splits.

    Bucket boundaries are chosen so that each captures a qualitatively different
    liquidity/information regime for a 24/7 token whose underlying is a US stock.
    """

    US_REGULAR = "us_regular"
    US_PRE = "us_pre"
    US_POST = "us_post"
    WEEKNIGHT = "weeknight"  # Mon–Thu night ET after post session, before next pre
    FRIDAY_NIGHT = "friday_night"  # Fri 20:00 ET → Sat 00:00 ET
    WEEKEND = "weekend"  # Saturday + Sunday ET
    SUNDAY_NIGHT = "sunday_night"  # kept for clarity: Sunday 20:00 ET → Monday 04:00 ET
    HOLIDAY = "holiday"


def hour_of_week_bucket(ts: datetime) -> HourOfWeekBucket:
    info = classify_session(ts)
    et = info.ts_utc.astimezone(ET)
    wd = et.weekday()
    match info.session:
        case Session.REGULAR:
            return HourOfWeekBucket.US_REGULAR
        case Session.PRE:
            return HourOfWeekBucket.US_PRE
        case Session.POST:
            return HourOfWeekBucket.US_POST
        case Session.HOLIDAY:
            return HourOfWeekBucket.HOLIDAY
        case Session.WEEKEND:
            if wd == 6 and et.time() >= POST_CLOSE:
                return HourOfWeekBucket.SUNDAY_NIGHT
            return HourOfWeekBucket.WEEKEND
        case Session.NIGHT:
            if wd == 4 and et.time() >= POST_CLOSE:
                return HourOfWeekBucket.FRIDAY_NIGHT
            return HourOfWeekBucket.WEEKNIGHT
    raise AssertionError("unreachable")  # pragma: no cover


def closed_window_bounds(ts: datetime) -> tuple[datetime, datetime] | None:
    """(regular_close, next_regular_open) of the closed stretch containing ``ts``,
    or ``None`` if the regular session is open."""
    info = classify_session(ts)
    if not info.is_closed:
        return None
    return info.regular_close_utc, info.regular_open_utc
