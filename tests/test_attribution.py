"""Which position carries the book's tail, and what removing it would do."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from nightwatch.decision.attribution import attribute
from nightwatch.decision.portfolio import Position

START = datetime(2026, 1, 1, tzinfo=UTC)


def frame(n: int = 1500, *, vol: float = 0.004, seed: int = 1, shared: np.ndarray | None = None, beta: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    own = rng.normal(0, vol, n)
    rets = own if shared is None else beta * shared + np.sqrt(max(0.0, 1 - beta**2)) * own
    idx = pd.date_range(START, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"spot_close": 100 * np.exp(np.cumsum(rets))}, index=idx)


def test_the_parts_add_up_to_the_whole():
    frames = {"A": frame(seed=1), "B": frame(seed=2), "C": frame(seed=3)}
    book = [Position("A", "long", 10_000), Position("B", "long", 20_000), Position("C", "short", 5_000)]
    a = attribute(book, frames, horizon_h=24)
    total = sum(c.component_quote for c in a.contributions)
    assert total == pytest.approx(a.book_tail_quote, rel=1e-9)
    assert sum(c.component_share for c in a.contributions) == pytest.approx(1.0, rel=1e-9)


def test_the_volatile_name_carries_more_than_its_weight():
    frames = {"CALM": frame(vol=0.002, seed=4), "WILD": frame(vol=0.012, seed=5)}
    book = [Position("CALM", "long", 20_000), Position("WILD", "long", 10_000)]
    a = attribute(book, frames, horizon_h=24)
    wild = next(c for c in a.contributions if c.ticker == "WILD")
    calm = next(c for c in a.contributions if c.ticker == "CALM")
    assert wild.share_of_gross < calm.share_of_gross  # smaller position
    assert wild.component_share > calm.component_share  # bigger share of the bad case
    assert a.worst_contributor.ticker == "WILD"


def test_a_hedge_shows_up_as_improving_the_tail():
    """A short in a correlated name should make the book's tail better, not worse."""
    rng = np.random.default_rng(9)
    market = rng.normal(0, 0.005, 1500)
    frames = {"A": frame(seed=6, shared=market, beta=0.95), "H": frame(seed=7, shared=market, beta=0.95)}
    a = attribute([Position("A", "long", 20_000), Position("H", "short", 10_000)], frames, horizon_h=24)
    hedge = next(c for c in a.contributions if c.ticker == "H")
    assert hedge.component_quote > 0  # it makes money when the book is at its worst
    assert hedge.marginal_quote > 0  # removing it would make the tail worse


def test_removing_the_risk_driver_improves_the_tail():
    frames = {"CALM": frame(vol=0.002, seed=8), "WILD": frame(vol=0.012, seed=10)}
    a = attribute([Position("CALM", "long", 10_000), Position("WILD", "long", 10_000)], frames, horizon_h=24)
    wild = next(c for c in a.contributions if c.ticker == "WILD")
    assert wild.marginal_quote < 0  # the book's tail is worse because this is held


def test_missing_history_is_unknown_not_zero():
    a = attribute([Position("A", "long", 1_000), Position("GHOST", "long", 1_000)], {"A": frame(seed=11)}, horizon_h=24)
    ghost = next(c for c in a.contributions if c.ticker == "GHOST")
    assert ghost.component_quote is None and ghost.note
    assert any("GHOST" in n for n in a.notes)


def test_nothing_to_attribute_without_shared_history():
    a = attribute([Position("A", "long", 1_000)], {"A": frame(n=50, seed=12)}, horizon_h=24)
    assert a.book_tail_quote is None
    assert all(c.component_quote is None for c in a.contributions)
