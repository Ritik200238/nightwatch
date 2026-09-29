"""Holdings change the verdict and the size, not only the text.

Runs the real pipeline on the seeded store from test_pipeline, so the book's tail, the
book_tail cap, the concentration cap and the what-if sweeps are all exercised together.
"""

from dataclasses import replace

import pytest

from nightwatch.api import intake
from nightwatch.decision.gate import GateInputs, evaluate_gate
from nightwatch.decision.portfolio import Position, build_book_model
from nightwatch.decision.sizing import SizingInputs, SizingPolicy, Verdict, compute_caps
from nightwatch.decision.ticket import TradeTicket
from nightwatch.pipeline.analyze import analyze
from nightwatch.stress.scenarios import Side
from tests.test_pipeline import AS_OF, Interval, Venue, _ctx, seeded_store  # noqa: F401 - fixture

EQUITY = 200_000.0
TICKERS = ["TSLA", "NVDA", "AAPL", "AMD"]


def _entry(ctx, t: str) -> float:
    return float(ctx.store.get_bars(Venue.BITGET_SPOT, f"R{t}USDT", Interval.H1)["close"].iloc[-1])


def _ticket(ctx, ticker="TSLA", side=Side.LONG, notional=20_000.0, held=()) -> TradeTicket:
    stop = _entry(ctx, ticker) * (0.96 if side == Side.LONG else 1.04)
    return TradeTicket(ticker=ticker, side=side, notional_quote=notional, account_equity_quote=EQUITY, stop_price=stop, thesis="t", invalidation="i", open_positions=tuple(held))


def _caps(report):
    return {c.name: c.notional for c in report.sizing.caps}


@pytest.fixture
def ctx(seeded_store):  # noqa: F811
    c = _ctx(seeded_store)
    yield c
    c.store.close()


def test_no_holdings_leaves_the_report_exactly_as_it_was(ctx):
    """Measured against the pre-change code on the same seeded store: same verdicts, sizes and caps."""
    got = {}
    for t, side, n in (("TSLA", Side.LONG, 20_000.0), ("AAPL", Side.LONG, 10_000.0)):
        r = analyze(ctx, _ticket(ctx, t, side, n), as_of=AS_OF)
        assert r.portfolio is None
        assert [c.name for c in r.sizing.caps] == ["risk_budget", "concentration", "regime", "exit_liquidity", "stress"]
        assert all(x.rule != "book_tail" for x in r.gate.rules)
        got[t] = (r.verdict.verdict, r.verdict.recommended_notional, r.sizing.binding_cap)
    assert got["TSLA"] == (Verdict.GO, 20_000.0, "regime")
    assert got["AAPL"] == (Verdict.REVIEW, pytest.approx(3750.0), "regime")


def test_a_concentrated_book_changes_the_size(ctx):
    """The same trade, judged alone and against a book that is already one big bet on it."""
    ctx.sizing_policy = SizingPolicy(max_book_tail_pct_of_equity=1.0)
    alone = analyze(ctx, _ticket(ctx), as_of=AS_OF, record=False)
    booked = analyze(ctx, _ticket(ctx, held=[("TSLA", "long", 40_000.0)]), as_of=AS_OF, record=False)
    assert alone.verdict.verdict == Verdict.GO and alone.verdict.recommended_notional == 20_000.0
    assert booked.sizing.binding_cap == "book_tail"
    assert booked.verdict.recommended_notional < alone.verdict.recommended_notional
    assert booked.verdict.verdict == Verdict.REDUCE_TO
    # The cap does what it says: at the recommended size the book's tail sits on the limit.
    p = booked.portfolio
    assert p.book_cap_binds and p.book_cap_quote == pytest.approx(booked.verdict.recommended_notional)
    assert abs(p.tail_after_recommended_quote) == pytest.approx(EQUITY * 0.01, rel=0.01)
    assert abs(p.after.tail_loss_quote) > abs(p.before.tail_loss_quote)


def test_same_name_exposure_counts_toward_concentration(ctx):
    r = analyze(ctx, _ticket(ctx, held=[("TSLA", "long", 40_000.0)]), as_of=AS_OF, record=False)
    assert _caps(r)["concentration"] == pytest.approx(EQUITY * 0.25 - 40_000.0)
    assert r.portfolio.same_name["combined_signed_quote"] == pytest.approx(60_000.0)
    # Held the other way round it does not relax the limit.
    other = analyze(ctx, _ticket(ctx, held=[("TSLA", "short", 40_000.0)]), as_of=AS_OF, record=False)
    assert _caps(other)["concentration"] == pytest.approx(EQUITY * 0.25)


