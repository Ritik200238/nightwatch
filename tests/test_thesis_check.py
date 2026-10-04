"""The trader's reason against the stored headlines: retrieval is point-in-time, the model
only names ids, and nothing it says becomes a quote unless it was one of ours."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from nightwatch.data.store import Store
from nightwatch.decision import thesis_check as tc
from nightwatch.time_utils import UTC, to_epoch_ms

AS_OF = datetime(2026, 10, 3, 20, tzinfo=UTC)


def _news(store: Store, nid: str, title: str, *, days_ago: float, tickers=("NVDA",), seen_after: float = 0.0) -> None:
    t = AS_OF - timedelta(days=days_ago)
    store._conn.execute(
        "INSERT INTO news (source, id, published_at, title, link, summary, tickers, observed_at) VALUES ('cnbc_top', ?, ?, ?, ?, '', ?, ?)",
        (nid, to_epoch_ms(t), title, f"https://example.com/{nid}", json.dumps(list(tickers)), to_epoch_ms(t + timedelta(days=seen_after))),
    )


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "nw.sqlite")
    from nightwatch.features.filing_read import FilingReadStore

    FilingReadStore(store)  # creates filing_reads, as the box has it

    _news(store, "a", "Nvidia breaks through to new record highs", days_ago=1)
    _news(store, "b", "Amazon is hiking chip-rental prices", days_ago=2, tickers=("AMZN",))
    _news(store, "c", "Nvidia record run ends as chip stocks slide", days_ago=20)  # outside the window
    _news(store, "d", "Nvidia record high, reported after the report was taken", days_ago=0.5, seen_after=1.0)  # not known then
    return store


def test_retrieval_is_the_token_in_the_window_as_known_then(tmp_path):
    store = _store(tmp_path)
    items = tc.candidates(store._conn, "NVDA", AS_OF, "record highs")
    assert [i.title for i in items] == ["Nvidia breaks through to new record highs"]
    assert items[0].id == "N1" and items[0].link == "https://example.com/a"


def test_the_model_names_ids_and_the_quote_is_ours(tmp_path):
    store = _store(tmp_path)

    def parse(system, user):
        assert "N1" in user and "REASON: Nvidia hit record highs" in user
        return tc._Out(claims=[
            tc._ClaimOut(claim="Nvidia hit record highs", status="supported", evidence=["N1", "N9"], note="N1 reports it."),
            tc._ClaimOut(claim="Fed is cutting rates tomorrow", status="supported", evidence=["N7"]),  # no real id
            tc._ClaimOut(claim="Apple bought Disney", status="contradicted", evidence=["N1"]),  # not in the reason
        ])

    got = tc.check(store._conn, ticker="nvda", thesis="Nvidia hit record highs; the Fed is cutting rates", as_of=AS_OF, parse=parse, model="m")
    assert got.state == "checked" and got.method == "model" and got.model == "m"
    assert [(c.claim, c.status) for c in got.claims] == [("Nvidia hit record highs", "supported"), ("Fed is cutting rates tomorrow", "not_found")]
    first = got.claims[0]
    assert [e.title for e in first.evidence] == ["Nvidia breaks through to new record highs"]  # N9 was never offered
    assert got.claims[1].evidence == []


def test_without_a_model_it_lists_related_headlines_and_never_says_supported(tmp_path):
    store = _store(tmp_path)
    got = tc.check(store._conn, ticker="NVDA", thesis="Nvidia record highs, momentum", as_of=AS_OF)
    assert got.method == "keyword"
    assert got.claims[0].status == "related" and got.claims[0].evidence[0].id == "N1"


def test_a_failing_model_falls_back_to_keywords(tmp_path):
    store = _store(tmp_path)

    def broken(system, user):
        raise TimeoutError("gateway")

    assert tc.check(store._conn, ticker="NVDA", thesis="record highs", as_of=AS_OF, parse=broken).method == "keyword"


def test_no_thesis_and_no_items_are_said_plainly(tmp_path):
    store = _store(tmp_path)
    assert tc.check(store._conn, ticker="NVDA", thesis="  ", as_of=AS_OF).state == "no_thesis"
    assert tc.check(store._conn, ticker="TSLA", thesis="deliveries beat", as_of=AS_OF).state == "no_items"


def test_chinese_reasons_match_by_character_pairs():
    assert tc._words("英伟达创新高") & tc._words("英伟达股价创新高")


def test_filings_count_with_the_models_read_headline(tmp_path):
    store = _store(tmp_path)
    t = to_epoch_ms(AS_OF - timedelta(days=3))
    store._conn.execute(
        "INSERT INTO filings (ticker, accession, cik, form, accepted_at, filed_date, description, items, source, observed_at) "
        "VALUES ('NVDA', 'acc1', '1', '8-K', ?, ?, 'Current report', '[]', 'edgar', ?)", (t, t, t))
    store._conn.execute(
        "INSERT INTO filing_reads (accession, ticker, model, category, market_moving, direction, headline, reason, read_at) "
        "VALUES ('acc1', 'NVDA', 'm', 'deal', 'high', 'up', 'Nvidia signs a supply deal with a hyperscaler', 'r', ?)", (t,))
    items = tc.candidates(store._conn, "NVDA", AS_OF, "supply deal")
    assert items[0].id == "F1" and items[0].title == "8-K: Nvidia signs a supply deal with a hyperscaler" and items[0].source == "SEC EDGAR"


def test_a_database_without_filing_reads_still_checks_news(tmp_path):
    store = Store(tmp_path / "bare.sqlite")
    _news(store, "a", "Nvidia breaks through to new record highs", days_ago=1)
    assert [i.id for i in tc.candidates(store._conn, "NVDA", AS_OF, "record")] == ["N1"]


def test_the_field_names_the_model_actually_used_are_accepted():
    """Qwen answered {"judgment": ..., "items": [...]} on the box; that must still count."""
    out = tc._Out.model_validate({"claims": [{"claim": "Nvidia hit record highs", "judgment": "Supported", "items": ["N2", "N3", "N4", "N5"], "note": "x" * 500}]})
    c = out.claims[0]
    assert c.status == "supported" and c.evidence == ["N2", "N3", "N4"]
    assert tc._Out.model_validate({"claims": [{"claim": "x", "verdict": "weird"}]}).claims[0].status == "not_found"


def test_notes_do_not_show_internal_ids():
    assert tc._plain_note("N2 states Nvidia broke through; both N1 and F3 agree.", False) == "The headline states Nvidia broke through; both the headline and the filing agree."
    assert tc._plain_note("Headline N3 reports record highs", False) == "The headline reports record highs"
    assert tc._plain_note("N8标题明确指出", True) == "该新闻明确指出"


def test_the_chat_questions_that_ask_for_it():
    for q in ("is my reason right?", "Check my thesis", "fact check the news", "is that news true?", "我的理由对吗", "核实一下新闻"):
        assert tc.ASKS.search(q), q
    for q in ("what if it gaps down 10%?", "halve it", "why?", "what's the safest way to hold it?"):
        assert not tc.ASKS.search(q), q


def test_the_chat_reply_quotes_stored_headlines_and_says_not_found_is_not_false(tmp_path):
    store = _store(tmp_path)

    def parse(system, user):
        return tc._Out(claims=[tc._ClaimOut(claim="Nvidia hit record highs", status="supported", evidence=["N1"]),
                               tc._ClaimOut(claim="AI demand is strong", status="not_found")])

    got = tc.check(store._conn, ticker="NVDA", thesis="Nvidia hit record highs, AI demand is strong", as_of=AS_OF, parse=parse).to_dict()
    text = tc.reply_text(got)
    assert '- In the news: "Nvidia hit record highs" - Nvidia breaks through to new record highs (cnbc_top, 2026-10-02)' in text
    assert '- Not in our feeds: "AI demand is strong"' in text and "not that it is false" in text
    assert "no written reason" in tc.reply_text(None)
    assert "新闻中有" in tc.reply_text(got, "zh")
