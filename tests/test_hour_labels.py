"""Hours are written with halves rounded up: Python's own rounding sends 26.5 to 26 and 0.5 to 0."""

from types import SimpleNamespace

import pytest

from nightwatch.api import intake
from nightwatch.decision.ticket import HorizonKind
from nightwatch.time_utils import round_half_up, whole_hours


@pytest.mark.parametrize(("h", "want"), [(0.5, "1"), (1.5, "2"), (2.5, "3"), (26.5, "27"), (27.5, "28"), (26.49, "26"), (47.5, "48"), (0.0, "0"), (63.0, "63")])
def test_whole_hours_round_half_up(h, want):
    assert whole_hours(h) == want
    assert round_half_up(h) == int(want)


@pytest.mark.parametrize(("h", "want"), [(26.5, "27"), (27.5, "28"), (0.5, "1")])
def test_the_hold_phrase_rounds_half_up_in_both_languages(h, want):
    report = SimpleNamespace(ticket=SimpleNamespace(extra={}, horizon_kind=HorizonKind.HOURS), horizon_h=h)
    assert intake._horizon_phrase(report, "en") == f"for {want}h"
    assert intake._horizon_phrase(report, "zh") == f"持有 {want} 小时"
    report.ticket.horizon_kind = HorizonKind.NEXT_OPEN
    assert f"({want}h)" in intake._horizon_phrase(report, "en")
    assert f"（{want} 小时）" in intake._horizon_phrase(report, "zh")


def test_the_scoring_horizon_key_matches_the_label():
    """The horizon the engine scores ('27h') and the label the trader reads must agree."""
    import inspect

    from nightwatch.pipeline import analyze

    src = inspect.getsource(analyze)
    assert "int(round(horizon_h))" not in src  # half-to-even would score 26.5 h as 26 h
