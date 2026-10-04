"""The analyst's text reads like a person wrote it: no source tags, no signed zero, no made-up
conditions, a real 'what would change my mind', Chinese that is Chinese, and a number check that
understands Chinese number formats."""

import json

from nightwatch.api import analyst

from .test_analyst import REPORT, FakeProvider


def _reply(**kw):  # noqa: ANN003, ANN202
    return json.dumps({"for": "", "against": "", "reconcile": "", "take": "The call\nGO.", **kw}, ensure_ascii=False)


class Seq(FakeProvider):
    """A model that gives a different reply each call."""

    def __init__(self, *texts):  # noqa: ANN002
        super().__init__(texts[0])
        self.texts = list(texts)

    def write(self, *, system, user, max_tokens=1500):  # noqa: ANN001, ANN003, ANN201
        self.calls.append(user)
        return self.texts[min(len(self.calls) - 1, len(self.texts) - 1)]


def test_the_sheet_names_the_largest_loss_not_the_first_listed():
    r = {**REPORT, "failure_modes": [
        {"title": "A bad gap", "mechanism": "m", "loss_quote": -833.0, "likelihood": "5%"},
        {"title": "A repeat of the COVID crash", "mechanism": "m", "loss_quote": -2843.0, "likelihood": "a named crisis"},
    ]}
    line = next(x for x in analyst.fact_sheet(r).splitlines() if x.startswith("[failure mode]"))
    assert "COVID" in line and "2,843" in line and "833" not in line


def test_a_typical_outcome_of_zero_is_about_flat_never_a_signed_zero():
    h = REPORT["analog"]["horizons"]["95h"]
    r = {**REPORT, "analog": {**REPORT["analog"], "horizons": {"95h": {**h, "cohort": {**h["cohort"], "median_pct": -0.02}}}}}
    sheet = analyst.fact_sheet(r)
    assert "typical outcome for this position about flat" in sheet and "-0.0%" not in sheet and "+0.0%" not in sheet


def test_no_account_size_is_said_plainly_on_the_sheet():
    assert "No account size was given" in analyst.fact_sheet(REPORT)
    r = {**REPORT, "ticket": {**REPORT["ticket"], "account_equity_quote": 50000.0}}
    assert "No account size" not in analyst.fact_sheet(r)


def test_polish_removes_tags_signed_zeros_and_known_bad_sentences():
    text = ("The call\nGO at 20,000 [desk] USDT. That liquidity gap dominates this trade.\n"
            "What matters most tonight\nThe typical outcome is -0.0% [history] and 10% is fine.\n"
            "What would change my mind\nIf the worst loss exceeded your unstated equity, it fails.")
    out = analyst.polish(text, REPORT, "en")
    assert "[" not in out and "liquidity gap" not in out and "unstated" not in out
    assert "-0.0%" not in out and "about flat" in out and "10%" in out
    assert out.count("\n") >= 4 and "What would change my mind" in out


def test_a_change_of_mind_tied_to_zero_or_a_made_up_input_is_replaced_by_a_real_condition():
    for bad in ("If the typical outcome moved above +0.0% in a future check.", "If the loss exceeded your unstated equity.", ""):
        out = analyst.polish(f"The call\nGO.\nWhat would change my mind\n{bad}\nWhat I'd watch\nThe book.", REPORT, "en")
        mind = out.split("What would change my mind\n")[1].split("\nWhat I'd watch")[0]
        assert mind and "0.0" not in mind and "unstated" not in mind and mind.endswith(".")
        assert "bps" in mind or "check" in mind
    good = "If getting out cost more than 30 bps on the order book, I would cut the size."
    assert good in analyst.polish(f"The call\nGO.\nWhat would change my mind\n{good}", REPORT, "en")


def test_the_change_of_mind_names_the_missing_account_size_when_that_is_what_blocks_the_verdict():
    r = {**REPORT, "verdict": {"verdict": "REVIEW_REQUIRED", "recommended_notional": 2474.0}}
    assert "account size" in analyst.mind_line(r, "en") and "账户规模" in analyst.mind_line(r, "zh")


