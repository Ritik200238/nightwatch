"""The card under a chat answer holds no number the answer or the report does not."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from nightwatch.api import baserate, cards, followup
from tests.test_api import client  # noqa: F401 - fixture
from tests.test_pipeline import AS_OF, _ctx, seeded_store  # noqa: F401 - fixture

FIXTURE = Path(__file__).parent / "data" / "report.json"


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def leaves(obj, acc=None):  # noqa: ANN001, ANN201
    """Every number anywhere in a payload."""
    acc = set() if acc is None else acc
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, (int, float)):
        acc.add(round(float(obj), 6))
    elif isinstance(obj, dict):
        for v in obj.values():
            leaves(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            leaves(v, acc)
    return acc


def assert_from(card: dict, *sources, derived=()):  # noqa: ANN001, ANN002, ANN201
    """Each number on the card is a field of a source, or one of the named derived values."""
    known = set()
    for s in sources:
        leaves(s, known)
    known |= {round(float(d), 6) for d in derived}
    stray = sorted(n for n in leaves(card) if n not in known)
    assert not stray, f"numbers on the card that are in no source: {stray}"


def test_a_shock_card_holds_the_positions_arithmetic_and_the_reports_tail(report):
    q = "what if it gaps down 10%?"
    got = followup.answer(report, q)
    card = cards.card_for({"answer_kind": got.kind, "mode": "rules"}, report, q)
    notional = report["ticket"]["notional_quote"]
    assert card["kind"] == "shock" and card["move_pct"] == -10.0 and card["pnl_pct"] == -10.0
    assert card["pnl_quote"] == pytest.approx(-notional * 0.10)
    assert f"{notional * 0.10:,.0f}" in got.text  # the sentence prints the same loss
    p1 = next(p for p in report["stress"]["presets"] if p["id"] == "closed_window_gap_p1")
    assert card["past"]["p1_move_pct"] == p1["price_move_pct"] and card["past"]["beyond"] == "1_in_100"
    worst = min(i["total_pnl_quote"] for i in report["stress"]["impacts"] if i["total_pnl_quote"] is not None)
    assert card["worst_quote"] == worst
    p5 = followup._p5(report)
    assert card["p5_quote"] == pytest.approx(p5 / 100.0 * notional)  # the 1-in-20 loss at this size
    assert_from(card, report, derived=[-notional * 0.10, -10.0, 10.0, p5 / 100.0 * notional])


def test_a_shock_up_for_a_long_is_a_gain_and_is_not_placed_on_the_loss_tail(report):
    q = "what if it rallies 5%?"
    card = cards.shock_card(report, q)
    assert card["pnl_pct"] == 5.0 and card["pnl_quote"] > 0 and card["past"]["beyond"] is None


def test_a_small_shock_is_inside_the_past_windows(report):
    card = cards.shock_card(report, "what if it gaps down 1%?")
    assert card["past"]["beyond"] is None


def test_a_short_shock_flips_the_sign_of_the_position(report):
    r = copy.deepcopy(report)
    r["ticket"]["side"] = "short"
    card = cards.shock_card(r, "what if it gaps up 10%?")
    assert card["side"] == "short" and card["move_pct"] == 10.0 and card["pnl_pct"] == -10.0


def test_a_size_card_sets_the_sweeps_point_beside_the_trade_on_screen(report):
    q = "what if I halve it?"
    got = followup.answer(report, q)
    assert got.kind == "size"
    card = cards.card_for({"answer_kind": got.kind, "mode": "rules"}, report, q)
    rows = {x["key"]: x for x in card["rows"]}
    point = followup._nearest(report["sensitivity"]["sizes"], "notional", report["ticket"]["notional_quote"] / 2)
    assert rows["size"]["before"] == report["ticket"]["notional_quote"] and rows["size"]["after"] == point["notional"]
    assert rows["verdict"]["after"] == point["verdict"] and rows["exit"]["after"] == point["exit_cost_bps"]
    assert_from(card, report)


def test_no_size_card_when_the_size_is_unchanged(report):
    assert cards.size_card(report, "why not bigger?") is None


def test_a_what_if_card_is_before_and_after_of_two_reports(report):
    after = copy.deepcopy(report)
    after["verdict"] = {**after["verdict"], "verdict": "REDUCE_TO", "recommended_notional": 7500.0}
    after["execution"]["exit_quote"]["total_cost_bps"] = 31.5
    out = {"mode": "what_if", "answer_kind": "what_if", "report": after}
    card = cards.card_for(out, report, "what about 5x?")
    rows = {x["key"]: x for x in card["rows"]}
    assert rows["verdict"] == {"key": "verdict", "unit": "verdict", "before": report["verdict"]["verdict"], "after": "REDUCE_TO"}
    assert rows["size"]["after"] == 7500.0 and rows["exit"]["after"] == 31.5
    assert rows["p5"]["before"] == followup._p5(report)
    assert_from(card, report, after)


def test_a_leveraged_worst_stress_is_capped_at_the_margin(report):
    after = copy.deepcopy(report)
    after["leverage"] = {"leverage": 5.0, "margin_quote": 100.0, "liquidation_distance_pct": 20.0}
    card = cards.compare_card(report, after)
    assert {x["key"]: x for x in card["rows"]}["worst"]["after"] == -100.0


def test_no_card_when_the_rerun_has_no_verdict(report):
    assert cards.card_for({"mode": "what_if", "report": {"verdict": {}}}, report, "x") is None
    assert cards.card_for({"mode": "rules", "answer_kind": "why"}, report, "why?") is None
    assert cards.card_for({"answer_kind": "shock"}, None, "gaps down 10%") is None


def test_a_base_rate_card_is_the_count_out_of_n(seeded_store):  # noqa: F811
    state = SimpleNamespace(ctx=_ctx(seeded_store), lock=threading.Lock())
    q = baserate.detect("how often does TSLA fall 1% overnight?", ["TSLA"])
    out = baserate.answer(state, q, as_of=AS_OF)
    card = cards.card_for(out, None, "")
    w = out["base_rate"]["windows"]
    assert card["kind"] == "base_rate" and card["windows"] == w
    assert 0 <= w["hits"] <= w["n"] and w["share"] == pytest.approx(w["hits"] / w["n"])
    # The sentence prints the same count and share.
    assert f"({w['share']:.1%})" in out["reply"]
    cond = card["conditional"]
    if cond:
        assert f"{cond['hits']} ({cond['hits'] / cond['n']:.0%})" in out["reply"]
    assert_from(card, out["base_rate"], derived=[q.move_pct])


def test_a_ways_card_is_the_versions_table(report):
    def row(label, verdict, size, p5):  # noqa: ANN001, ANN202
        return {"label": label, "verdict": verdict, "size": size, "hours": 18.0, "p5_pct": p5, "p5_quote": p5 / 100 * size,
                "worst_quote": -900.0, "exit_bps": 12.0, "liquidation_pct": None, "hedge_bps": None}

    rows = [row("As asked", "GO", 20000.0, -4.0), row("Half the size", "GO", 10000.0, -4.0), row("Half hedged on the perpetual", "GO", 20000.0, -2.0)]
    card = cards.card_for({"mode": "ways", "ways": rows}, report, "safest way to hold it?")
    assert card["kind"] == "ways" and card["pick"] == "Half hedged on the perpetual"
    assert [x["label"] for x in card["rows"]] == [x["label"] for x in rows]
    assert card["rows"][0]["label_zh"] == "按原计划"
    assert_from(card, rows)


def _ask(client, fid, text):  # noqa: ANN001, ANN202, F811
    return client.post("/chat", json={"messages": [{"role": "user", "content": text}], "context_forecast_id": fid}).json()


def test_the_chat_endpoint_carries_the_card(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    first = client.post("/chat", json={"messages": [{"role": "user", "content": "long 20000 TSLA overnight"}], "account_equity_quote": 200000}).json()
    fid = first["report"]["forecast_id"]
    shock = _ask(client, fid, "what if it gaps down 10%?")
    assert shock["answer_kind"] == "shock" and shock["card"]["kind"] == "shock" and shock["card"]["move_pct"] == -10.0
    zh = _ask(client, fid, "如果跌 10% 呢？")
    assert zh["card"]["kind"] == "shock" and zh["card"]["pnl_quote"] == shock["card"]["pnl_quote"]
    again = _ask(client, fid, "what if I halve it?")
    assert again["card"]["kind"] == "compare"
    flipped = _ask(client, fid, "short it instead")
    assert flipped["mode"] == "what_if" and flipped["card"]["kind"] == "compare"
    assert_from(flipped["card"], first["report"], flipped["report"])
    # A text-only answer has no card key at all.
    assert "card" not in _ask(client, fid, "thanks, that helps")


def test_the_shock_card_carries_the_worst_presets_chinese_name(report):
    # The chat card printed "最坏压力情景：Replay: COVID crash": the English preset name in a Chinese answer.
    r = copy.deepcopy(report)
    for p in r["stress"]["presets"]:
        p["name_zh"] = "中文名：" + p["name"]
    card = cards.shock_card(r, "what if it gaps down 10%?")
    assert card["worst_name_zh"] == "中文名：" + card["worst_name"]
