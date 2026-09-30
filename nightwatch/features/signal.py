"""The bitget-signal Skill's RSI, accepted only if it agrees with the desk's own candles.

Context only: nothing here reaches the gate or the size. A reading that disagrees with
RSI14 on 4-hour bars built from the stored Bitget spot hourly candles by more than
``AGREE_PTS`` is not shown, because the Skill backend is known to return bad numbers
(its Bollinger bands came back inverted).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from nightwatch.time_utils import utc_now

SOURCE = "bitget-signal technical-analysis skill"
AGREE_PTS = 5.0
PERIOD = 14


def own_rsi_4h(hourly_close: pd.Series | None) -> float | None:
    """Wilder RSI14 on 4h closes (UTC-aligned, the last bar possibly still forming)."""
    if hourly_close is None or hourly_close.empty:
        return None
    s = hourly_close.dropna()
    if s.empty:
        return None
    four = s.resample("4h").last().dropna()
    if len(four) < PERIOD * 3:
        return None
    delta = four.diff().dropna()
    gain = delta.clip(lower=0).ewm(alpha=1 / PERIOD, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / PERIOD, adjust=False).mean()
    g, ls = float(gain.iloc[-1]), float(loss.iloc[-1])
    if ls == 0:
        return 100.0 if g > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + g / ls)


def reading_word(rsi: float) -> str:
    return "oversold" if rsi <= 30 else "overbought" if rsi >= 70 else "neutral"


def build(client: Any, ticker: str, hourly_close: pd.Series | None) -> dict[str, Any] | None:  # noqa: ANN401
    """The report's ``signal`` block, or None when there is no reading or no way to check it.

    A reading that disagrees comes back with ``agrees`` False so the caller can say it was
    withheld; MACD (same backend, no independent check here) is fetched only when RSI agrees."""
    doc = client.rsi(ticker)
    if doc is None:
        return None
    own = own_rsi_4h(hourly_close)
    if own is None:
        return None  # an unchecked reading is not shown
    rsi = float(doc["rsi"])
    out: dict[str, Any] = {
        "source": SOURCE, "ticker": ticker, "rsi": round(rsi, 1), "timeframe": doc.get("timeframe") or "4h",
        "reading": reading_word(rsi), "own_rsi": round(own, 1), "agrees": abs(rsi - own) <= AGREE_PTS,
        "fetched_at": utc_now().isoformat(), "macd": None,
    }
    if not out["agrees"]:
        out["note"] = "disagrees with Bitget candles, not shown"
        return out
    m = client.macd(ticker)
    if m is not None:
        out["macd"] = {"macd": round(float(m["macd"]), 3), "signal": round(float(m["signal"]), 3),
                       "histogram": round(float(m["histogram"]), 3), "cross": m.get("cross")}
    return out
