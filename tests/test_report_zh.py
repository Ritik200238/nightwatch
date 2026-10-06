"""Chinese twins of a report's server-written sentences: present where the page shows them, and
carrying exactly the numbers of the English original."""

import re

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from nightwatch.decision import report_zh as rz
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

CJK = re.compile(r"[一-鿿]")
NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def nums(s: str) -> list[str]:
    return NUM.findall(s)


def assert_same_numbers(en: str, zh: str) -> None:
    """Every number token in the Chinese sentence is in the English one (the twin adds none)."""
    have = nums(en)
    for n in nums(zh):
        assert n in have, f"{n!r} is in the Chinese but not the English:\n  en: {en}\n  zh: {zh}"
        have.remove(n)  # a number written once in English is written once in Chinese


# --------------------------------------------------------------------------- the translators

GATE_CASES = [
    "your 'wrong if' line is 5% away, farther than this token's own one-in-twenty move over the hold (4.9%): it is too far to bind, so it does not limit the loss",
    "no stop given: risk is sized on the calibrated 5th percentile, -4.9% over the horizon",
    "no stop order: risk is sized on the calibrated 5th percentile, -4.9% over the horizon; your 'wrong if' line is 12% away, but it is an invalidation, not a stop order",
    "stop: no stop given; sized on the 5th percentile (-4.9%) instead",
    "written plan: missing thesis, invalidation",
    "position size: position is 31.5% of equity (limit 25.0%)",
    "risk budget: risk 4,200 (analog 5th-percentile loss) but equity unknown",
    "market posture: hostile regime (size multiplier 0.50); selective entries only",
    "exit liquidity: exit would cost 38 bps (limit 25)",
    "liquidation: the 1-in-20 bad outcome (-9.9%) reaches the liquidation price 7.5% away",
    "liquidation: liquidation 12.5% away is reached by 3 of 400 past moments and 2 stress presets",
    "liquidation 12.5% away; no past moment like this and no preset reached it",
    "hedging 97% costs ~16 bps and cuts the 5th-percentile loss from -3.5% to about -0.4% at that ratio (basis risk only)",
    "hedging 100% (fully hedged) costs ~16 bps and cuts the 5th-percentile loss from -3.5% to about -0.4% at that ratio (basis risk only)",
    "Size held at 12,000 USDT: the loss if the stop is hit would exceed the share of equity you allow at risk (requested 20,000).",
    "requested size is within every cap",
    "it moves with the rest of your book (mean correlation 0.82): this adds size, not diversification",
]
CAP_CASES = [
    "1.0% of equity at risk over a 4.90% stop distance",
    "1.0% of equity at risk over a 4.90% analog p5 loss",
    "the largest size at which the whole book's one-in-twenty loss stays inside 8% of equity (40,000)",
    "worst severe preset -22.5% of notional; the largest size whose loss stays inside 5% of equity",
    "largest size the live book absorbs within 25 bps",
]
WARN_CASES = [
    "only 48 past hours match earnings ahead, which is too few to build a distribution from; the answer below is the unfiltered one",
    "only 9 past hours match earnings ahead and over a weekend, which is too few to build a distribution from; the answer below is the unfiltered one",
    "same-ticker history has only 55 distinct episodes; using pooled history across 3 tickers",
    "earnings ahead is too rare in TSLA's own past; searched the pooled history across 24 tokens instead",
    "earnings ahead covers 1,200 past hours, but only 6 distinct episodes (need 15) - they fall on too few separate dates to count as independent evidence; the answer below is the unfiltered one",
]
PREMISE_CASES = [
    "Your reason mentions earnings, but none fall near this hold (no past report on record; next: in 3 days).",
    "Your reason mentions earnings, but none fall near this hold (last over 30 days ago; next: no earnings in the next 30 days).",
    "Your reason mentions earnings, but none fall near this hold (last 12 days ago; next: in 3 days).",
    "Your reason leans on a recent earnings report, but the last one was 20 days ago and next: in 40 days.",
    "Your reason leans on earnings coming up, but next earnings: in 25 days, well past this hold.",
    "Your reason mentions the Fed, but the next FOMC decision is 9 days away, after this hold ends.",
    "Your reason mentions the Fed, but there is no FOMC decision in the next 30 days.",
    "Your reason leans on a data release, but no scheduled release (CPI, jobs, PCE, GDP, retail sales) falls in the next 72 hours.",
    "Your stop (290.00) sits beyond your own 'wrong if' level (300.00): if the idea is proven wrong you are still holding it.",
    "Your reason mentions a dividend or split, but none falls inside this hold; the next is ex-dividend of 0.25 USD a share on 2026-09-12, about 0.10% of the price (Nasdaq, declared 2026-08-01).",
]
LIQ_CASES = [
    "every bucket is still thin: the recorder needs more hours before these can be compared",
    "3 of 8 buckets are still thin and are marked as such",
    "no order-book snapshots recorded yet",
]
BOOK_CASES = [
    "you already hold 30,000 of NVDA long; with this trade that name is 90,000",
    "NVDA moves with the rest of the book (mean correlation 0.82): this adds size, not diversification",
    "hedge 50% of NVDA (45,000) with a short on its Bitget perpetual",
    "take NVDA at 20,000 instead of 90,000",
    "trim NVDA by 40% (36,000), the holding that carries most of the bad case; even closing it does not get the book inside the limit",
    "the cost is a taker fee to open and again to close",
]
SRC_CASES = [
    "1% of 440 past closed windows were worse for this side", "what TSLA did on 2020-03-16, the day the market gapped down most",
    "Bitget spot order book", "api.bitget.com spot orderbook", "spot close→open across closed windows", "rv_24h × √horizon",
    "|basis vs index| during closed sessions", "perp funding history", "1.0% maintenance margin assumed (tiers unavailable)",
    "Yahoo daily, stock's move on SPY's extreme day in the window (2020-03-16)", "block bootstrap of this token's hourly returns",
]


