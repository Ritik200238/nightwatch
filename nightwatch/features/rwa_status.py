"""Bitget Wallet's tokenized-stock listing: is the token tradable, and does the size fit?

From ``nightwatch.data.bitget_rwa`` (the bitget-wallet-skill's RWA market data). Three
checks, each a plain fact the listing states, each able to put a caution on the report:

* the listing is not ``online`` or carries a pause code (``special_pause_reason_code``);
* the listing carries alert text (``market_alert_content``);
* the requested size is outside the per-order limits (``tx_minimum_usd`` / ``tx_maximum_usd``).

None of them changes the recommended size: they say the order may not go through as asked.
Everything else it returns (session, price, valuation) is shown as context.
"""

from __future__ import annotations

from typing import Any

from nightwatch.time_utils import utc_now

SOURCE = "Bitget Wallet RWA market data (bitget-wallet-skill)"


def _f(x: Any) -> float | None:  # noqa: ANN401
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def build(info: dict[str, Any] | None, notional: float, side_long: bool) -> dict[str, Any] | None:
    """The report's ``rwa_listing`` block, or None with no reading."""
    if not info:
        return None
    buy = _f(info.get("tx_maximum_usd")), _f(info.get("tx_minimum_usd"))
    sell = _f(info.get("tx_maximum_sell_usd")), _f(info.get("tx_minimum_sell_usd"))
    hi, lo = buy if side_long else sell  # a long opens by buying, a short-side ticket (reduce) sells
    flags: list[str] = []
    pause = (info.get("special_pause_reason_code") or "").strip()
    status = info.get("status")
    if status and status != "online":
        flags.append(f"Bitget Wallet lists {info.get('ticker')} as {status}")
    if pause:
        flags.append(f"Bitget Wallet reports a trading pause ({pause})")
    alert = (info.get("market_alert_content") or "").strip()
    if alert:
        flags.append(f"Bitget Wallet alert: {alert}")
    if hi is not None and notional > hi:
        flags.append(f"the requested {notional:,.0f} USDT is above Bitget Wallet's per-order maximum of {hi:,.0f}")
    if lo is not None and notional < lo:
        flags.append(f"the requested {notional:,.0f} USDT is below Bitget Wallet's per-order minimum of {lo:,.0f}")
    return {
        "source": SOURCE, "ticker": info.get("ticker"), "status": status, "market_status": info.get("market_status"),
        "session": info.get("market_status_code"), "session_title": info.get("market_status_title"),
        "latest_price": _f(info.get("latest_price")), "pe_ratio": _f(info.get("pe_ratio")),
        "tx_max_usd": hi, "tx_min_usd": lo, "flags": flags, "fetched_at": utc_now().isoformat(),
    }
