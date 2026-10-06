"""/chat/stream tells the same turn as /chat, with a step event as each stage finishes."""

import json

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    monkeypatch.setenv("NIGHTWATCH_LLM_PROVIDER", "off")


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = [x for x in block.split("\n") if not x.startswith(":")]
        if not lines:
            continue
        kind = lines[0].removeprefix("event: ")
        out.append((kind, json.loads(lines[1].removeprefix("data: "))))
    return out


def stream(client, body):
    r = client.post("/chat/stream", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "no-cache" in r.headers["cache-control"]
    assert r.headers["x-accel-buffering"] == "no"
    return events(r.text)


def test_a_trade_streams_its_stages_then_the_same_payload_as_chat(client):
    body = {"messages": [{"role": "user", "content": "long 40000 TSLA overnight, account 50k"}]}
    got = stream(client, body)
    kinds = [k for k, _ in got]
    assert kinds[-1] == "done" and kinds.count("done") == 1
    steps = [d for k, d in got if k == "step"]
    assert [s["stage"] for s in steps][:2] == ["snapshot", "analog"]
    assert {"analog", "stress", "decision"} <= {s["stage"] for s in steps}
    for s in steps:
        assert s["en"] and s["zh"]
    done = got[-1][1]
    assert done["report"]["ticket"]["ticker"] == "TSLA"
    # A step label is shown to the reader, so it carries the verdict as words, never the code
    # name ("NO_GO"), and the Chinese label is in Chinese.
    decision = next(s for s in steps if s["stage"] == "decision")
    assert "_" not in decision["en"] and not any(c in decision["zh"] for c in "_ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    # The numbers in the labels are the stage's own.
    stress = next(s for s in steps if s["stage"] == "stress")
    assert f"Ran {len(done['report']['stress']['presets'])} stress presets" in stress["en"]
    plain = client.post("/chat", json=body).json()
    assert set(plain) == set(done)
    assert plain["reply"] == done["reply"]


def test_a_followup_that_needs_no_analysis_sends_done_alone(client):
    out = stream(client, {"messages": [{"role": "user", "content": "thanks, that helps"}]})
    assert [k for k, _ in out] == ["done"]


def test_errors_carry_the_detail_chat_would_raise(client):
    body = {"messages": [{"role": "user", "content": "how often does TSLA fall 5% over a weekend"}]}
    plain = client.post("/chat", json=body)
    out = stream(client, body)
    if plain.status_code == 200:
        assert out[-1][0] == "done"
    else:
        assert out[-1] == ("error", {"detail": plain.json()["detail"], "status": plain.status_code})


def test_a_failing_turn_ends_in_an_error_event(client, monkeypatch):
    def boom(*_a, **_k):
        from fastapi import HTTPException

        raise HTTPException(422, "nope")

    monkeypatch.setattr("nightwatch.api.baserate.detect", lambda *a, **k: object())
    monkeypatch.setattr("nightwatch.api.baserate.answer", lambda *a, **k: boom())
    out = stream(client, {"messages": [{"role": "user", "content": "anything"}]})
    assert out == [("error", {"detail": "nope", "status": 422})]