def test_an_opposite_side_position_is_a_hedge_and_does_not_bind(ctx):
    ctx.sizing_policy = SizingPolicy(max_book_tail_pct_of_equity=1.0)
    r = analyze(ctx, _ticket(ctx, held=[("TSLA", "short", 40_000.0)]), as_of=AS_OF, record=False)
    assert r.sizing.binding_cap != "book_tail"
    assert r.portfolio.adds_tail_quote > 0  # the book's loss gets smaller
    assert not r.portfolio.book_cap_binds
    assert r.verdict.recommended_notional == pytest.approx(20_000.0)


def test_a_book_already_over_its_limit_refuses_more_of_the_same_and_allows_the_hedge(ctx):
    ctx.sizing_policy = SizingPolicy(max_book_tail_pct_of_equity=0.5)  # 1,000: the held 40k TSLA is already past it
    more = analyze(ctx, _ticket(ctx, held=[("TSLA", "long", 40_000.0)]), as_of=AS_OF, record=False)
    assert _caps(more)["book_tail"] == 0.0
    assert more.verdict.verdict == Verdict.NO_GO
    hedge = analyze(ctx, _ticket(ctx, held=[("TSLA", "short", 40_000.0)]), as_of=AS_OF, record=False)
    assert hedge.sizing.binding_cap != "book_tail" and hedge.verdict.recommended_notional > 0


def test_a_holding_with_no_history_is_flagged_and_never_assumed_flat(ctx):
    alone = analyze(ctx, _ticket(ctx), as_of=AS_OF, record=False)
    r = analyze(ctx, _ticket(ctx, held=[("ZZZZ", "long", 30_000.0)]), as_of=AS_OF, record=False)
    assert r.portfolio.unknown == ["ZZZZ"]
    assert r.portfolio.before.tail_loss_quote is None and r.portfolio.after.tail_loss_quote is None
    assert "book_tail" not in _caps(r)  # nothing to measure, so no cap
    assert any("no stored history for ZZZZ" in a for a in r.gate.advisories)
    assert r.verdict.recommended_notional == alone.verdict.recommended_notional
    assert r.gate.decision == alone.gate.decision  # an advisory, not a veto
    assert "not enough stored history" in intake.book_line(r) or "no book limit" in intake.book_line(r)


def test_a_partly_unknown_book_is_measured_on_the_rest(ctx):
    r = analyze(ctx, _ticket(ctx, held=[("NVDA", "long", 30_000.0), ("ZZZZ", "long", 30_000.0)]), as_of=AS_OF, record=False)
    assert r.portfolio.unknown == ["ZZZZ"]
    assert "book_tail" in _caps(r)
    assert r.portfolio.before.tail_loss_quote is not None
    assert r.portfolio.before.gross_quote == 60_000.0  # counted in exposure even though it is not in the tail
    assert "No stored history for ZZZZ" in intake.book_line(r)


def test_what_if_sweeps_size_against_the_same_book_as_the_headline(ctx):
    ctx.sizing_policy = SizingPolicy(max_book_tail_pct_of_equity=1.0)
    r = analyze(ctx, _ticket(ctx, held=[("TSLA", "long", 40_000.0)]), as_of=AS_OF, record=False)
    point = next(p for p in r.sensitivity.sizes if p.notional == r.ticket.notional_quote)
    assert point.verdict == r.verdict.verdict.value and point.binding_cap == r.sizing.binding_cap == "book_tail"
    assert point.recommended_notional == pytest.approx(r.verdict.recommended_notional)
    assert r.sensitivity.max_go_notional is not None and r.sensitivity.max_go_notional < r.ticket.notional_quote


def test_the_book_tail_uses_the_same_windows_for_every_holding(ctx):
    frames = {t: ctx.feature_frame(t, AS_OF) for t in ("TSLA", "NVDA")}
    built, _notes, unknown = build_book_model([Position("NVDA", "long", 30_000.0)], "TSLA", frames, horizon_h=24)
    assert unknown == () and built is not None
    assert len(built.times) == len(built.base) == len(built.unit) == len(built.positions_pnl)
    # A short is the mirror image of a long over the same windows.
    long_tail, short_tail = built.tail(10_000.0, "long"), built.tail(10_000.0, "short")
    assert long_tail != short_tail
    assert built.worst_window(10_000.0, "long") in {t.isoformat() for t in built.times}


def test_the_reply_leads_with_the_book(ctx):
    r = analyze(ctx, _ticket(ctx, held=[("NVDA", "long", 30_000.0)]), as_of=AS_OF, record=False)
    short = intake.brief_short(r)
    assert short.split("\n\n")[1].startswith("With your 30,000 USDT NVDA")
    assert "one-in-twenty loss goes from" in short
    zh = intake.brief_short(r, "zh")
    assert "你已有 30,000 USDT 的 NVDA" in zh
    assert intake.book_line(analyze(ctx, _ticket(ctx), as_of=AS_OF, record=False)) is None


# ---- the caps and the gate, without the pipeline ----------------------------------------------


