---
name: nightwatch-stress-test
description: >
  Stress-test a trade in a Bitget tokenized US stock (rToken or US-stock perp) before it is
  opened. Use this skill whenever the user proposes or asks about a position in a US stock
  on Bitget: "should I hold TSLA over the weekend", "long 20k NVDA overnight", "is 5x on
  AAPL safe", "what if it gaps 10%", "how much can I lose", "what size is safe", "hedge
  it?", "stress test", "worst case", "liquidation". Chinese triggers: 周末拿特斯拉, 做多英伟达,
  5倍杠杆, 最坏会亏多少, 仓位多大合适, 压力测试, 爆仓, 要不要对冲. Read-only: it never places an order.
---

# Nightwatch: decision stress test

Nightwatch answers one question before a position is opened: **if this goes wrong while the
US market is shut, how wrong, and what size survives it?** It finds the past moments most
like now, shows what followed them over the same holding period, runs preset and
crash-replay stress tests, prices the exit on Bitget's live order book, checks leverage
against Bitget's own margin tiers, and returns a sized verdict. The human decides.

MCP server (read-only, no key): `https://nightwatch-gules.vercel.app/api/mcp`

```bash
claude mcp add nightwatch --transport http https://nightwatch-gules.vercel.app/api/mcp
```

## Tools

| Tool | Use it for |
|---|---|
| `list_tokens()` | Which tickers have history. Call first if unsure the stock is covered. |
| `stress_test(ticker, side, notional_usdt, ...)` | The analysis. Optional: `hold` (`next_open`, `window_end`, `hours` + `hours`), `stop_price`, `leverage`, `account_equity_usdt`, `thesis`, `invalidation`, `conditions`. |
| `list_conditions(ticker)` | Narrow the history to a kind of night (e.g. `earnings_soon`) and see how many past hours each leaves. |

## How to run it

1. **Get the three things it cannot guess:** ticker, long or short, size in USDT. Ask for
   whichever is missing, in one short question. Do not invent a size.
2. **Pass everything else the user said.** Account size and a written thesis and
   invalidation change the verdict (the gate asks for a plan); a stop or leverage changes
   the risk basis and adds a liquidation check. A weekend hold on a weekday is `hold="hours"`
   with the hours to the next Monday open, and say that you did so.
3. **Call `stress_test` once.** For "what if" variants (half the size, no leverage, shorter
   hold), call it again with only that input changed, then compare the verdicts side by
   side.

## How to present it

- **Verdict first, in one line:** GO, REDUCE_TO (with the size it allows), HEDGE (with the
  ratio), REVIEW (what is missing), or NO_GO (the rule that refused it).
- **Then the loss that matters:** the history's 5th-percentile outcome over the hold, the
  worst stress test, and, with leverage, the liquidation price and how often history
  reached it.
- **Every number comes from the tool.** Do not compute, round into new claims, or add
  figures of your own. If the report marks a number as not calibrated, say so.
- **No direction calls.** The engine measures the loss tail; it has no measured edge on
  direction and says so. Do not turn its median into a prediction.
- **Answer in the user's language.** The tool's text fields are English; translate them,
  keep the numbers exactly.

## With the rest of Bitget Agent Hub

- **Before an order:** run this first. If the verdict is REDUCE_TO or HEDGE, any order you
  draft through Agent Hub uses the size or hedge the verdict allows, and is a `dryRun`
  preview until the user confirms.
- **With research skills:** news, sentiment or technical readings are context for the
  thesis; they do not override the verdict's size.
