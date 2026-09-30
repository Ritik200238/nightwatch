"""Three silent gaps a judge found: filings the feature counted but the page hid,
a 720-hour cap read as a real date, and sources that named three of ten feeds."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from nightwatch.data.models import Filing
from nightwatch.data.store import Store
from nightwatch.decision.ticket import TradeTicket
from nightwatch.features.phrases import NO_EARNINGS_30D, earnings_ahead, hours_ago
from nightwatch.pipeline.analyze import FILING_LOOKBACK_H, _filing_notes, analyze
from nightwatch.pipeline.feeds import feed_sources
from nightwatch.stress.scenarios import Side
from tests.test_pipeline import AS_OF, _ctx, seeded_store  # noqa: F401 - fixture


def _filing(acc, at):
    return Filing(ticker="TSLA", cik="1", form="8-K", accepted_at=at, filed_date=at, accession=acc, items="2.02", observed_at=at + timedelta(minutes=5))


def _ticket():
    return TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0, thesis="t", invalidation="i")


def test_an_unread_filing_the_feature_counted_is_still_on_the_page(tmp_path):
    with Store(tmp_path / "f.sqlite") as store:
        earlier = AS_OF - timedelta(hours=50)  # inside 72 h, outside the old 36 h window
        store.upsert_filings([_filing("a1", earlier)])
        notes = _filing_notes(SimpleNamespace(store=store), _ticket(), AS_OF, 24.0)
    assert FILING_LOOKBACK_H == 72.0
    assert len(notes) == 1 and notes[0].market_moving == "unread" and notes[0].label_p5_pct is None
    assert "not yet read" in notes[0].headline


def test_the_720_hour_cap_never_reads_as_a_number():
    assert earnings_ahead(720.0) == NO_EARNINGS_30D
    assert "720" not in earnings_ahead(720.0) and "not known" in earnings_ahead(None)
    assert earnings_ahead(30.0) == "in 30 hours" and earnings_ahead(96.0) == "in 4 days"
    assert hours_ago(720.0) == "more than 30 days ago"


def test_the_brief_and_followup_say_no_earnings_not_720(seeded_store):  # noqa: F811
    from nightwatch.api.followup import _a_premise
    from nightwatch.pipeline.render import render_text

    ctx = _ctx(seeded_store)
    report = analyze(ctx, _ticket(), as_of=AS_OF)
    report.snapshot.features["hours_to_earnings"] = 720.0
    text = render_text(report)
    assert "earnings: no earnings in the next 30 days" in text and "720" not in text.split("NOW")[1].split("\n")[3]
    ans = _a_premise(report.to_dict(), "")
    assert ans is not None and NO_EARNINGS_30D in ans.text and "720" not in ans.text
    ctx.store.close()


def test_sources_list_every_feed_with_its_freshness(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    report = analyze(ctx, _ticket(), as_of=AS_OF)
    by = {s["kind"]: s for s in report.sources}
    for kind in ("bitget_candles", "bitget_perp", "yahoo_bars", "nasdaq_earnings", "fred_macro", "rss_news", "sec_edgar", "orderbook"):
        assert kind in by and by[kind]["label"] and "rows_used" in by[kind], kind
    assert by["bitget_candles"]["rows_used"] > 0 and by["bitget_candles"]["last_ts"] <= AS_OF.isoformat()
    assert by["fred_macro"]["rows_used"] >= 1
    assert by["sec_edgar"]["rows_used"] == 0 and by["sec_edgar"]["last_ts"] is None  # listed even when empty
    ctx.store.close()


@pytest.mark.parametrize("perp", [None, "TSLAUSDT"])
def test_feed_sources_only_lists_the_perp_when_there_is_one(tmp_path, perp):
    with Store(tmp_path / "s.sqlite") as store:
        kinds = [s["kind"] for s in feed_sources(store, ticker="TSLA", spot_symbol="RTSLAUSDT", perp_symbol=perp, yahoo_ticker="TSLA", as_of=AS_OF)]
    assert ("bitget_perp" in kinds) == (perp is not None) and "sec_edgar" in kinds
