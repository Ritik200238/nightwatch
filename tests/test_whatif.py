"""Counterfactuals, and the line between naming one and computing one.

A what-if runs the desk again. That makes it the one place where a model's output turns
into a real analysis rather than a sentence about one, so the tests here are mostly
about restraint: what the model is allowed to change, what happens to a change it
invented, and whether the comparison a trader reads can contain a number that was not
copied out of one of the two reports.
"""

import threading
from types import SimpleNamespace

import pytest

from nightwatch.analog.engine import AnalogConfig
from nightwatch.api import whatif
from nightwatch.api.llm import ParsedChange, parse_change
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry
from nightwatch.decision.ticket import HorizonKind, Side, TradeTicket
from nightwatch.pipeline.analyze import AnalysisContext
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

TICKET = {
    "ticker": "TSLA", "side": "long", "notional_quote": 20000.0, "account_equity_quote": 200000.0,
    "horizon_kind": "next_open", "horizon_hours": None, "stop_price": None,
    "thesis": "strength carries", "invalidation": "close below the average",
}


def report(**over) -> dict:  # noqa: ANN003
    """A report skeleton with only the fields the comparison reads."""
    base = {
        "ticket": dict(TICKET), "as_of": "2026-09-19T02:00:00+00:00", "primary_horizon": "8h",
        "analog": {
            "scope": "same_ticker", "lens": None,
            "result": {"ok": True, "reason": ""},
            "horizons": {"8h": {"cohort": {"n": 40, "median_pct": 0.2, "p5": -3.3}, "p5_adjusted": -3.3}},
        },
        "verdict": {"verdict": "GO", "recommended_notional": 20000.0},
        "sizing": {"binding_cap": "regime"},
        "forecast_id": 7,
    }
    for k, v in over.items():
        base[k] = v
    return base


# ------------------------------------------------------------------- the routing


@pytest.mark.parametrize("q", [
    "what if I held it for 12 hours?",
    "what about NVDA?",
    "was it worse on earnings nights?",
    "only weekends please",
    "would it look different short?",
    "how about the end of the window instead",
])
def test_counterfactual_questions_are_routed_to_a_re_run(q):
    assert whatif.looks_like_a_what_if(q, tickers=("TSLA", "NVDA"), current="TSLA")


@pytest.mark.parametrize("q", [
    "why not bigger?",
    "can I actually get out?",
    "has this setup burned me before?",
    "talk me out of it",
])
def test_questions_the_report_already_answers_are_not(q):
    assert not whatif.looks_like_a_what_if(q, tickers=("TSLA", "NVDA"), current="TSLA")


def test_the_token_already_on_screen_is_not_a_change():
    """"How did TSLA do" about a TSLA report is a question, not a counterfactual."""
    assert not whatif.looks_like_a_what_if("tsla history", tickers=("TSLA", "NVDA"), current="TSLA")
    assert whatif.looks_like_a_what_if("nvda history", tickers=("TSLA", "NVDA"), current="TSLA")


def test_a_phrase_from_a_lens_definition_routes_without_being_listed_twice():
    """The router reads the lens vocabulary, so a condition added there is reachable
    from a sentence without a second list being kept in step by hand."""
    said = next(x.says[0] for x in __import__("nightwatch.analog.lens", fromlist=["x"]).LENSES if x.name == "basis_stretched")
    assert whatif.looks_like_a_what_if(f"show me {said}")


# -------------------------------------------------------------------- the change


def test_an_unset_field_means_as_it_was():
    t = whatif.Change(horizon_hours=12.0).apply_to(whatif.ticket_from(report()))
    assert t.ticker == "TSLA" and t.side is Side.LONG and t.notional_quote == 20000.0
    assert t.horizon_hours == 12.0 and t.horizon_kind is HorizonKind.HOURS


def test_a_change_that_sets_nothing_is_not_a_what_if():
    assert whatif.Change().empty
    assert not whatif.Change(lenses=("weekend",)).empty


def test_lens_names_the_model_invented_never_reach_the_engine():
    t = whatif.Change(lenses=("weekend", "when_it_felt_scary")).apply_to(whatif.ticket_from(report()))
    assert t.lenses == ("weekend",)


def test_the_written_plan_survives_the_rebuild():
    """The gate refuses a ticket with no plan. A what-if that lost the trader's thesis
    would come back refused for a reason that has nothing to do with the question."""
    t = whatif.ticket_from(report())
    assert t.thesis and t.invalidation


def test_a_report_without_a_ticket_cannot_be_re_run():
    assert whatif.ticket_from({}) is None
    assert whatif.ticket_from({"ticket": {"ticker": "TSLA", "side": "sideways"}}) is None


