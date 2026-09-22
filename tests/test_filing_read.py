"""Reading filings: the transport, the validation, and the window it is scored over.

The model's judgement cannot be unit tested, and is not meant to be - it is scored
against what happened, on the studies page. What is tested here is everything around
it, because those are the parts that can be quietly wrong: a label outside the
vocabulary accepted anyway, the wrong document read, the outcome window measured from
the bar the filing was already inside.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from nightwatch.data import qwen
from nightwatch.data.sec import readable_documents, strip_html
from nightwatch.features import filing_outcomes as fo
from nightwatch.features.filing_read import CATEGORIES, FilingRead, FilingReadStore, ReadError, parse_read, read_filing
from nightwatch.data.store import Store


# ------------------------------------------------------------------- the transport


def test_the_answer_is_the_content_not_the_reasoning():
    """The model reasons out loud in a separate field. Reading that one gets you the
    model talking to itself instead of its answer."""
    a = qwen._answer({
        "model": "qwen3.8-max",
        "choices": [{"message": {"content": "the answer", "reasoning_content": "let me think about this"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "completion_tokens_details": {"reasoning_tokens": 3}},
    })
    assert a.text == "the answer"
    assert a.usage.prompt_tokens == 10 and a.usage.reasoning_tokens == 3 and a.usage.total == 14


def test_an_empty_answer_is_an_error_not_an_empty_string():
    with pytest.raises(qwen.QwenError):
        qwen._answer({"choices": [{"message": {"content": "   ", "reasoning_content": "hmm"}}]})
    with pytest.raises(qwen.QwenError):
        qwen._answer({"choices": []})


def test_json_survives_a_fenced_block():
    """A reasoning model honours json_object most of the time and wraps it the rest."""
    assert qwen._strip_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert qwen._strip_fence('```\n{"a": 1}\n```') == '{"a": 1}'
    assert qwen._strip_fence('{"a": 1}') == '{"a": 1}'


# ------------------------------------------------------------------- the documents


def test_xbrl_renderings_are_not_the_filing():
    """EDGAR renders each filing into R1.htm, R2.htm ... Those are tables of tagged
    values; reading one gets you "Document Type 8-K Entity Registrant Name ..."."""
    picked = readable_documents(["0001-index.html", "R1.htm", "R12.htm", "amzn-20260908.htm", "amzn.xsd"])
    assert picked == ["amzn-20260908.htm"]


def test_the_press_release_is_read_before_the_shell_that_points_at_it():
    """An 8-K often says little more than "see Exhibit 99.1"; the news is the exhibit."""
    picked = readable_documents(["msft-20260514.htm", "d125909dex991.htm", "0001-index.html"])
    assert picked[0] == "d125909dex991.htm"
    assert "msft-20260514.htm" in picked


def test_script_bodies_do_not_survive_as_words():
    text = strip_html("<p>Hello <b>world</b></p><script>var x = 1;</script><style>p{color:red}</style>&amp; more")
    assert text == "Hello world more"


# ------------------------------------------------------------------ the validation


def good() -> dict:
    return {"category": "leadership", "headline": "The chief financial officer resigned.", "market_moving": "high", "direction": "down", "reason": "no successor named"}


def test_a_valid_answer_becomes_a_read():
    r = parse_read(good(), accession="a-1", ticker="TSLA", model="qwen3.8-max")
    assert r.category == "leadership" and r.market_moving == "high" and r.direction == "down"
    assert r.accession == "a-1" and r.ticker == "TSLA" and r.model == "qwen3.8-max"


@pytest.mark.parametrize(
    "field,value",
    [("category", "very bad news"), ("market_moving", "extreme"), ("direction", "sideways"), ("category", None)],
)
def test_a_label_outside_the_vocabulary_is_refused_not_coerced(field, value):
    """The point of a controlled vocabulary is that the counts mean something. Quietly
    mapping an invented label to the nearest real one invents a category instead."""
    payload = good() | {field: value}
    with pytest.raises(ReadError):
        parse_read(payload, accession="a", ticker="T", model="m")


def test_a_read_with_no_headline_is_refused():
    with pytest.raises(ReadError):
        parse_read(good() | {"headline": "  "}, accession="a", ticker="T", model="m")


def test_labels_are_normalised_before_they_are_checked():
    r = parse_read(good() | {"category": "  Leadership ", "market_moving": "HIGH"}, accession="a", ticker="T", model="m")
    assert r.category == "leadership" and r.market_moving == "high"
    assert r.category in CATEGORIES


class FakeClient:
    model = "fake-1"

    def __init__(self, payload: dict):
        self.payload = payload
        self.seen: list[str] = []

    def chat_json(self, messages, *, system=None, max_tokens=1200):  # noqa: ANN001, ARG002
        self.seen.append(messages[0]["content"])
        return self.payload, qwen.Usage(prompt_tokens=100, completion_tokens=20)


def test_the_prompt_carries_the_filing_and_nothing_about_prices():
    """The read has to be formable from what was public when the filing landed. A price
    in the prompt would make every stored read useless for scoring."""
    c = FakeClient(good())
    read, usage = read_filing(c, accession="a-1", ticker="NVDA", form="8-K", items="5.02", text="The CFO resigned." * 50)
    assert read.ticker == "NVDA" and usage.prompt_tokens == 100
    prompt = c.seen[0]
    assert "NVDA" in prompt and "8-K" in prompt and "5.02" in prompt and "The CFO resigned." in prompt
    for banned in ("close", "%", "return", "price", "USDT"):
        assert banned not in prompt.lower().split("filing text")[0]


def test_a_long_filing_is_trimmed_rather_than_sent_whole():
    from nightwatch.features.filing_read import MAX_TEXT_CHARS

    c = FakeClient(good())
    read_filing(c, accession="a", ticker="T", form="8-K", items=None, text="x" * (MAX_TEXT_CHARS * 3))
    assert len(c.seen[0]) < MAX_TEXT_CHARS * 1.2


def test_reads_are_stored_once_and_updated_in_place(tmp_path):
    with Store(tmp_path / "s.sqlite") as store:
        s = FilingReadStore(store)
        assert s.count() == 0 and s.have() == set()
        r = parse_read(good(), accession="a-1", ticker="TSLA", model="m")
        s.save(r, usage=qwen.Usage(prompt_tokens=100, completion_tokens=20))
        assert s.count() == 1 and s.have() == {"a-1"}
        assert s.tokens_used() == (100, 20)
        got = s.get("a-1")
        assert got is not None and got.headline == r.headline and got.direction == "down"
        # Re-reading the same filing replaces rather than duplicating.
        s.save(parse_read(good() | {"direction": "up"}, accession="a-1", ticker="TSLA", model="m"))
        assert s.count() == 1 and s.get("a-1").direction == "up"
        assert s.get("missing") is None


# ---------------------------------------------------------------------- the window


def frame(closes: list[float], start: datetime) -> pd.DataFrame:
    idx = pd.DatetimeIndex([start + timedelta(hours=i) for i in range(len(closes))])
    return pd.DataFrame({"spot_close": closes, "spot_low": closes, "spot_high": closes}, index=idx)


def test_the_window_runs_from_the_filing_to_the_next_us_open():
    # A Tuesday, 21:00 UTC - after the US close, so the next open is Wednesday morning.
    at = datetime(2026, 9, 15, 21, 0, tzinfo=UTC)
    end, hours = fo.window_after(at)
    assert end > at and 10 < hours < 20
    assert end.weekday() == 2  # Wednesday


def test_a_friday_night_filing_is_carried_to_monday():
    at = datetime(2026, 9, 18, 21, 0, tzinfo=UTC)  # Friday evening
    end, hours = fo.window_after(at)
    assert end.weekday() == 0 and hours > 50  # Monday, more than two days later


def test_the_move_is_measured_from_the_first_bar_after_the_filing():
    """Measuring from the bar the filing landed inside would credit the model with the
    part of the move that happened before the filing was public."""
    start = datetime(2026, 9, 15, 20, 0, tzinfo=UTC)
    # 20:00 100, 21:00 110 (the bar the filing is inside), 22:00 onwards flat at 110.
    f = frame([100.0, 110.0] + [110.0] * 24, start)
    out = fo.outcome_for(f, datetime(2026, 9, 15, 20, 30, tzinfo=UTC))
    assert out is not None
    # Entry is the 21:00 close of 110, so the 10% jump is not counted as the outcome.
    assert out["ret_pct"] == pytest.approx(0.0, abs=1e-9)


def test_a_window_running_past_the_stored_bars_has_no_outcome():
    start = datetime(2026, 9, 15, 20, 0, tzinfo=UTC)
    f = frame([100.0, 101.0, 102.0], start)
    assert fo.outcome_for(f, datetime(2026, 9, 15, 20, 30, tzinfo=UTC)) is None


def test_the_worst_and_best_points_inside_the_window_are_reported():
    start = datetime(2026, 9, 15, 20, 0, tzinfo=UTC)
    closes = [100.0] * 26
    f = frame(closes, start)
    f.iloc[3, f.columns.get_loc("spot_low")] = 90.0
    f.iloc[5, f.columns.get_loc("spot_high")] = 115.0
    out = fo.outcome_for(f, datetime(2026, 9, 15, 20, 30, tzinfo=UTC))
    assert out is not None
    assert out["mae_pct"] == pytest.approx(-10.0) and out["mfe_pct"] == pytest.approx(15.0)
    assert out["ret_pct"] == pytest.approx(0.0)


# --------------------------------------------------------------- the label summary


def outcomes_frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame([{"ticker": t, "market_moving": m, "ret_pct": r} for t, m, r in rows])


def test_a_label_with_too_few_filings_gets_no_distribution():
    """Quoting a 5th percentile off nine nights is quoting the second-worst of nine."""
    df = outcomes_frame([("T", "high", float(i)) for i in range(9)])
    assert fo.summarise_labels(df) == []


def test_the_distribution_is_of_the_nights_that_followed_that_label():
    rng = np.random.default_rng(0)
    rows = [("T", "high", float(x)) for x in rng.normal(0, 4, 60)]
    rows += [("T", "low", float(x)) for x in rng.normal(0, 1, 60)]
    stats = {s.label: s for s in fo.summarise_labels(outcomes_frame(rows), min_n=40)}
    assert set(stats) == {"high", "low"}
    assert stats["high"].n == 60 and stats["low"].n == 60
    # The wide label has the worse tail and the bigger average move.
    assert stats["high"].p5_pct < stats["low"].p5_pct
    assert stats["high"].mean_abs_pct > stats["low"].mean_abs_pct


def test_label_stats_round_trip_and_replace(tmp_path):
    with Store(tmp_path / "s.sqlite") as store:
        assert fo.load_labels(store) == {}
        rows = [("T", "high", float(i - 30)) for i in range(60)]
        assert fo.save_labels(store, fo.summarise_labels(outcomes_frame(rows), min_n=40)) == 1
        got = fo.load_labels(store)
        assert set(got) == {"high"} and got["high"].n == 60
        # Recomputing replaces wholesale rather than accumulating stale labels.
        rows2 = [("T", "low", 0.5) for _ in range(60)]
        fo.save_labels(store, fo.summarise_labels(outcomes_frame(rows2), min_n=40))
        assert set(fo.load_labels(store)) == {"low"}


def test_a_report_note_carries_the_models_words_and_historys_numbers(tmp_path):
    """The split that makes the panel honest: the label is the model's, the percentile
    is not. A note that sourced both from the model would be an opinion wearing a
    number, which is the thing this product exists not to print."""
    from nightwatch.pipeline.analyze import FilingNote

    n = FilingNote(
        ticker="TSLA", accepted_at=datetime(2026, 9, 22, 1, 0, tzinfo=UTC), form="8-K", items="2.02",
        hours_ago=4.6, inside_window=True, market_was_shut=True,
        category="results", headline="Reports fourth quarter results.", market_moving="high",
        label_n=146, label_p5_pct=-6.6, label_median_pct=-0.68, label_mean_abs_pct=3.15,
    )
    d = n.to_dict()
    assert d["accepted_at"].startswith("2026-09-22")
    assert d["market_moving"] == "high" and d["label_n"] == 146
    # No direction anywhere: the model offers one and it measured as a coin.
    assert "direction" not in d
