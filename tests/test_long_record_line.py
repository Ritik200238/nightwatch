from datetime import UTC, datetime
from types import SimpleNamespace

from nightwatch.api.intake import long_record_line
from nightwatch.stress.scenarios import Side


def _report(side=Side.LONG, as_of=datetime(2026, 10, 7, 20, tzinfo=UTC), hours=60.0, ticker="NVDA"):
    return SimpleNamespace(ticket=SimpleNamespace(ticker=ticker, side=side), as_of=as_of, horizon_h=hours)


def test_weekend_hold_quotes_the_weekend_record():
    en = long_record_line(_report(), "en")
    assert en and "weekends" in en and "since 1999" in en and "does not change the verdict" in en
    zh = long_record_line(_report(), "zh")
    assert zh and "周末" in zh


def test_midweek_night_uses_overnight_record():
    en = long_record_line(_report(as_of=datetime(2026, 10, 6, 21, tzinfo=UTC), hours=10.0), "en")
    assert en and "overnight closes" in en


def test_short_reads_the_upper_tail():
    en = long_record_line(_report(side=Side.SHORT), "en")
    assert en and "rose more than" in en


def test_unknown_ticker_is_silent():
    assert long_record_line(_report(ticker="ZZZZ"), "en") is None
