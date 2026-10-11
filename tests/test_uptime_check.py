"""The uptime check says what is wrong in a sentence, and never takes the proxy's saved copy for a live desk.

It used to die in a traceback on a network error or on a body that was not JSON (an error page),
and it read a saved copy - served by the web proxy when the API does not answer - as the API's own
answer: /health was misdiagnosed as "the recorder has written nothing", and a saved example
analysis, which has a verdict, passed as a working desk.
"""

import importlib.util
import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("uptime_check", Path(__file__).resolve().parents[1] / "deploy" / "uptime_check.py")
uc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uc)

NOW = datetime.now(UTC).isoformat()
HEALTH = {"ok": True, "bars": 1_500_000, "tickers_with_data": 24, "last_book_ts": NOW}
SOURCES = [{"key": "bitget_bars", "rows": 10, "last_update": NOW}]
ANALYSIS = {"verdict": {"verdict": "GO"}, "timings_ms": {"total": 1200}}


def site(**over):
    answers = {
        "/": (200, b"<html>", {}),
        "/api/health": (200, json.dumps(HEALTH).encode(), {}),
        "/api/sources": (200, json.dumps(SOURCES).encode(), {}),
        "/api/analyze": (200, json.dumps(ANALYSIS).encode(), {}),
    }
    answers.update(over)

    def fetch(url, payload=None):
        return answers[url.split("https://x.test", 1)[1]]

    return fetch


def run(monkeypatch, capsys, **over):
    monkeypatch.setattr(uc, "fetch", site(**over))
    code = uc.main("https://x.test")
    return code, capsys.readouterr().out


def test_a_healthy_desk_passes(monkeypatch, capsys):
    code, out = run(monkeypatch, capsys)
    assert code == 0 and "all good" in out


def test_a_saved_copy_of_health_says_the_api_is_down_not_the_recorder(monkeypatch, capsys):
    old = dict(HEALTH, last_book_ts="2026-10-01T00:00:00+00:00")
    code, out = run(monkeypatch, capsys, **{"/api/health": (200, json.dumps(old).encode(), {"x-nightwatch-snapshot": "2026-10-01T00:00:00Z"})})
    assert code == 1 and "the API is not answering: health came from the saved copy" in out
    assert "recorder has written nothing" not in out


def test_a_saved_example_analysis_does_not_pass_as_a_working_desk(monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, **{"/api/analyze": (200, json.dumps(ANALYSIS).encode(), {"x-nightwatch-snapshot": "2026-10-01T00:00:00Z"})})
    assert code == 1 and "the analysis came from the saved copy" in out


@pytest.mark.parametrize("path", ["/api/health", "/api/sources", "/api/analyze"])
def test_a_body_that_is_not_json_is_named_not_a_traceback(monkeypatch, capsys, path):
    code, out = run(monkeypatch, capsys, **{path: (200, b"<html>An error occurred</html>", {})})
    assert code == 1 and "did not answer with JSON" in out and "An error occurred" in out


def test_no_answer_at_all_is_a_reason_not_a_crash(monkeypatch, capsys):
    def refused(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(uc.urllib.request, "urlopen", refused)
    code = uc.main("https://x.test")
    out = capsys.readouterr().out
    assert code == 1 and "no answer: connection refused" in out