@pytest.mark.parametrize(("fn", "cases"), [
    (rz.gate_zh, GATE_CASES), (rz.cap_detail_zh, CAP_CASES), (rz.warning_zh, WARN_CASES), (rz.premise_zh, PREMISE_CASES),
    (rz.liquidity_note_zh, LIQ_CASES), (rz.book_note_zh, BOOK_CASES), (rz.source_zh, SRC_CASES),
])
def test_every_known_shape_has_a_twin_with_the_same_numbers(fn, cases):
    for en in cases:
        zh = fn(en)
        assert zh, f"no Chinese twin for: {en}"
        assert CJK.search(zh)
        assert_same_numbers(en, zh)


def test_an_unknown_sentence_has_no_twin_rather_than_a_wrong_one():
    for fn in (rz.gate_zh, rz.cap_detail_zh, rz.warning_zh, rz.premise_zh, rz.liquidity_note_zh, rz.book_note_zh, rz.source_zh):
        assert fn("a sentence nobody has written a twin for, 12 times") is None
        assert fn("") is None or fn("") == ""


def test_the_lens_twins_cover_every_lens_the_desk_offers():
    from nightwatch.analog import lens as lens_mod

    assert {x.name for x in lens_mod.LENSES} == set(rz.LENS_ZH)
    for x in lens_mod.LENSES:
        label_zh, def_zh = rz.LENS_ZH[x.name]
        assert CJK.search(label_zh) and CJK.search(def_zh)
        assert_same_numbers(x.definition, def_zh)
        assert rz.lens_description_zh(x.label) == label_zh
    assert rz.lens_description_zh("earnings ahead and over a weekend") == "财报前 且 跨周末"
    assert rz.lens_description_zh("something invented") is None


# --------------------------------------------------------------------------- real reports


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


TRADES = [
    {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 290, "thesis": "deliveries beat",
     "invalidation": "closes below 290", "leverage": 5, "horizon_kind": "hours", "horizon_hours": 63},
    {"ticker": "NVDA", "side": "short", "notional_quote": 900000, "account_equity_quote": 100000, "horizon_kind": "hours", "horizon_hours": 30},
    {"ticker": "AAPL", "side": "long", "notional_quote": 50000, "horizon_kind": "next_open", "lenses": ["earnings_soon"],
     "open_positions": [{"ticker": "TSLA", "side": "long", "notional_quote": 30000}]},
    {"ticker": "TSLA", "side": "long", "notional_quote": 5000, "horizon_kind": "next_open", "hedge_ratio": 0.5},
    {"ticker": "TSLA", "side": "long", "notional_quote": 150000, "account_equity_quote": 100000, "stop_price": 300, "horizon_kind": "hours", "horizon_hours": 12},
    {"ticker": "NVDA", "side": "long", "notional_quote": 60000, "account_equity_quote": 50000, "horizon_kind": "hours", "horizon_hours": 72,
     "thesis": "earnings beat", "invalidation": "closes below 100",
     "open_positions": [{"ticker": "NVDA", "side": "long", "notional_quote": 20000}, {"ticker": "AAPL", "side": "long", "notional_quote": 20000}]},
    {"ticker": "AAPL", "side": "long", "notional_quote": 20000, "account_equity_quote": 90000, "stop_price": 200, "horizon_kind": "next_open",
     "lenses": ["fomc_soon"], "thesis": "the fed will cut rates", "invalidation": "closes below 200"},
]


