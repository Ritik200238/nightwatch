"""The report's source list says how old each feed is in terms a reader can compare.

``last_ts`` is the newest data point, which for a calendar or a quiet ticker can be weeks
old while the feed is perfectly live. Each row therefore also says what ``last_ts`` is and
when the desk last pulled the feed.
"""

from datetime import datetime, timedelta

import pytest

from nightwatch.data.models import Venue
from nightwatch.data.store import Store
from nightwatch.pipeline.feeds import feed_sources
from nightwatch.time_utils import UTC

AS_OF = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


@pytest.fixture()
def store(tmp_path):  # noqa: ANN001, ANN201
    with Store(tmp_path / "f.sqlite") as s:
        yield s


def pulled(store: Store, task: str, ago: timedelta, venue: Venue | None = None) -> None:
    t = AS_OF - ago
    store.log_sync(task, venue=venue, started_at=t - timedelta(seconds=5), finished_at=t)


def rows(store: Store, at: datetime = AS_OF) -> dict[str, dict]:
    return {r["kind"]: r for r in feed_sources(store, ticker="TSLA", spot_symbol="RTSLAUSDT", perp_symbol="TSLAUSDT", yahoo_ticker="TSLA", as_of=at)}


def test_every_pulled_feed_says_when_it_was_last_pulled_and_what_its_date_means(store):  # noqa: ANN001
    pulled(store, "earnings_calendar", timedelta(hours=2))
    pulled(store, "macro_calendar", timedelta(hours=5))
    pulled(store, "macro_series", timedelta(hours=1))
    pulled(store, "news", timedelta(minutes=20))
    pulled(store, "filings", timedelta(hours=3))
    pulled(store, "corporate_events", timedelta(hours=9))
    pulled(store, "bars", timedelta(minutes=14), Venue.BITGET_SPOT)
    pulled(store, "bars", timedelta(minutes=14), Venue.BITGET_UMCBL)
    pulled(store, "bars", timedelta(hours=1), Venue.YAHOO)
    r = rows(store)

    def ago(kind: str) -> timedelta:
        return AS_OF - datetime.fromisoformat(r[kind]["checked_at"])

    assert ago("nasdaq_earnings") == timedelta(hours=2) and r["nasdaq_earnings"]["last_what"] == "row first seen"
    assert ago("fred_macro") == timedelta(hours=1), "the newer of its two pulls"
    assert r["fred_macro"]["last_what"] == "latest release already out"
    assert ago("rss_news") == timedelta(minutes=20) and r["rss_news"]["last_what"] == "newest headline"
    assert ago("sec_edgar") == timedelta(hours=3) and ago("corporate_events") == timedelta(hours=9)
    assert ago("bitget_candles") == timedelta(minutes=14) and ago("bitget_perp") == timedelta(minutes=14)
    assert ago("yahoo_bars") == timedelta(hours=1)


def test_a_feed_that_was_never_pulled_says_so_instead_of_borrowing_another_feeds_time(store):  # noqa: ANN001
    pulled(store, "news", timedelta(minutes=5))
    r = rows(store)
    assert r["rss_news"]["checked_at"] and r["nasdaq_earnings"]["checked_at"] is None
    assert r["bitget_candles"]["checked_at"] is None, "a Yahoo pull is not a Bitget pull"


def test_a_pull_after_the_moment_of_the_report_is_not_counted(store):  # noqa: ANN001
    pulled(store, "news", timedelta(hours=4))
    store.log_sync("news", started_at=AS_OF + timedelta(hours=1), finished_at=AS_OF + timedelta(hours=1, seconds=5))
    assert AS_OF - datetime.fromisoformat(rows(store)["rss_news"]["checked_at"]) == timedelta(hours=4)
