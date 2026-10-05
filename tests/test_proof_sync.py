"""The quoted figures follow the live API, and nothing else in the docs is touched."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nightwatch import proof_sync

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, tzinfo=UTC)


def _api(**over):
    api = {
        "verify": {"ok": True, "checked": 1190},
        "anchors": {"anchors": [{"state": "bitcoin"}] * 6},
        "calibration": {
            "n_matured": 2818, "tail": {"observed_rate": 0.0738, "band": "red"},
            "adjusted": {"n_evaluated": 2774, "adj_lo_coverage": 0.0476, "adj_tail_band": "green", "n_nights": 121, "adj_lo_night_ci": [0.039, 0.069]},
        },
        "misses": {"totals": {"replay": {"scored": 2301, "missed": 124}, "ticket": {"scored": 473, "missed": 8, "distinct_missed": 5}}},
    }
    for k, v in over.items():
        api[k].update(v) if isinstance(v, dict) else None
    return api


def _copy(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    for rel in ("README.md", "docs/submission.md"):
        (tmp_path / rel).write_bytes((ROOT / rel).read_bytes())
    return tmp_path


def test_figures_are_rewritten_and_placeholders_survive(tmp_path):
    root = _copy(tmp_path)
    changed = proof_sync.run(root=root, api=_api(), now=NOW)
    readme = (root / "README.md").read_text(encoding="utf-8")
    sub = (root / "docs/submission.md").read_text(encoding="utf-8")
    assert "1,190 checked, no break, as of 5 Oct 2026" in readme
    assert "2,818 scored forecasts (121 independent nights; resampling whole nights the interval is 3.9% to 6.9%)" in readme
    assert "8 of 473 live tickets (5 distinct events) went past the line" in readme
    assert "6 of 6 in Bitcoin" in readme and "Figures as of 5 Oct 2026." in readme
    assert "recomputes 1,190 chained verdicts" in sub and "4.8% on 2,774 evaluated (green band)" in sub
    assert "`<video URL>`" in sub and "<forecast id>" in sub
    assert changed


def test_a_second_run_changes_nothing(tmp_path):
    root = _copy(tmp_path)
    proof_sync.run(root=root, api=_api(), now=NOW)
    first = {p: (root / p).read_bytes() for p in ("README.md", "docs/submission.md")}
    assert proof_sync.run(root=root, api=_api(), now=NOW) == []
    assert first == {p: (root / p).read_bytes() for p in first}


def test_check_mode_writes_nothing(tmp_path):
    root = _copy(tmp_path)
    before = (root / "README.md").read_bytes()
    assert proof_sync.run(root=root, api=_api(), now=NOW, check=True)
    assert (root / "README.md").read_bytes() == before


def test_a_broken_chain_is_not_written_as_no_break(tmp_path):
    root = _copy(tmp_path)
    proof_sync.run(root=root, api=_api(verify={"ok": False}), now=NOW)
    assert "CHAIN BROKEN" in (root / "README.md").read_text(encoding="utf-8")


def test_a_reworded_sentence_fails_loudly(tmp_path):
    with pytest.raises(ValueError, match="no longer matches"):
        proof_sync.rewrite_readme("nothing here", proof_sync.figures(_api(), NOW))