def _inputs(**kw) -> SizingInputs:
    base = dict(entry_price=100.0, equity=100_000.0, stop_distance_pct=4.0, analog_p5_loss_pct=-4.0, risk_multiplier=1.0,
                max_exit_notional_within_budget=None, worst_severe_stress_pct=None, hedge_cost_bps_of_position=None, hedge_residual_p5_loss_pct=None)
    base.update(kw)
    return SizingInputs(**base)


def test_compute_caps_adds_book_tail_and_narrows_concentration_only_with_a_book():
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=100_000.0)
    plain = {c.name: c.notional for c in compute_caps(ticket, _inputs())}
    assert "book_tail" not in plain and plain["concentration"] == 25_000.0
    with_book = {c.name: c.notional for c in compute_caps(ticket, _inputs(book_tail_cap_notional=7_000.0, same_name_exposure_quote=10_000.0))}
    assert with_book["book_tail"] == 7_000.0 and with_book["concentration"] == 15_000.0
    assert {c.name: c.notional for c in compute_caps(ticket, _inputs(same_name_exposure_quote=90_000.0))}["concentration"] == 0.0


def test_gate_advises_on_a_correlated_book_and_missing_history_without_vetoing():
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=100_000.0, stop_price=96.0, thesis="t", invalidation="i")
    base = dict(entry_price=100.0, equity=100_000.0, analog_p5_loss_pct=-3.0, quality_flags=(), regime_label="calm", risk_multiplier=1.0, exit_cost_bps=5.0, exit_fully_filled=True)
    plain = evaluate_gate(ticket, GateInputs(**base))
    assert all(r.rule != "book_tail" for r in plain.rules)
    booked = evaluate_gate(replace(ticket, open_positions=(("NVDA", "long", 5_000.0), ("ZZZZ", "long", 1_000.0))),
                           GateInputs(**base, book_given=True, book_unknown=("ZZZZ",), book_mean_correlation=0.85))
    assert booked.decision == plain.decision
    assert any("no stored history for ZZZZ" in a for a in booked.advisories)
    assert any("0.85" in a for a in booked.advisories)
    assert all("_" not in reason.split(":")[0] for reason in booked.reasons)  # rule names read as words


# ---- chat ---------------------------------------------------------------------------------------


def test_chat_reads_holdings_in_english_and_keeps_the_new_trade_separate():
    p = intake.parse_message("long 20k TSLA, I also hold 30k NVDA", TICKERS)
    assert (p.ticker, p.side, p.notional_quote) == ("TSLA", "long", 20_000.0)
    assert p.open_positions == [("NVDA", "long", 30_000.0)]
    p = intake.parse_message("I already have 20k AAPL long and short 10k AMD, thinking of long 15k TSLA overnight", TICKERS)
    assert p.open_positions == [("AAPL", "long", 20_000.0), ("AMD", "short", 10_000.0)]
    assert (p.ticker, p.side, p.notional_quote) == ("TSLA", "long", 15_000.0)
    # "hold" on its own is a trade, and a comma then a side is the next trade, not a holding.
    assert intake.parse_message("hold 20k TSLA overnight", TICKERS).open_positions == []
    p = intake.parse_message("I also hold 30k NVDA, long 20k TSLA", TICKERS)
    assert p.open_positions == [("NVDA", "long", 30_000.0)] and p.ticker == "TSLA"


def test_chat_reads_holdings_in_chinese():
    p = intake.parse_message("我还持有3万U的英伟达，做多2万特斯拉", TICKERS + ["NVDA"])
    assert p.open_positions == [("NVDA", "long", 30_000.0)] and (p.ticker, p.side, p.notional_quote) == ("TSLA", "long", 20_000.0)
    p = intake.parse_message("我手上有5万U的NVDA空单，周末持有两万美元的特斯拉", TICKERS)
    assert p.open_positions == [("NVDA", "short", 50_000.0)] and p.ticker == "TSLA"
    p = intake.parse_message("我已经持有2万美元的英伟达和做空1万AMD，想做多特斯拉 1.5万U", TICKERS)
    assert p.open_positions == [("NVDA", "long", 20_000.0), ("AMD", "short", 10_000.0)]
    assert intake.parse_message("周末持有两万美元的特斯拉", TICKERS).open_positions == []


def test_holdings_merge_across_the_conversation_and_reach_the_ticket():
    msgs = [{"role": "user", "content": "I also hold 30k NVDA"}, {"role": "user", "content": "long 20k TSLA"},
            {"role": "user", "content": "and I also hold 10k AAPL, my account is 200k"}, {"role": "user", "content": "I also hold 25k NVDA"}]
    got = intake.read_conversation(msgs, TICKERS)
    assert got.kind == "analyze" and got.ticker == "TSLA"
    assert got.open_positions == [("NVDA", "long", 25_000.0), ("AAPL", "long", 10_000.0)]
    assert "already in the book" in got.reply
    ticket = intake.intent_to_ticket(got, None)
    assert ticket.open_positions == (("NVDA", "long", 25_000.0), ("AAPL", "long", 10_000.0))