def test_the_re_run_answers_the_same_moment():
    """Running a what-if against the current hour would vary the moment as well as the
    question, and the difference could not be attributed to either."""
    assert whatif.as_of_of(report()).isoformat() == "2026-09-19T02:00:00+00:00"
    assert whatif.as_of_of({"as_of": "not a time"}) is None and whatif.as_of_of({}) is None


# ---------------------------------------------------------------- the comparison


def test_the_comparison_names_what_moved():
    after = report(
        analog={
            "scope": "pooled", "lens": {"names": ["earnings_soon"], "applied": True, "refused": ""},
            "result": {"ok": True},
            "horizons": {"8h": {"cohort": {"n": 28, "median_pct": -1.2}, "p5_adjusted": -10.6}},
        },
        verdict={"verdict": "CUT", "recommended_notional": 6200.0},
        sizing={"binding_cap": "risk_budget"},
    )
    text = whatif.compare(report(), after, whatif.Change(lenses=("earnings_soon",))).text
    assert "28 past moments instead of 40" in text
    assert "pooled history" in text, "a widened search is a different cohort and has to say so"
    assert "-3.3%" in text and "-10.6%" in text
    assert "GO at 20,000 USDT to CUT at 6,200 USDT" in text and "risk budget" in text


def test_a_verdict_that_did_not_move_is_said_to_have_not_moved():
    text = whatif.compare(report(), report(), whatif.Change(lenses=("weekend",))).text
    assert "The verdict is unchanged: GO at 20,000 USDT" in text
    # "Moves from -3.3% to -3.3%" is true and reads like a mistake.
    assert "moves from" not in text and "are unchanged, at +0.2% and -3.3%" in text


def test_a_lens_that_could_not_be_honoured_is_refused_not_answered():
    """The re-run falls back to the unfiltered history when a lens is too rare. Printing
    that answer under the question's name would be the worst outcome available."""
    after = report(analog={
        "scope": "same_ticker",
        "lens": {"names": ["fomc_soon", "high_volatility"], "applied": False, "refused": "only 44 past hours match FOMC ahead and volatile"},
        "result": {"ok": True},
        "horizons": {"8h": {"cohort": {"n": 40, "median_pct": 0.2}, "p5_adjusted": -3.3}},
    })
    text = whatif.compare(report(), after, whatif.Change(lenses=("fomc_soon", "high_volatility"))).text
    assert "cannot answer that one" in text and "only 44 past hours" in text
    assert "-3.3" not in text, "the unfiltered answer must not be quoted as the narrow one"


def test_a_changed_holding_period_names_both_windows():
    """The two medians are measured over different things once the horizon moves, and a
    sentence that names only the new one compares them as though they were not."""
    after = report(primary_horizon="6h", analog={
        "scope": "same_ticker", "lens": None, "result": {"ok": True},
        "horizons": {"6h": {"cohort": {"n": 27, "median_pct": 0.0}, "p5_adjusted": -2.9}},
    })
    text = whatif.compare(report(), after, whatif.Change(horizon_hours=6.0)).text
    assert "from +0.2% over 8h to 0.0% over 6h" in text


def test_a_re_run_with_no_cohort_says_so_rather_than_comparing_nothing():
    after = report(analog={
        "scope": "same_ticker", "lens": None,
        "result": {"ok": False, "reason": "only 6 distinct episodes (need 10)"},
        "horizons": {},
    })
    text = whatif.compare(report(), after, whatif.Change(ticker="NVDA")).text
    assert "not enough distinct past moments" in text and "only 6 distinct episodes" in text


def test_every_number_in_the_comparison_comes_from_one_of_the_two_reports():
    """The point of assembling this text in code is that there is no step at which a
    number could be invented. If that ever stops being true this test fails."""
    from nightwatch.api.llm import unverified_numbers

    before, after = report(), report(verdict={"verdict": "CUT", "recommended_notional": 6200.0})
    text = whatif.compare(before, after, whatif.Change(horizon_hours=12.0)).text
    assert unverified_numbers(text, f"{before} {after} 12") == []


# ------------------------------------------------------------- the model's share


class FakeProvider:
    name, model, narrates = "fake", "fake-1", False

    def __init__(self, parsed):
        self.parsed = parsed
        self.calls: list[dict] = []

    def parse(self, messages, *, system, schema, max_tokens=2000):  # noqa: ANN001, ANN003
        self.calls.append({"messages": messages, "system": system, "schema": schema})
        return self.parsed

    def write(self, *, system, user, max_tokens=1500):  # noqa: ANN001, ANN003
        raise AssertionError("a what-if is assembled from the reports, never written")


