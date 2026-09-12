"""Yahoo / Nasdaq / FRED / RSS clients against mocked transports."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from nightwatch.data import fred as fred_mod
from nightwatch.data.fred import FredClient, fomc_decisions
from nightwatch.data.http import HttpClient, UpstreamError
from nightwatch.data.models import Interval, Venue
from nightwatch.data.nasdaq import BASE_URL as NASDAQ_URL
from nightwatch.data.nasdaq import NasdaqEarningsClient
from nightwatch.data.rss import RssNewsClient
from nightwatch.data.yahoo import BASE_URL as YAHOO_URL
from nightwatch.data.yahoo import YahooChartClient
from nightwatch.time_utils import ET

UTC = timezone.utc


def fast(base: str = "") -> HttpClient:
    return HttpClient(base, rate_per_sec=1000, burst=1000)


# --- Yahoo ------------------------------------------------------------------------


@respx.mock
def test_yahoo_parses_bars_and_skips_nulls():
    t0 = 1_757_000_000
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"exchangeTimezoneName": "America/New_York"},
                    "timestamp": [t0, t0 + 3600, t0 + 7200],
                    "indicators": {"quote": [{"open": [1, None, 3], "high": [2, None, 4], "low": [0.5, None, 2.5], "close": [1.5, None, 3.5], "volume": [10, None, 30]}]},
                }
            ],
            "error": None,
        }
    }
    respx.get(f"{YAHOO_URL}/v8/finance/chart/NVDA").mock(return_value=httpx.Response(200, json=payload))
    bars = YahooChartClient(http=fast(YAHOO_URL)).get_bars("NVDA", Interval.H1, datetime.fromtimestamp(t0, tz=UTC), datetime.fromtimestamp(t0 + 10800, tz=UTC))
    assert [b.ts.timestamp() for b in bars] == [t0, t0 + 7200]  # null row skipped
    assert bars[0].venue == Venue.YAHOO and bars[0].volume_base == 10.0 and bars[0].ts.tzinfo is not None


@respx.mock
def test_yahoo_error_payload_raises():
    respx.get(f"{YAHOO_URL}/v8/finance/chart/NOPE").mock(
        return_value=httpx.Response(200, json={"chart": {"result": None, "error": {"code": "Not Found", "description": "No data"}}})
    )
    with pytest.raises(UpstreamError):
        YahooChartClient(http=fast(YAHOO_URL)).get_bars("NOPE", Interval.D1, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


@respx.mock
def test_yahoo_chunks_long_hourly_ranges():
    route = respx.get(f"{YAHOO_URL}/v8/finance/chart/TSLA").mock(return_value=httpx.Response(200, json={"chart": {"result": [], "error": None}}))
    end = datetime.now(tz=UTC)
    YahooChartClient(http=fast(YAHOO_URL)).get_bars("TSLA", Interval.H1, end - timedelta(days=700), end)
    assert route.call_count == 2  # 365-day chunks


# --- Nasdaq -----------------------------------------------------------------------


@respx.mock
def test_nasdaq_calendar_timing_and_money_parsing():
    respx.get(f"{NASDAQ_URL}/api/calendar/earnings").mock(
        return_value=httpx.Response(200, json={"data": {"rows": [
            {"symbol": "NVDA", "time": "time-after-hours", "epsForecast": "$1.20", "fiscalQuarterEnding": "Jul 2026"},
            {"symbol": "aapl", "time": "time-pre-market", "epsForecast": "($0.05)", "fiscalQuarterEnding": None},
            {"symbol": "X", "time": "time-not-supplied", "epsForecast": ""},
        ]}})
    )
    start = datetime(2026, 9, 15, tzinfo=ET)
    events = NasdaqEarningsClient(http=fast(NASDAQ_URL)).get_calendar(start, start + timedelta(days=1))
    by = {e.ticker: e for e in events}
    assert by["NVDA"].timing == "amc" and by["NVDA"].eps_estimate == 1.2 and by["NVDA"].fiscal_quarter_end == "Jul 2026"
    assert by["AAPL"].timing == "bmo" and by["AAPL"].eps_estimate == -0.05
    assert by["X"].timing == "unknown" and by["X"].eps_estimate is None
    assert by["NVDA"].report_date == datetime(2026, 9, 15, tzinfo=ET).astimezone(UTC)


@respx.mock
def test_nasdaq_history_sorted_ascending():
    respx.get(f"{NASDAQ_URL}/api/company/nvda/earnings-surprise").mock(
        return_value=httpx.Response(200, json={"data": {"earningsSurpriseTable": {"rows": [
            {"dateReported": "8/26/2026", "eps": "$2.22", "consensusForecast": "$2.09", "percentageSurprise": "6.22", "fiscalQtrEnd": "Jul 2026"},
            {"dateReported": "5/20/2026", "eps": "$1.87", "consensusForecast": "$1.70", "percentageSurprise": "10", "fiscalQtrEnd": "Apr 2026"},
        ]}}})
    )
    hist = NasdaqEarningsClient(http=fast(NASDAQ_URL)).get_history("NVDA")
    assert [h.report_date.astimezone(ET).date().isoformat() for h in hist] == ["2026-05-20", "2026-08-26"]
    assert hist[1].eps_actual == 2.22 and hist[1].surprise_pct == 6.22


# --- FRED -------------------------------------------------------------------------


@respx.mock
def test_fred_csv_series_parsing_with_missing_values():
    csv = "observation_date,DGS10\n2026-09-04,4.78\n2026-09-07,.\n2026-09-08,4.80\n"
    respx.get(f"{fred_mod.GRAPH_URL}/graph/fredgraph.csv").mock(return_value=httpx.Response(200, text=csv))
    client = FredClient(http_graph=fast(fred_mod.GRAPH_URL), http_api=fast(fred_mod.API_URL))
    rows = client.get_series("DGS10", datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 30, tzinfo=UTC))
    assert [(r.period, r.value) for r in rows] == [("2026-09-04", 4.78), ("2026-09-07", None), ("2026-09-08", 4.8)]
    assert rows[0].name == "10-year Treasury yield"


def test_fomc_schedule_instants_are_2pm_et():
    ev = fomc_decisions(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    assert len(ev) == 1
    et = ev[0].release_ts.astimezone(ET)
    assert (et.date().isoformat(), et.hour) == ("2026-09-16", 14)


@respx.mock
def test_fred_release_calendar_filters_key_releases_when_key_set():
    respx.get(f"{fred_mod.API_URL}/fred/releases/dates").mock(
        return_value=httpx.Response(200, json={"release_dates": [
            {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-09-11"},
            {"release_id": 50, "release_name": "Employment Situation", "date": "2026-10-02"},
            {"release_id": 99, "release_name": "Something Obscure", "date": "2026-09-12"},
        ]})
    )
    client = FredClient("k", http_graph=fast(fred_mod.GRAPH_URL), http_api=fast(fred_mod.API_URL))
    rows = client.get_release_calendar(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    ids = [r.series_id for r in rows]
    assert ids == ["CPI", "FOMC"]  # NFP is October, obscure release filtered out
    assert rows[0].release_ts.astimezone(ET).hour == 8


# --- RSS --------------------------------------------------------------------------

RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>t</title>
<item><title>Tesla\xe2\x80\x99s robotaxi expands</title><link>https://x/1</link><guid>g1</guid>
<pubDate>Fri, 11 Sep 2026 15:19:00 GMT</pubDate><description>Musk says more cities.</description></item>
<item><title>Amdocs reports quarter</title><link>https://x/2</link><guid>g2</guid>
<pubDate>Fri, 11 Sep 2026 16:00:00 GMT</pubDate><description>AMDOCS beat estimates.</description></item>
<item><title>Chipmaker AMD raises guidance</title><link>https://x/3</link><guid>g3</guid>
<pubDate>Fri, 11 Sep 2026 17:00:00 GMT</pubDate></item>
</channel></rss>"""


@respx.mock
def test_rss_tags_tickers_and_handles_encoding():
    respx.get("https://feed.test/rss").mock(return_value=httpx.Response(200, content=RSS_XML, headers={"content-type": "application/xml; charset=iso-8859-1"}))
    client = RssNewsClient({"t": "https://feed.test/rss"}, tickers=["TSLA", "AMD"], http=fast())
    items = client.fetch()
    assert [i.tickers for i in items] == [("TSLA",), (), ("AMD",)]
    assert "Tesla’s" in items[0].title  # bytes fed to parser: no mojibake
    assert items[0].published_at == datetime(2026, 9, 11, 15, 19, tzinfo=UTC)
    assert items[0].id != items[1].id


@respx.mock
def test_rss_dead_feed_does_not_stop_others():
    respx.get("https://feed.test/dead").mock(return_value=httpx.Response(404))
    respx.get("https://feed.test/ok").mock(return_value=httpx.Response(200, content=RSS_XML))
    client = RssNewsClient({"dead": "https://feed.test/dead", "ok": "https://feed.test/ok"}, tickers=["TSLA"], http=fast())
    client._http._retry.base_delay = 0.0
    items = client.fetch()
    assert len(items) == 3 and all(i.source == "ok" for i in items)
