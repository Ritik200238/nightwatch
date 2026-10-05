"""The report's own sentences carry Chinese twins built from the same numbers."""

import re

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from nightwatch.decision.zh import note_zh
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

CJK = re.compile(r"[\u3400-\u9fff]")
NUMBERS = re.compile(r"\d[\d,]*(?:\.\d+)?")


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def _numbers(text: str) -> list[str]:
    return sorted(n.replace(",", "") for n in NUMBERS.findall(text))


@pytest.mark.parametrize(
    "extra",
    [
        {"side": "long", "stop_price": 300, "leverage": 5, "thesis": "momentum", "invalidation": "closes below 290"},
        {"side": "short", "stop_price": 420, "thesis": "stretched", "invalidation": "closes above 430"},
        {"side": "long"},
    ],
)
def test_every_failure_mode_has_a_chinese_twin_with_the_same_numbers(client, extra):
    body = {"ticker": "TSLA", "notional_quote": 20000, "account_equity_quote": 200000, "as_of": AS_OF.isoformat(), "record": False, **extra}
    report = client.post("/analyze", json=body).json()
    modes = report["failure_modes"]
    assert modes
    for m in modes:
        for field in ("trigger", "mechanism", "likelihood"):
            zh = m[f"{field}_zh"]
            assert CJK.search(zh), f"{m['key']}.{field} has no Chinese twin: {m[field]!r}"
        # the loss figures and counts quoted in the English appear in the Chinese too
        en_numbers = set(_numbers(m["mechanism"] + " " + m["likelihood"]))
        zh_numbers = set(_numbers(m["mechanism_zh"] + " " + m["likelihood_zh"]))
        assert en_numbers <= zh_numbers or not en_numbers, (m["key"], en_numbers - zh_numbers)
    against = report["second_opinion"]["against"]
    assert against and all(CJK.search(a["text_zh"]) for a in against if a["source"] != "book archive"), [a["text"] for a in against if not a["text_zh"]]


@pytest.mark.parametrize(
    ("note", "has"),
    [
        ("5% of 800 past closed windows were worse for this side", "800"),
        ("1% of 120 past runs of 3 closed windows were worse for this side", "120"),
        ("worst of 12 past earnings reactions", "12"),
        ("3σ adverse move at current realised vol", "3σ"),
        ("what TSLA did on 2020-03-16, the day the market gapped down most", "2020-03-16"),
        ("what TSLA did on 2023-03-13, the day the market's three sessions ran up most", "2023-03-13"),
    ],
)
def test_preset_notes_keep_their_numbers_in_chinese(note, has):
    zh = note_zh(note)
    assert zh and CJK.search(zh) and has in zh


def test_an_unknown_note_is_left_in_english_not_invented():
    assert note_zh("something a future preset says") is None