def test_a_token_the_desk_has_no_data_for_is_not_a_runnable_what_if():
    """Running the original token under a name the trader did not ask about would answer
    the wrong question and look like the right one."""
    got = parse_change(FakeProvider(ParsedChange(ticker="DOGE")), "what about DOGE?", TICKET, ["TSLA", "NVDA"])
    assert got.empty


def test_the_token_already_on_screen_is_dropped_as_a_change():
    got = parse_change(FakeProvider(ParsedChange(ticker="tsla")), "and TSLA?", TICKET, ["TSLA", "NVDA"])
    assert got.ticker is None and got.empty


def test_the_side_already_on_the_ticket_is_dropped_as_a_change():
    got = parse_change(FakeProvider(ParsedChange(side="long")), "still long?", TICKET, ["TSLA"])
    assert got.empty


def test_the_model_is_shown_the_menu_and_the_trade_it_is_varying():
    p = FakeProvider(ParsedChange(lenses=["earnings_soon"]))
    got = parse_change(p, "only earnings nights", TICKET, ["TSLA", "NVDA"])
    assert got.lenses == ("earnings_soon",)
    system = p.calls[0]["system"]
    assert '"earnings_soon"' in system and "TSLA" in system and "NVDA" in system


def test_a_provider_that_returns_nothing_is_not_a_what_if():
    assert parse_change(FakeProvider(None), "what if?", TICKET, ["TSLA"]).empty


def test_a_negative_horizon_is_not_a_holding_period():
    assert parse_change(FakeProvider(ParsedChange(horizon_hours=-4.0)), "what if?", TICKET, ["TSLA"]).empty


# ------------------------------------------------------------------ end to end


@pytest.fixture
def state(seeded_store):  # noqa: F811
    store = Store(seeded_store)
    entries = [UniverseEntry(t, f"R{t}USDT", f"{t}USDT", t, True) for t in ("TSLA", "NVDA", "AAPL")]
    ctx = AnalysisContext(store=store, entries=entries, analog_config=AnalogConfig(k=30, min_matches=10, min_separation_h=36, min_age_h=96))
    kept: dict[int, dict] = {}

    def keep(payload):  # noqa: ANN001, ANN202
        key = -(len(kept) + 1)
        payload["forecast_id"] = key
        kept[key] = payload
        return key

    yield SimpleNamespace(ctx=ctx, lock=threading.Lock(), keep_hypothetical=keep, kept=kept)
    store.close()


def _seed_report(state) -> dict:  # noqa: ANN001
    from nightwatch.pipeline.analyze import analyze

    ticket = TradeTicket(
        ticker="TSLA", side=Side.LONG, notional_quote=20_000.0, account_equity_quote=200_000.0,
        horizon_kind=HorizonKind.NEXT_OPEN, thesis="strength carries", invalidation="close below the average",
    )
    return analyze(state.ctx, ticket, as_of=AS_OF, record=False).to_dict()


def test_a_what_if_runs_the_desk_again_and_is_never_journalled(state, monkeypatch):
    from nightwatch.api import app as app_mod

    provider = FakeProvider(ParsedChange(horizon_hours=6.0))
    monkeypatch.setattr("nightwatch.api.providers.select", lambda preferred=None: provider)
    before = _seed_report(state)

    out = app_mod._what_if(state, before, "what if I only held it for 6 hours?")
    assert out is not None and out["mode"] == "what_if"
    assert out["ticket"]["horizon_hours"] == 6.0 and out["ticket"]["ticker"] == "TSLA"
    # A forecast nobody took is not scored, and its key says so.
    assert out["report"]["forecast_id"] < 0 and out["report"]["forecast_id"] in state.kept
    # Same night, different question.
    assert out["report"]["as_of"] == before["as_of"]
    assert out["unverified_numbers"] == [] and out["written_by"] == "rules"


def test_a_question_about_the_trade_as_it_stands_is_handed_back(state, monkeypatch):
    """An empty change is the model saying "this is not a what-if", and the answer then
    belongs to the layer that reads the report rather than to a needless re-run."""
    from nightwatch.api import app as app_mod

    monkeypatch.setattr("nightwatch.api.providers.select", lambda preferred=None: FakeProvider(ParsedChange()))
    before = _seed_report(state)
    assert app_mod._what_if(state, before, "what if I am wrong about all of this?") is None


def test_a_question_with_no_counterfactual_in_it_never_costs_a_model_call(state, monkeypatch):
    from nightwatch.api import app as app_mod

    provider = FakeProvider(ParsedChange(horizon_hours=6.0))
    monkeypatch.setattr("nightwatch.api.providers.select", lambda preferred=None: provider)
    assert app_mod._what_if(state, _seed_report(state), "why not bigger?") is None
    assert provider.calls == []
