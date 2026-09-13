"""Post-mortems: classify a matured forecast, write one honest sentence, recall it later."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from nightwatch.data.store import Store
from nightwatch.journal.journal import Journal
from nightwatch.journal.postmortem import Classification, LessonBook, build, classify

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _row(**kw) -> pd.Series:
    base = dict(
        id=1, kind="ticket", ticker="TSLA", side="long", notional=20_000.0, as_of=NOW, horizon_h=48.0,
        p5=-6.0, p25=-2.0, p50=0.0, p75=2.0, p95=6.0, verdict="REDUCE_TO", recommended_notional=16_000.0,
        ret_pct=-1.0, mae_pct=-2.5, matured_at=NOW + timedelta(hours=48),
    )
    base.update(kw)
    return pd.Series(base)


def test_classification_follows_the_stated_band():
    assert classify(-7.0, -6.0, -2.0, 2.0, 6.0) is Classification.WORSE_THAN_STRESS
    assert classify(-3.0, -6.0, -2.0, 2.0, 6.0) is Classification.BAD_TAIL
    assert classify(0.5, -6.0, -2.0, 2.0, 6.0) is Classification.AS_EXPECTED
    assert classify(4.0, -6.0, -2.0, 2.0, 6.0) is Classification.GOOD_TAIL
    assert classify(9.0, -6.0, -2.0, 2.0, 6.0) is Classification.BETTER_THAN_FORECAST
    assert classify(9.0, None, None, None, None) is Classification.NO_DISTRIBUTION


def test_a_breach_is_written_plainly_and_is_notable():
    lesson = build(_row(ret_pct=-7.4, mae_pct=-8.1), {"labels": {"bucket": "weekend", "regime_label": "hostile"}})
    assert lesson.classification is Classification.WORSE_THAN_STRESS
    assert lesson.breached_low and lesson.touched_stress and not lesson.recovered
    assert lesson.notable
    assert "-7.40%" in lesson.text and "-6.00%" in lesson.text
    assert lesson.bucket == "weekend" and lesson.regime_label == "hostile"


def test_a_dip_through_the_stress_level_that_recovers_says_so():
    lesson = build(_row(ret_pct=-1.0, mae_pct=-7.0), {})
    assert lesson.touched_stress and lesson.recovered
    assert "came back" in lesson.text


def test_the_size_cut_is_valued_in_money_only_when_it_mattered():
    saved = build(_row(ret_pct=-5.0), {})  # cut 4,000 of a position that fell 5%
    assert saved.size_effect_quote == pytest.approx(200.0)
    assert "avoided about 200 USDT" in saved.text

    cost = build(_row(ret_pct=+5.0), {})  # the same cut, on a move that went the right way
    assert cost.size_effect_quote == pytest.approx(-200.0)
    assert "cost about 200 USDT" in cost.text

    untouched = build(_row(recommended_notional=20_000.0), {})
    assert untouched.size_effect_quote is None and "the desk cut" not in untouched.text.lower()


def test_an_ordinary_outcome_is_not_worth_showing():
    assert not build(_row(ret_pct=0.5, mae_pct=-1.0, recommended_notional=20_000.0), {}).notable


@pytest.fixture
def book(tmp_path):
    store = Store(tmp_path / "j.sqlite")
    journal = Journal(store)
    q = {"p5": -6.0, "p25": -2.0, "p50": 0.0, "p75": 2.0, "p95": 6.0}
    for ticker, bucket, ret, days in [
        ("TSLA", "weekend", -7.4, 10),   # a breach on the same token
        ("TSLA", "weeknight", 0.4, 9),   # dull
        ("NVDA", "weekend", -8.0, 8),    # a breach in the same bucket, other token
        ("AAPL", "us_regular", 1.0, 1),  # recent but unrelated
    ]:
        at = NOW - timedelta(days=days)
        fid = journal.record_forecast(
            kind="replay", ticker=ticker, side="long", notional=10_000.0, as_of=at, bar_ts=at, horizon_h=24.0,
            entry_price=100.0, snapshot_hash="h", analog_n=40, analog_scope="same_ticker", quantiles=q, es5=None,
            mc_p5=None, mc_p95=None, verdict=None, recommended_notional=None,
            payload={"labels": {"bucket": bucket, "regime_label": "normal"}},
        )
        with store._conn:
            store._conn.execute(
                "INSERT INTO forecast_outcomes (forecast_id, matured_at, exit_ts, exit_price, ret_pct, mfe_pct, mae_pct, max_abs_basis_bps) VALUES (?,?,?,?,?,?,?,?)",
                (fid, int((at + timedelta(days=1)).timestamp() * 1000), int((at + timedelta(days=1)).timestamp() * 1000), 100.0, ret, 1.0, ret - 1, None),
            )
    yield LessonBook(journal)
    store.close()


def test_writing_is_idempotent_and_recall_prefers_what_taught_something(book):
    assert book.write_pending() == 4
    assert book.write_pending() == 0  # nothing left to write

    top = book.recall(ticker="TSLA", bucket="weekend", regime_label="normal", as_of=NOW, limit=3)
    assert top[0].ticker == "TSLA" and top[0].breached_low  # same token and a breach wins
    assert [x.ticker for x in top] == ["TSLA", "NVDA", "TSLA"]  # the dull TSLA one ranks last
    assert book.summary()["worse_than_stress"] == 2


def test_a_lesson_cannot_be_read_before_its_outcome_existed(book):
    book.write_pending()
    # Outcomes land a day after the call, so only the oldest lesson exists at this instant.
    early = NOW - timedelta(days=8, hours=12)
    seen = book.recall(ticker="TSLA", bucket="weekend", as_of=early)
    assert len(seen) == 1 and seen[0].ret_pct == pytest.approx(-7.4)


def test_resetting_replays_takes_their_lessons_with_them(book):
    """Lessons point at forecasts, so a reset has to clear them or the delete is refused."""
    assert book.write_pending() == 4
    removed = book.journal.delete_replays("TSLA")
    assert removed == 2
    left = {row[0] for row in book.journal._conn.execute("SELECT ticker FROM lessons").fetchall()}
    assert "TSLA" not in left and "NVDA" in left
