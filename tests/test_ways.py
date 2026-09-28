"""The same idea run several ways and the safest go picked by rule."""

from nightwatch.api import ways
from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.stress.scenarios import Side


def row(label, verdict, size, p5_pct, hedge=None):  # noqa: ANN001, ANN201
    return {"label": label, "verdict": verdict, "size": size, "hours": 18.0, "p5_pct": p5_pct, "p5_quote": p5_pct / 100 * size,
            "worst_quote": None, "exit_bps": None, "liquidation_pct": None, "hedge_bps": hedge}


def test_the_pick_is_the_safest_go_at_the_size_asked_not_simply_less_money():
    rows = [row("As asked", "GO", 20000, -4.0), row("Half the size", "GO", 10000, -4.0),
            row("Half hedged on the perpetual", "GO", 20000, -2.0, hedge=12.0), row("Shorter hold: to the next open", "REDUCE_TO", 20000, -1.0)]
    assert ways.pick(rows, 20000)["label"] == "Half hedged on the perpetual"
    none_go = [row("As asked", "NO_GO", 20000, -9.0), row("Without leverage", "REVIEW", 20000, -3.0)]
    assert ways.pick(none_go, 20000)["label"] == "Without leverage"


def test_the_versions_are_fixed_by_rule():
    base = TradeTicket(ticker="NVDA", side=Side.LONG, notional_quote=20000.0, horizon_kind=HorizonKind.HOURS, horizon_hours=70.0, leverage=5.0)
    labels = [label for label, _ in ways.versions(base)]
    assert labels == ["As asked", "Half the size", "Shorter hold: to the next open", "Half hedged on the perpetual", "Without leverage"]
    assert ways.ASKS.search("what's the safest way to hold NVDA over the weekend?")
    assert ways.ASKS.search("怎么持有最安全") and not ways.ASKS.search("what if it gaps 10%?")
