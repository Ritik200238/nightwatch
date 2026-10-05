"""Options-implied move: Cboe's real document shape, the arithmetic, the cache, and the report.

The fixture is a trimmed copy of Cboe's TSLA chain recorded on 2026-10-05 (four expiries, strikes
within $15 of the last price, real quotes). Every HTTP call here is a mock transport.
"""

import json
import math
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from nightwatch.data.cboe import AtmQuote, CboeOptionsClient, NoOptions, OptionsChain, parse_chain
from nightwatch.data.http import HttpClient, RetryPolicy, UpstreamError
from nightwatch.features import options as opt
from nightwatch.time_utils import ET, UTC
from tests.test_pipeline import _ctx, seeded_store  # noqa: F401 - fixture

DOC = json.loads((Path(__file__).parent / "data" / "cboe_tsla_2026-10-02.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)  # Monday 05:00 ET


def chain() -> OptionsChain:
    return parse_chain(DOC, "TSLA", NOW)


def quick(handler):  # noqa: ANN001, ANN201
    return CboeOptionsClient(http=HttpClient("https://cdn.cboe.com", rate_per_sec=1000, burst=1000, retry=RetryPolicy(max_attempts=2, base_delay=0.0, max_delay=0.0),
                                             transport=httpx.MockTransport(handler)))


# ------------------------------------------------------------------ parsing


def test_the_real_document_is_reduced_to_one_atm_quote_per_expiry():
    c = chain()
    assert c.spot == 371.43 and c.iv30 == pytest.approx(0.43035)
    assert [q.expiry for q in c.expiries] == [date(2026, 10, 5), date(2026, 10, 9), date(2026, 10, 16), date(2026, 11, 20)]
    q = next(x for x in c.expiries if x.expiry == date(2026, 10, 9))
    assert q.strike == 372.5, "the strike nearest 371.43 with a two-sided quote on both sides"
    assert q.call_mid == pytest.approx(6.45) and q.put_mid == pytest.approx(7.95)
    assert q.call_iv == pytest.approx(0.351) and q.put_iv == pytest.approx(0.3431)
    # Last trade 15:59:59 Eastern, as UTC.
    assert c.quote_ts == datetime(2026, 10, 2, 15, 59, 59, tzinfo=ET).astimezone(UTC)


def test_contracts_without_a_real_two_sided_quote_are_ignored():
    doc = {"data": {"current_price": 100.0, "options": [
        {"option": "XYZ261009C00100000", "bid": 0.0, "ask": 1.0, "iv": 0.4},      # no bid
        {"option": "XYZ261009P00100000", "bid": 1.0, "ask": 1.2, "iv": 0.4},
        {"option": "XYZ261009C00105000", "bid": 2.0, "ask": 2.2, "iv": 0.0},      # no IV
        {"option": "XYZ261009P00105000", "bid": 3.0, "ask": 3.2, "iv": 0.4},
        {"option": "XYZ261016C00110000", "bid": 1.0, "ask": 1.1, "iv": 0.5},
        {"option": "XYZ261016P00110000", "bid": 9.0, "ask": 9.5, "iv": 0.5},
        {"option": "XYZ1261016C00100000", "bid": 1.0, "ask": 1.1, "iv": 0.5},     # adjusted root
    ]}}
    c = parse_chain(doc, "XYZ", NOW)
    assert [q.expiry for q in c.expiries] == [date(2026, 10, 16)], "the 10-09 expiry has no strike with both sides usable"
    with pytest.raises(UpstreamError):
        parse_chain({"data": {"options": []}}, "XYZ", NOW)


# --------------------------------------------------------------------- client


def test_a_redirect_is_followed_and_the_chain_is_read():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/TSLA.json") and len(seen) == 1:
            return httpx.Response(307, headers={"location": "https://cdn.cboe.com/api/global/delayed_quotes/options/_TSLA.json"})
        return httpx.Response(200, json=DOC)

    got = quick(handler).get_chain("TSLA", fetched_at=NOW)
    assert got.listed and len(seen) == 2


def test_a_name_cboe_does_not_carry_is_no_options_not_an_outage():
    with pytest.raises(NoOptions):
        quick(lambda r: httpx.Response(403, text="forbidden")).get_chain("ZZZZ", fetched_at=NOW)
    with pytest.raises(NoOptions):
        quick(lambda r: httpx.Response(200, json={"data": {"current_price": 10.0, "options": []}})).get_chain("ETFX", fetched_at=NOW)


def test_a_5xx_is_an_error_that_is_not_mistaken_for_no_options():
    with pytest.raises(Exception) as exc:  # noqa: PT011
        quick(lambda r: httpx.Response(503)).get_chain("TSLA", fetched_at=NOW)
    assert not isinstance(exc.value, NoOptions)


# ---------------------------------------------------------------- arithmetic


def test_trading_days_count_only_open_days():
    fri_close = datetime(2026, 9, 18, 16, 0, tzinfo=ET)
    mon_open = datetime(2026, 9, 21, 9, 30, tzinfo=ET)
    assert opt.trading_days(fri_close, mon_open) == pytest.approx(8 / 24 + 9.5 / 24)
    assert opt.trading_days(datetime(2026, 9, 19, 1, 0, tzinfo=ET), datetime(2026, 9, 20, 23, 0, tzinfo=ET)) == 0.0, "a weekend has no trading time"
    labor_day = datetime(2026, 9, 7, 0, 0, tzinfo=ET)
    assert opt.trading_days(labor_day, labor_day + timedelta(days=1)) == 0.0, "an exchange holiday counts for nothing"


def test_the_implied_move_follows_the_documented_formula():
    c = chain()
    got = opt.implied_move(c, NOW, 10.0)  # Monday 05:00 ET, 10 h: ends 15:00 ET, so the expiry that closes today covers it
    assert got["expiry"] == "2026-10-05"
    q = next(x for x in c.expiries if x.expiry == date(2026, 10, 5))
    iv = (q.call_iv + q.put_iv) / 2
    exp_close = datetime(2026, 10, 5, 16, 0, tzinfo=ET)
    # The quotes are Friday's close, so the expiry's time is counted from then: the weekend is in the IV.
    anchor = datetime(2026, 10, 2, 15, 59, 59, tzinfo=ET)
    cal = (exp_close - anchor).total_seconds() / 86400
    exp_td = (8 + 16) / 24  # Friday 16:00-24:00 and Monday 00:00-16:00 clock hours; the weekend counts for nothing
    hold_td = 10 / 24
    assert got["implied_move_pct"] == pytest.approx(iv * math.sqrt(cal / 365 * hold_td / exp_td) * 100, rel=1e-3)
    assert got["anchor"].startswith("2026-10-02T19:59:59")
    # The straddle cross-check lands in the same order of magnitude, not on the same number.
    assert 0.3 < got["straddle_move_pct"] / got["implied_move_pct"] < 3.0
    assert got["quote_ts"] and got["source"] == "Cboe delayed quotes"


def test_a_hold_that_outlives_an_expiry_uses_the_next_one():
    got = opt.implied_move(chain(), NOW, 3 * 24)  # ends Thursday 05:00 ET: needs the 10-09 expiry
    assert got["expiry"] == "2026-10-09"
    # A longer hold is a bigger move.
    assert got["implied_move_pct"] > opt.implied_move(chain(), NOW, 10.0)["implied_move_pct"]


def test_no_covering_expiry_or_no_trading_time_means_no_number():
    assert opt.implied_move(chain(), NOW, 24 * 400) is None
    saturday = datetime(2026, 10, 3, 14, 0, tzinfo=UTC)
    assert opt.implied_move(chain(), saturday, 10.0) is None, "a hold wholly inside a weekend has no trading time in it"


def test_the_line_sets_the_implied_move_beside_the_desks_one_in_twenty():
    assert opt.line(2.34, -3.8) == "Options market implies about ±2.3% over this hold; history says one in twenty worse than −3.8%."
    assert opt.line(2.34, None) == "Options market implies about ±2.3% over this hold."
    b = opt.attach_history({"implied_move_pct": 1.0}, 4.0)  # a positive "p5" is not a loss line
    assert b["desk_p5_pct"] is None and b["line"].endswith("hold.")


# --------------------------------------------------------------------- cache


class FakeCboe:
    def __init__(self, result="chain", gate=None):  # noqa: ANN001
        self.result, self.calls, self.gate = result, 0, gate

    def get_chain(self, ticker, *, fetched_at):  # noqa: ANN001, ANN201
        self.calls += 1
        if self.gate:
            self.gate.wait(5)
        if self.result == "none":
            raise NoOptions(ticker)
        if self.result == "fail":
            raise UpstreamError("down")
        return chain()


def wait_for(cond, n=100):  # noqa: ANN001, ANN201
    for _ in range(n):
        if cond():
            return True
        threading.Event().wait(0.02)
    return False


def test_a_cold_cache_never_waits_it_asks_for_a_background_fetch(seeded_store):  # noqa: F811
    gate = threading.Event()
    ctx = _ctx(seeded_store)
    ctx.options_client = FakeCboe(gate=gate)
    assert ctx.options_chain_for("TSLA") is None and "TSLA" in ctx._options_pending, "returned at once"
    gate.set()
    assert wait_for(lambda: "TSLA" in ctx._options)
    assert ctx.options_chain_for("TSLA").listed
    n = ctx.options_client.calls
    for _ in range(5):
        ctx.options_chain_for("TSLA")
    assert ctx.options_client.calls == n, "cached for 30 minutes"


def test_no_listed_options_is_remembered_for_hours(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    ctx.options_client = FakeCboe("none")
    assert ctx.options_chain_for("QQQ", fetch=True) == "none"
    assert ctx.options_chain_for("QQQ") == "none" and ctx.options_client.calls == 1


def test_a_failure_is_paced_and_an_older_chain_is_kept_but_not_past_a_day(seeded_store):  # noqa: F811
    from nightwatch.pipeline.analyze import utc_now

    ctx = _ctx(seeded_store)
    ctx.options_client = FakeCboe()
    ctx.options_chain_for("TSLA", fetch=True)
    ctx._options["TSLA"] = (utc_now() - timedelta(hours=2), ctx._options["TSLA"][1])  # stale, still servable
    ctx.options_client = FakeCboe("fail")
    assert ctx.options_chain_for("TSLA", fetch=True).listed, "an old good chain beats nothing"
    assert ctx.options_client.calls == 1
    ctx.options_chain_for("TSLA", fetch=True)
    assert ctx.options_client.calls == 1, "a failing endpoint is not hammered"
    ctx._options["TSLA"] = (utc_now() - timedelta(hours=30), ctx._options["TSLA"][1])
    assert ctx.options_chain_for("TSLA") is None


# ------------------------------------------------------------------ the report


def _analyse(path, monkeypatch, *, chain_value, now=None):  # noqa: ANN001, ANN202
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from tests.test_pipeline import AS_OF

    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: now or AS_OF)
    ctx = _ctx(path)
    ctx.options_client = FakeCboe()
    if chain_value is not None:
        ctx._options["TSLA"] = (now or AS_OF, chain_value)
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
    return analyze(ctx, ticket, as_of=AS_OF, record=False).to_dict()


def _weekly_chain():  # noqa: ANN202
    from tests.test_pipeline import AS_OF

    q = AtmQuote(expiry=date(2026, 9, 18), strike=350.0, call_mid=9.0, put_mid=8.5, call_iv=0.40, put_iv=0.42, n_strikes=12)
    return OptionsChain(ticker="TSLA", spot=350.0, quote_ts=AS_OF - timedelta(hours=20), fetched_at=AS_OF, iv30=0.45, expiries=[q])


def test_the_report_puts_the_implied_move_beside_the_desks_own_one_in_twenty(seeded_store, monkeypatch):  # noqa: F811
    r = _analyse(seeded_store, monkeypatch, chain_value=_weekly_chain())
    o = r["options"]
    assert o and o["expiry"] == "2026-09-18" and o["implied_move_pct"] > 0
    h = r["analog"]["horizons"][r["primary_horizon"]]
    assert o["desk_p5_pct"] == h["loss_p5_pct"] and o["line"].startswith("Options market implies about ±")
    if h["loss_p5_pct"] is not None and h["loss_p5_pct"] < 0:
        assert f"worse than −{abs(h['loss_p5_pct']):.1f}%" in o["line"]
    src = next(s for s in r["sources"] if s["kind"] == "cboe_options")
    assert src["rows_used"] == 12 and src["last_ts"]


def test_a_token_with_no_options_or_a_cold_cache_just_has_no_line(seeded_store, monkeypatch):  # noqa: F811
    assert _analyse(seeded_store, monkeypatch, chain_value="none")["options"] is None
    r = _analyse(seeded_store, monkeypatch, chain_value=None)
    assert r["options"] is None and not any(s["kind"] == "cboe_options" for s in r["sources"])
    assert not any("ptions" in w for w in r["warnings"])


def test_a_past_moment_never_gets_todays_options(seeded_store, monkeypatch):  # noqa: F811
    from tests.test_pipeline import AS_OF

    assert _analyse(seeded_store, monkeypatch, chain_value=_weekly_chain(), now=AS_OF + timedelta(days=30))["options"] is None


def test_sources_lists_it():
    from nightwatch.api.sources import options_row

    row = options_row({"TSLA": (NOW, chain()), "QQQQ": (NOW, "none"), "BAD": (NOW - timedelta(days=1), None)}, {"BAD": NOW})
    assert row["key"] == "cboe_options" and row["rows"] == 1
    assert row["latest_label"] == "1 tokens with an options chain; 1 with no listed options; 1 not answering"
    assert options_row({}, {})["latest_label"] == "none fetched yet"
