"""Portfolio view: exposure, measured correlation, and whether the book is one bet."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from nightwatch.decision.portfolio import MIN_OVERLAP_HOURS, Position, correlations, evaluate

START = datetime(2026, 1, 1, tzinfo=UTC)


def frame(n: int = 1200, *, seed: int = 1, shared: np.ndarray | None = None, beta: float = 0.0) -> pd.DataFrame:
    """Hourly closes. With ``shared`` and a beta, a token that moves with the market."""
    rng = np.random.default_rng(seed)
    own = rng.normal(0, 0.004, n)
    rets = own if shared is None else beta * shared + np.sqrt(max(0.0, 1 - beta**2)) * own
    idx = pd.date_range(START, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"spot_close": 100 * np.exp(np.cumsum(rets))}, index=idx)


@pytest.fixture
def market():
    rng = np.random.default_rng(7)
    return rng.normal(0, 0.004, 1200)


def test_exposure_and_concentration_are_plain_arithmetic():
    positions = [Position("TSLA", "long", 30_000), Position("NVDA", "long", 10_000), Position("AAPL", "short", 10_000)]
    rep = evaluate(positions, None, {}, equity=100_000)
    assert rep.after.gross_quote == 50_000 and rep.after.net_quote == 30_000
    assert rep.after.gross_pct_of_equity == pytest.approx(50.0)
    assert rep.after.largest_name == "TSLA" and rep.after.largest_pct_of_gross == pytest.approx(60.0)
    assert rep.after.top3_pct_of_gross == pytest.approx(100.0)


def test_an_empty_book_is_not_an_error():
    rep = evaluate([], None, {}, equity=100_000)
    assert rep.after.gross_quote == 0 and rep.after.tail_loss_quote is None


def test_positions_without_history_are_counted_but_not_risked():
    rep = evaluate([Position("WHO", "long", 10_000)], None, {}, equity=100_000)
    assert rep.after.gross_quote == 10_000
    assert rep.after.tail_loss_quote is None
    assert any("no stored history for WHO" in n for n in rep.notes)


def test_correlated_names_do_not_diversify(market):
    frames = {"A": frame(seed=1, shared=market, beta=0.95), "B": frame(seed=2, shared=market, beta=0.95)}
    book = [Position("A", "long", 10_000), Position("B", "long", 10_000)]
    rep = evaluate(book, None, frames, equity=100_000, horizon_h=24)
    assert rep.after.diversification_ratio is not None and rep.after.diversification_ratio > 0.85
    assert any("one bet" in n for n in rep.notes)


def test_independent_names_do_diversify(market):
    frames = {"A": frame(seed=11), "B": frame(seed=12)}
    book = [Position("A", "long", 10_000), Position("B", "long", 10_000)]
    rep = evaluate(book, None, frames, equity=100_000, horizon_h=24)
    assert rep.after.diversification_ratio < 0.85
    assert not any("one bet" in n for n in rep.notes)


def test_a_hedge_shrinks_the_book_tail(market):
    """The same token long and short is not a bet at all."""
    f = frame(seed=3, shared=market, beta=0.9)
    frames = {"A": f, "B": frame(seed=4, shared=market, beta=0.9)}
    longs = evaluate([Position("A", "long", 10_000), Position("B", "long", 10_000)], None, frames, equity=100_000)
    hedged = evaluate([Position("A", "long", 10_000), Position("B", "short", 10_000)], None, frames, equity=100_000)
    assert abs(hedged.after.tail_loss_quote) < abs(longs.after.tail_loss_quote)


def test_the_marginal_trade_is_the_difference(market):
    frames = {"A": frame(seed=21, shared=market, beta=0.9), "B": frame(seed=22, shared=market, beta=0.9)}
    rep = evaluate([Position("A", "long", 10_000)], Position("B", "long", 10_000), frames, equity=100_000)
    assert rep.before.gross_quote == 10_000 and rep.after.gross_quote == 20_000
    assert rep.adds_tail_quote is not None and rep.adds_tail_quote < 0  # a bigger loss in the tail
    assert rep.mean_correlation_to_book is not None and rep.mean_correlation_to_book > 0.5
    assert any("adds size, not diversification" in n for n in rep.notes)


def test_correlation_is_refused_without_enough_overlap():
    short = frame(n=MIN_OVERLAP_HOURS // 2, seed=5)
    pairs = correlations([Position("A", "long", 1), Position("B", "long", 1)], {"A": short, "B": short}, horizon_h=24)
    assert pairs[0].correlation is None and pairs[0].overlap_hours < MIN_OVERLAP_HOURS


def test_short_history_is_reported_rather_than_guessed():
    frames = {"A": frame(n=100, seed=6), "B": frame(seed=7)}
    rep = evaluate([Position("A", "long", 1_000), Position("B", "long", 1_000)], None, frames, equity=50_000)
    assert any("too short for a tail" in n for n in rep.notes)
