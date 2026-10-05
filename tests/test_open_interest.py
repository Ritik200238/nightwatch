"""Perp open interest: the endpoint's real shape, the 24 h comparison from the recorder, the cache."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from nightwatch.data.bitget import BASE_URL, BitgetPublicClient
from nightwatch.data.http import HttpClient, UpstreamError
from nightwatch.data.models import Ticker, Venue
from nightwatch.data.store import Store
from nightwatch.features import open_interest as oi
from nightwatch.time_utils import UTC
from tests.test_pipeline import _ctx, seeded_store  # noqa: F401 - fixture

# A recorded response (TSLAUSDT, 2026-10-05), not a hand-written one.
FIXTURE = json.loads((Path(__file__).parent / "data" / "bitget_open_interest_tslausdt_2026-10-05.json").read_text(encoding="utf-8"))
URL = f"{BASE_URL}/api/v3/market/open-interest"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def perp() -> BitgetPublicClient:
    return BitgetPublicClient(Venue.BITGET_UMCBL, http=HttpClient(BASE_URL, rate_per_sec=1000, burst=1000))


def tick(store: Store, ts: datetime, open_interest: float | None, symbol: str = "TSLAUSDT") -> None:
    store.insert_tickers([Ticker(venue=Venue.BITGET_UMCBL, symbol=symbol, ts=ts, last=370.0, bid=369.9, ask=370.1, open_interest=open_interest, observed_at=ts)])


@pytest.fixture()
def store(tmp_path):  # noqa: ANN001, ANN201
    with Store(tmp_path / "oi.sqlite") as s:
        yield s


# ------------------------------------------------------------------ the endpoint


@respx.mock
def test_the_recorded_response_is_read():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    contracts, ts = perp().get_open_interest("TSLAUSDT")
    assert contracts == pytest.approx(38321.82) and ts == datetime.fromtimestamp(1791189967.482, tz=UTC)
    assert dict(route.calls[0].request.url.params) == {"category": "USDT-FUTURES", "symbol": "TSLAUSDT"}


@respx.mock
def test_a_symbol_with_no_row_is_an_error_not_a_zero():
    respx.get(URL).mock(return_value=httpx.Response(200, json={"code": "00000", "msg": "success", "data": {"list": [], "ts": "1"}}))
    with pytest.raises(UpstreamError):
        perp().get_open_interest("NOPEUSDT")


def test_spot_has_no_open_interest():
    spot = BitgetPublicClient(Venue.BITGET_SPOT, http=HttpClient(BASE_URL, rate_per_sec=1000, burst=1000))
    with pytest.raises(ValueError):
        spot.get_open_interest("RTSLAUSDT")


# ------------------------------------------------------- 24 h change, from the recorder


def test_the_change_is_measured_against_the_recorded_reading_nearest_a_day_ago(store):  # noqa: ANN001
    tick(store, NOW - timedelta(hours=27), 1.0)  # too far from 24 h ago
    tick(store, NOW - timedelta(hours=24, minutes=2), 36_000.0)
    tick(store, NOW - timedelta(hours=22), 99.0)
    block = oi.build("TSLAUSDT", 38_321.82, NOW, store, price=370.0)
    assert block["change_24h_pct"] == pytest.approx((38_321.82 / 36_000 - 1) * 100)
    assert block["usd"] == pytest.approx(38_321.82 * 370.0)
    assert block["line"] == "Open interest 38,322 contracts (about $14.2M), up 6.4% in 24h."


def test_without_a_reading_from_a_day_ago_the_change_is_left_out_and_the_line_says_so(store):  # noqa: ANN001
    tick(store, NOW - timedelta(hours=2), 38_000.0)  # recent, but not a day old
    tick(store, NOW - timedelta(hours=24), 5.0, symbol="OTHERUSDT")  # another symbol
    block = oi.build("TSLAUSDT", 38_321.82, NOW, store)
    assert block["change_24h_pct"] is None and block["compared_with_ts"] is None
    assert "no reading from a day ago" in block["line"] and "$" not in block["line"]


def test_down_and_flat_are_said_in_words(store):  # noqa: ANN001
    tick(store, NOW - timedelta(hours=24), 40_000.0)
    assert oi.build("TSLAUSDT", 36_000.0, NOW, store)["line"].endswith("down 10.0% in 24h.")
    assert "about the same as 24 h ago" in oi.build("TSLAUSDT", 40_100.0, NOW, store)["line"]


# ----------------------------------------------------------------- the cache


class FakePerp:
    def __init__(self, fail: bool = False):
        self.fail, self.calls = fail, 0

    def get_open_interest(self, symbol):  # noqa: ANN001, ANN201
        self.calls += 1
        if self.fail:
            raise UpstreamError("down")
        return 1_000.0, NOW


def test_one_request_per_token_per_ttl_and_failures_never_raise(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    assert ctx.open_interest_for("TSLAUSDT") is None, "no perp client, nothing to say"
    ctx.perp_client = FakePerp()
    for _ in range(5):
        assert ctx.open_interest_for("TSLAUSDT")["contracts"] == 1_000.0
    assert ctx.perp_client.calls == 1
    ctx.perp_client = FakePerp(fail=True)
    for _ in range(3):
        assert ctx.open_interest_for("NVDAUSDT") is None
    assert ctx.perp_client.calls == 1, "a failing endpoint is not retried by every request"


# ------------------------------------------------------------------ the report


def _analyse(path, monkeypatch, *, leverage=None, now=None):  # noqa: ANN001, ANN202
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from tests.test_pipeline import AS_OF

    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: now or AS_OF)
    ctx = _ctx(path)
    ctx.perp_client = FakePerp()
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0, leverage=leverage,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
    return analyze(ctx, ticket, as_of=AS_OF, record=False).to_dict()


def test_a_leveraged_report_carries_the_one_plain_line(seeded_store, monkeypatch):  # noqa: F811
    r = _analyse(seeded_store, monkeypatch, leverage=5.0)
    assert r["open_interest"]["contracts"] == 1_000.0
    assert r["leverage"]["open_interest_line"] == r["open_interest"]["line"]
    assert any(s["kind"] == "bitget_open_interest" and s["rows_used"] == 1 for s in r["sources"])


def test_an_unleveraged_report_still_shows_it_but_not_in_a_leverage_block(seeded_store, monkeypatch):  # noqa: F811
    r = _analyse(seeded_store, monkeypatch)
    assert r["open_interest"] and r["leverage"] is None


def test_a_past_moment_never_gets_todays_open_interest(seeded_store, monkeypatch):  # noqa: F811
    from tests.test_pipeline import AS_OF

    assert _analyse(seeded_store, monkeypatch, now=AS_OF + timedelta(days=30))["open_interest"] is None


def test_sources_lists_it():
    from nightwatch.api.sources import open_interest_row

    row = open_interest_row({"TSLAUSDT": (NOW, {"x": 1}), "NVDAUSDT": (NOW, None)})
    assert row["key"] == "bitget_oi" and row["rows"] == 1 and "1 not answering (NVDAUSDT)" in row["latest_label"]
    assert open_interest_row({})["latest_label"] == "none read yet"