def test_chinese_number_formats_pass_the_number_check():
    sheet = analyst.fact_sheet(REPORT, "zh")
    # 2万 is 20000; full-width digits and percent; a translated section name; no space after 。
    clean, removed, _ = analyst.verify_tagged("规模是2万 [desk] USDT。最差的二十分之一低于－４．６％［历史］。成本２１ bps【订单簿】。", sheet)
    assert removed == 0, clean
    clean, removed, _ = analyst.verify_tagged("规模是3万 [desk] USDT。成本21 bps [order book]。", sheet)
    assert removed == 1 and "21" in clean and "3万" not in clean, "a wrong amount is still removed, and only its own sentence"


def test_a_chinese_paragraph_loses_only_the_bad_sentence_not_all_of_it():
    sheet = analyst.fact_sheet(REPORT, "zh")
    clean, removed, _ = analyst.verify_tagged("成本21 bps [order book]。预计上涨12% [history]。止损在7.6% [stop]。", sheet)
    assert removed == 1 and "21" in clean and "7.6" in clean and "12%" not in clean


def test_mostly_english_text_is_caught_in_chinese_mode():
    assert analyst.mostly_english("Replay: COVID crash would cost -14.2% what TSLA did on the day the market gapped down most", ("TSLA",))
    assert not analyst.mostly_english("特斯拉在周末休市期间可能出现大幅跳空，最差的二十分之一情况会亏损约百分之四点六 USDT。", ("TSLA",))


def test_a_half_english_chinese_take_is_asked_for_again_and_the_chinese_one_is_kept():
    english = _reply(take="The call\nThe weekend gap risk dominates this trade and the replay of the crash is the largest loss here.")
    chinese = _reply(take="结论\n维持 GO，规模 20,000 [desk] USDT。\n今晚最重要的\n周末休市期间的跳空风险最大，需要留意。")
    p = Seq(english, chinese)
    take = analyst.write(p, REPORT, "zh")
    assert len(p.calls) == 2 and "Simplified Chinese" in p.calls[1] or "Chinese" in p.calls[1]
    assert take.status == "done" and "结论" in take.text and not analyst.mostly_english(take.text)


def test_a_chinese_take_that_stays_english_is_not_shown_half_translated():
    english = _reply(take="The call\nThe weekend gap risk dominates this trade and the replay of the crash is the largest loss here today.")
    take = analyst.write(Seq(english, english), REPORT, "zh")
    assert take.status == "failed" and not take.text


def test_a_take_the_guard_cut_to_pieces_is_written_again_and_the_cleaner_one_kept():
    bad = _reply(take="The call\nRally 12% [history]. Rally 13% [history]. Rally 14% [history]. GO at 20,000 [desk] USDT.")
    good = _reply(take="The call\nGO at 20,000 [desk] USDT.")
    p = Seq(bad, good)
    take = analyst.write(p, REPORT)
    assert len(p.calls) == 2 and take.removed == 0 and "GO at 20,000" in take.text
    # A small cut is not worth a second call.
    p2 = Seq(_reply(take="The call\nRally 12% [history]. GO at 20,000 [desk] USDT."), good)
    assert analyst.write(p2, REPORT).removed == 1 and len(p2.calls) == 1


def test_the_prompts_forbid_the_phrases_the_audit_caught():
    for system in (analyst.SYSTEM_EN, analyst.SYSTEM_ZH):
        assert "unstated equity" in system and "liquidity gap" in system and "-0.0%" in system and "threshold of zero" in system
    assert "EVERY sentence must be Chinese" in analyst.SYSTEM_ZH


def test_the_chinese_sheet_uses_the_chinese_names_so_there_is_no_english_to_copy():
    r = {**REPORT, "stress": {**REPORT["stress"], "presets": [{"name": "Replay: COVID crash", "name_zh": "回放：新冠崩盘"}]}}
    assert "回放：新冠崩盘" in analyst.fact_sheet(r, "zh") and "COVID" not in analyst.fact_sheet(r, "zh")
    assert "COVID" in analyst.fact_sheet(r, "en")
