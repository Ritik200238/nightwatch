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
    # Leveraged: no "half hedged on the perpetual" version - a leveraged position is already
    # on the perpetual, so that is not a distinct version of the trade. See below for the
    # unleveraged case, where it is offered and "without leverage" is not.
    assert labels == ["As asked", "Half the size", "Shorter hold: to the next open", "Without leverage"]
    assert ways.ASKS.search("what's the safest way to hold NVDA over the weekend?")
    assert ways.ASKS.search("怎么持有最安全") and not ways.ASKS.search("what if it gaps 10%?")


def test_half_hedged_is_not_offered_for_a_position_already_on_the_perpetual():
    """A leveraged ticket is already trading the perpetual; halving a hedge onto the same
    instrument is not a distinct version of the trade, so it must not appear. An unleveraged
    ticket has no perpetual exposure yet, so the hedge version is still offered and
    "without leverage" is not, since there is none to remove."""
    leveraged = TradeTicket(ticker="NVDA", side=Side.LONG, notional_quote=20000.0, leverage=5.0)
    labels = [label for label, _ in ways.versions(leveraged)]
    assert "Half hedged on the perpetual" not in labels
    assert "Without leverage" in labels

    spot = TradeTicket(ticker="NVDA", side=Side.LONG, notional_quote=20000.0)
    spot_labels = [label for label, _ in ways.versions(spot)]
    assert "Half hedged on the perpetual" in spot_labels
    assert "Without leverage" not in spot_labels


def test_the_table_reads_in_chinese():
    rows = [row("As asked", "GO", 20000, -4.0), row("Half the size", "GO", 10000, -4.0), row("Half hedged on the perpetual", "GO", 20000, -2.0, hedge=12.0)]
    base = TradeTicket(ticker="NVDA", side=Side.LONG, notional_quote=20000.0)
    text = ways._zh(base, rows, ways.pick(rows, 20000), rows[1])
    assert "用永续合约对冲一半" in text and "按原计划" in text and "As asked" not in text
    assert ways.ASKS.search("最安全的持有方式是什么？")
