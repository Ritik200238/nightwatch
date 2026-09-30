"""Plain words for the event features, so a cap never reads as a measurement.

``hours_to_earnings`` and friends are capped at 720 h (30 days) so a distance metric is
not dominated by "far away". The engine needs that number; a person reading "720 hours"
takes it for a real date. Everything user-facing goes through here instead.
"""
from __future__ import annotations

EVENT_CAP_H = 720.0
NO_EARNINGS_30D = "no earnings in the next 30 days"
NOT_KNOWN = "not known"


def _span(hours: float) -> str:
    return f"{hours / 24:.0f} days" if hours >= 48 else f"{hours:.0f} hours"


def earnings_ahead(hours: float | None) -> str:
    """When the next earnings report is: a span, 'in 3 days', or the honest absence."""
    if hours is None or hours != hours:  # noqa: PLR0124 - NaN
        return NOT_KNOWN + " (no upcoming date on the earnings calendar)"
    if hours >= EVENT_CAP_H:
        return NO_EARNINGS_30D
    return f"in {_span(hours)}"


def hours_ago(hours: float | None) -> str:
    """How long since an event, with the cap read as 'over 30 days'."""
    if hours is None or hours != hours:  # noqa: PLR0124
        return NOT_KNOWN
    if hours >= EVENT_CAP_H:
        return "more than 30 days ago"
    return f"{_span(hours)} ago"