def _pairs(rep):
    """(english, chinese-or-None, where) for every field the page shows in Chinese through a twin."""
    def lst(obj, key, where):
        for i, s in enumerate((obj or {}).get(key) or []):
            z = ((obj or {}).get(key + "_zh") or [])
            yield s, (z[i] if i < len(z) and z[i] else None), f"{where}[{i}]"

    def one(obj, key, where):
        if isinstance(obj, dict) and isinstance(obj.get(key), str) and obj[key]:
            yield obj[key], obj.get(key + "_zh") or None, where

    v, g, sz, an = rep.get("verdict") or {}, rep.get("gate") or {}, rep.get("sizing") or {}, rep.get("analog") or {}
    yield from lst(v, "reasons", "verdict.reasons")
    yield from lst(g, "advisories", "gate.advisories")
    yield from lst(rep, "warnings", "warnings")
    yield from lst(rep, "premise", "premise")
    for k, c in enumerate(v.get("caps") or []):
        yield from one(c, "detail", f"verdict.caps[{k}]")
    for k, c in enumerate(sz.get("caps") or []):
        yield from one(c, "detail", f"sizing.caps[{k}]")
    for k, r in enumerate(g.get("rules") or []):
        yield from one(r, "reason", f"gate.rules[{k}]")
    lens = an.get("lens") or {}
    yield from one(lens, "description", "lens.description")
    yield from one(lens, "refused", "lens.refused")
    for k, x in enumerate(lens.get("lenses") or []):
        yield from one(x, "label", f"lens.lenses[{k}].label")
        yield from one(x, "definition", f"lens.lenses[{k}].definition")
    yield from one((rep.get("execution") or {}).get("liquidity_history"), "note", "liquidity_history.note")
    p = rep.get("portfolio") or {}
    yield from lst(p, "notes", "portfolio.notes")
    st = p.get("stress") or {}
    yield from lst(st, "notes", "portfolio.stress.notes")
    for k, plan in enumerate(st.get("plans") or []):
        yield from one(plan, "detail", f"plans[{k}].detail")
        yield from lst(plan, "notes", f"plans[{k}].notes")
    for e in ((rep.get("provenance") or {}).get("items") or {}).values():
        for sub in ([e] if "kind" in e else list(e.values())):
            yield from one(sub, "source", "provenance.source")


# Sentences the page already translates by another route (the breaker and the data-quality flag
# lists are identifiers or a fixed phrase the page maps itself).
_ELSEWHERE = re.compile(r"^(circuit breaker|data quality): ")


def test_a_real_report_carries_a_twin_for_every_displayed_sentence_with_the_same_numbers(client):
    seen = missing = 0
    problems = []
    for t in TRADES:
        r = client.post("/analyze", json={**t, "as_of": AS_OF.isoformat(), "record": False})
        assert r.status_code == 200, r.text
        for en, zh, where in _pairs(r.json()):
            seen += 1
            if zh is None:
                if _ELSEWHERE.match(en) or CJK.search(en):
                    continue
                missing += 1
                problems.append(f"{where}: {en}")
                continue
            assert CJK.search(zh), (where, zh)
            assert_same_numbers(en, zh)
    assert seen > 40  # the matrix exercises real sentences
    assert not problems, "English sentences with no Chinese twin:\n" + "\n".join(sorted(set(problems)))


def test_the_lens_menu_carries_chinese_labels(client):
    menu = client.get("/lenses").json()["lenses"]
    assert menu and all(x.get("label_zh") and x.get("definition_zh") for x in menu)
