# Nightwatch

**Stress-test a tokenized-US-stock trade before you place it.**

US stocks trade 6.5 hours a day. Tokenized versions of them (rTokens) trade 24/7. The
dangerous window is the one where only the token can move: nights, weekends, holidays —
when news lands and the real market is shut.

Nightwatch takes a trade idea in plain language and answers four questions with data:

1. **What happened before?** It finds the past moments that looked like now — same
   volatility, same gap between token and fair value, same time-of-week, same distance to
   earnings — and shows what followed, with sample sizes and confidence intervals.
2. **What could go wrong?** Preset stress tests built from real token data: weekend gap,
   earnings gap, volatility spike, token-vs-fair-value blowout, liquidity drought, exchange
   halt.
3. **Can you get out?** It walks the live order book for your size and tells you the real
   cost of exiting.
4. **How big, then?** A sized verdict — go, reduce, hedge with the perpetual, or don't —
   with every number traceable to its source.

The human makes the decision. Nightwatch never places orders.

## Status

Early build. See `SPEC.md`, `FEATURES.md`, `BUILD-ORDER.md`.

## Development

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python.exe -m pytest
```
