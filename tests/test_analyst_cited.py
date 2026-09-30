"""The analyst's take: every number carries a source tag that is checked, the language is held
to the evidence, and the debate arrives from the same single call."""

import json

from nightwatch.api import analyst

from .test_analyst import REPORT, FakeProvider


def _reply(**kw):  # noqa: ANN003, ANN202
    return json.dumps({"for": "", "against": "", "reconcile": "", "take": "The call\nGO.", **kw})


def test_a_tagged_number_passes_and_is_returned_as_a_citation():
    sheet = analyst.fact_sheet(REPORT)
    clean, removed, cites = analyst.verify_tagged("A bad night is worse than -4.6% [history]. Getting out costs 21 bps [order book]. The median target is $420 target [street].", sheet)
    assert removed == 0 and "-4.6% [history]" in clean
    assert {"number": "-4.6%", "source": "history"} in cites and {"number": "21bps", "source": "order book"} in cites


def test_an_untagged_number_is_removed_even_when_it_is_on_the_sheet():
    clean, removed, cites = analyst.verify_tagged("A bad night is worse than -4.6%. Nothing else.", analyst.fact_sheet(REPORT))
    assert removed == 1 and "4.6" not in clean and not cites


def test_a_wrong_number_or_wrong_section_is_removed():
    sheet = analyst.fact_sheet(REPORT)
    clean, removed, _ = analyst.verify_tagged("It may lose 12% [history]. Exit costs 21 bps [street]. Exit costs 21 bps [order book].", sheet)
    assert removed == 2 and clean == "Exit costs 21 bps [order book]."


def test_every_sheet_line_has_a_section_id():
    sheet = analyst.fact_sheet(REPORT)
    assert {"desk", "history", "stop", "plan", "stress", "order book", "street", "relations"} <= set(analyst.sheet_sections(sheet))
    assert all(line.startswith("[") for line in sheet.splitlines())


def test_the_prompt_forbids_overclaiming_and_asks_for_one_change_of_mind():
    for system in (analyst.SYSTEM_EN, analyst.SYSTEM_ZH):
        assert "Do not predict direction" in system and "no clear edge" in system
        assert "exactly one sentence" in system and "Directly after EVERY number" in system
        assert "quote the typical outcome next to it" in system


def test_the_edge_check_is_a_fact_on_the_sheet_not_the_models_mood():
    h = REPORT["analog"]["horizons"]["95h"]
    r = {**REPORT, "analog": {**REPORT["analog"], "horizons": {"95h": {**h, "baseline": {"permutation_p_value": 0.42}}}}}
    sheet = analyst.fact_sheet(r)
    assert "p = 0.42, so no clear edge over random hours" in sheet
    assert "coin flip" not in sheet and "coin flip" not in " ".join(analyst.relations(r))
    r["analog"]["horizons"]["95h"]["baseline"]["permutation_p_value"] = 0.01
    assert "the history differs from random hours" in analyst.fact_sheet(r)


def test_the_debate_comes_back_from_one_call_checked_and_cited():
    reply = _reply(**{
        "for": "Typical outcome is -1.8% [history] with the stop 7.6% [stop] away. Tesla will rally 12% [history].",
        "against": "A bad night goes past -4.6% [history].",
        "reconcile": "The desk says GO at 20,000 [desk] USDT.",
        "take": "The call\nGO at 20,000 [desk] USDT.\nWhat would change my mind\nA fill above 21 bps [order book].",
    })
    p = FakeProvider(text=reply)
    take = analyst.write(p, REPORT)
    assert len(p.calls) == 1, "one call for the debate and the take"
    assert "12%" not in take.case_for and "7.6% [stop]" in take.case_for
    assert take.case_against.startswith("A bad night") and take.reconcile == "The desk says GO at 20,000 [desk] USDT."
    assert take.removed == 1
    d = take.to_dict()
    assert d["for"] == take.case_for and d["against"] == take.case_against and "case_for" not in d
    assert {"number": "-4.6%", "source": "history"} in d["citations"]


def test_a_reconcile_that_drops_or_changes_the_verdict_is_replaced_by_the_desks_own_words():
    for line in ("Overall this looks fine.", "The desk says NO_GO at 20,000 [desk] USDT.", "The desk says GO at 5,000 [desk] USDT."):
        take = analyst.write(FakeProvider(text=_reply(**{"for": "Typical outcome -1.8% [history].", "reconcile": line})), REPORT)
        assert take.reconcile == "The desk's verdict stands: GO, up to 20,000 USDT."


def test_prose_instead_of_json_is_still_a_checked_take_without_a_debate():
    take = analyst.write(FakeProvider(text="The call\nGO at 20,000 [desk] USDT. Rally 9% [history]."), REPORT)
    assert take.status == "done" and take.removed == 1 and not take.case_for and not take.reconcile
    assert take.citations == [{"number": "20000", "source": "desk"}]


def test_a_fenced_json_reply_is_read():
    fenced = "```json\n" + _reply(**{"for": "Typical outcome -1.8% [history]."}) + "\n```"
    assert analyst.write(FakeProvider(text=fenced), REPORT).case_for == "Typical outcome -1.8% [history]."


def _wait(jobs, key, status="done"):  # noqa: ANN001, ANN202
    import threading
    for _ in range(80):
        got = jobs.get(*key)
        if got and got.status == status:
            return got
        threading.Event().wait(0.05)
    return jobs.get(*key)


def test_a_prefetched_take_is_joined_by_the_later_request_not_written_twice():
    jobs = analyst.AnalystJobs()
    p = FakeProvider(text=_reply(**{"for": "Typical outcome -1.8% [history]."}), delay=0.2)
    jobs.prefetch(7, REPORT, lambda: p, "en")
    assert jobs.get(7, "en").status == "pending", "pending from the moment the report exists"
    assert jobs.start(7, REPORT, p, "en").status in ("pending", "done")
    assert _wait(jobs, (7, "en")).status == "done" and len(p.calls) == 1
    assert jobs.get(7, "zh") is None, "only the requested language is written"


def test_a_prefetch_with_no_provider_leaves_no_trace_so_a_later_ask_still_works():
    jobs = analyst.AnalystJobs()
    jobs.prefetch(8, REPORT, lambda: None, "en")
    for _ in range(40):
        if jobs.get(8, "en") is None:
            break
        import threading
        threading.Event().wait(0.05)
    assert jobs.get(8, "en") is None
    assert jobs.start(8, REPORT, FakeProvider(), "en").status == "pending"



def test_an_empty_side_of_the_debate_is_filled_from_the_desks_own_rules():
    """Live, the model's 'for' failed the number check and the card showed one side only."""
    import copy

    r = copy.deepcopy(REPORT)
    r["second_opinion"] = {"supporting": [{"text": "The book absorbs this size cheaply."}], "against": []}
    reply = _reply(**{"for": "Tesla will rally 12% [history].", "against": "A bad night goes past -4.6% [history].",
                      "reconcile": "The desk says GO at 20,000 [desk] USDT.", "take": "The call" + chr(10) + "GO at 20,000 [desk] USDT."})
    take = analyst.write(FakeProvider(text=reply), r)
    assert take.case_for == "The book absorbs this size cheaply. (from the desk's own rules)"
    assert take.case_against.startswith("A bad night")
