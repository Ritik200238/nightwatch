# SPEC — "Nightwatch" (working name): rToken Decision Stress Tester

Track 3 · AI Trading Desk · Sub-theme **Decision Stress Testing**
Official core question: *"Before opening a position, how does AI retrieve historically
similar scenarios?"* Example approach: *"Input trade idea → retrieve historical
distribution; preset stress tests."*

Written 2026-09-10. Deadline 2026-09-21 UTC+8. Sources: `buildathon.md` (rules),
`tools/README.md` (verified Bitget data), `my-goal/README.md` (repo study).

---

## 1. Goal (one sentence)

A trader types a trade idea in plain English; the desk finds the past moments that
looked like now, shows what happened next, runs preset stress tests, checks whether the
position could even be exited on rToken's thin books, and returns a sized
**cut / hold / hedge** recommendation — the human decides.

## 2. Thesis (Project Description part 1 — highest judging weight)

- rTokens trade 24/7; the underlying US stock does not. The dangerous window is the
  closed-market window (nights, weekends, holidays) when news lands and only the rToken
  can reprice.
- **Measured:** the rToken-vs-perp basis is **1.8× wider when the US market is closed**
  (mean |basis| 15.0 bps closed vs 8.4 bps open, n=486 hourly obs, RTSLA). Top-of-book
  depth on rToken spot is **~$175–$210** (RSPY ~$10.6k). Fees 10 bps/side spot,
  2/6 bps perp. All from Bitget public API, 2026-09-10.
- Existing tools (21 repos studied) do preset shocks or LLM narrative; **none retrieve
  data-driven similar scenarios**, none model rToken basis/liquidity, none show
  calibration. That gap is the product.

## 3. Target user (part 2 — "all traders" is rejected)

Retail/pro-retail trader, **$5k–$50k per position**, holding **tokenized US stocks on
Bitget through overnight/weekend windows**, 1–10 trades/week, moderate risk appetite,
primary market = Bitget rToken spot + US-stock perps. Needs: "what's my realistic
downside while the real market is shut, and can I get out?"

## 4. The one complete research task (required demo)

> **Q:** "Should I hold $20k of RNVDA through this weekend? NVDA reports Wednesday."
> **Flow:** parse idea → build "now" feature vector → retrieve nearest past windows →
> outcome distribution (5d, weekend, next-open) → preset stress (gap, vol spike, basis
> blowout, liquidity drought) → exit-cost check on live book → hedge math with NVDAUSDT
> perp → sized verdict with reasons and sample sizes.
> **A:** "Cut to $6k or hedge 60% via perp (2 bps maker). Reasons: … n=41 similar windows,
> 5% tail −7.2%, exit cost at $20k ≈ 38 bps, basis p95 during closed hours 36 bps."

## 5. Architecture

```
[Chat UI]  ──►  [Orchestrator / LUI layer (LLM)]
                    │  parse trade idea → TradeTicket
                    ▼
     ┌──────────────┼──────────────────┬──────────────────┬───────────────┐
     ▼              ▼                  ▼                  ▼               ▼
[Analog Engine] [Stress Library]  [Liquidity/Exit]   [Hedge Calc]   [Calendar/Events]
 (ours)          (from AgenticTrading) (ours + AT impact) (ours)      (FRED/earnings/news)
     └──────────────┴──────────────────┴──────────────────┴───────────────┘
                    ▼
            [Verdict + Sizing]  ← position-sizer / pre-trade gate rules
                    ▼
            [Journal + Calibration]  ← forward outcomes, Kupiec/Christoffersen
```

Backend: **Python (FastAPI)** — donor code is numpy/scipy Python. Frontend: web chat with
charts (React/Next). LLM: Claude (Anthropic API) for parsing + narrative; all numbers come
from code, never from the model.

## 6. Modules

### 6.1 TradeTicket (input) — from `pre-trade-discipline-gate` + hermes journal schema
Fields: symbol (rToken), side, notional, horizon (overnight / weekend / N days),
entry, stop (optional), thesis text, account size. Missing → ask, never assume.

### 6.2 Analog Engine (THE core — we build it; nobody has it)
- Universe: 22 rTokens (7 months, hourly+daily) + 18 US-stock perps + native stock via
  Yahoo (multi-year) for the underlying.
- "Now" feature vector per symbol/time: realized vol (1d/5d/20d), basis level and
  z-score, basis widening rate, hour-of-week bucket (open/closed/weekend), days to
  earnings, macro-event density next 72h, funding rate, distance from 20d high/low,
  book depth bucket.
- Retrieval: standardised kNN (cosine/Mahalanobis) over historical windows; return top
  N with similarity scores; **report n, and refuse a verdict below min-sample** (borrow
  the min-sample guard idea from `stockbee-20pct-study`).
- Outcomes per analog: forward return at horizons, MFE/MAE, max gap at next US open,
  basis path — computed with the `update_forward_outcomes` pattern
  (entry close → future bars → close/MFE/MAE → tag).
- Output: distribution (p5/p25/median/p75/p95), win rate, tag counts, representative
  dates. Two layers: **underlying-stock analogs** (long history) and **rToken overlay**
  (basis/liquidity, short history) — shown separately, sample sizes on both.

### 6.3 Stress Library — adapted from `AgenticTrading/risk_agent_pool/agents/stress_testing.py`
Keep: `StressScenario` / `StressTestResult` dataclasses, sensitivity sweep, Monte Carlo,
reverse stress ("what shock loses X%"), concentration + breach indicators.
Replace their 2008/COVID/rate-shock library with **rToken-native presets**:
- Weekend gap (empirical from data), earnings gap (empirical per symbol), vol spike 2×/3×,
  basis blowout (p95/p99 closed-hours basis), liquidity drought (depth ÷ 5),
  perp funding spike, exchange halt (cannot exit for N hours).
- VaR/CVaR from `var_calculator.py` (parametric, historical, MC, GARCH).

### 6.4 Liquidity / Exit-Cost — ours, with `liquidity_risk.py` impact shape
Walk the live order book for the ticket notional → expected slippage bps; classify
exit time; show "you can exit $X at ≤25 bps". Start **recording order-book snapshots
every minute from day 1** — nobody else will have rToken depth history.

### 6.5 Hedge Calculator — ours
Perp hedge ratio (β≈1, same underlying), cost = 2/6 bps + funding × hours; residual
basis risk shown from 6.2's basis distribution.

### 6.6 Calendar / Events
FRED (FOMC/CPI/NFP dates), earnings dates, RSS news keyword hits for the symbol in the
last 72h. Each one moves the feature vector and is listed in the verdict.

### 6.7 Verdict + Sizing — rules from `position-sizer` + gate logic
Fixed-fractional risk (default 1% of account) against the p5 analog loss; caps from
exit-cost; outputs **GO / REDUCE_TO $N / HEDGE x% / NO_GO** with the reasons in the
gate's style (`GO`, `REVIEW_REQUIRED`, `NO_GO`).

### 6.8 Journal + Calibration — the killer extra
Every ticket stored; forward outcomes filled automatically as bars mature
(`update_forward_outcomes`); calibration page: forecast p5 vs realized, Kupiec POF +
Christoffersen tests (from `var_calculator.py`), traffic-light. Even 11 days of
self-tests + a historical replay over the 7-month window gives a real chart.

## 7. Data sources (feature-depth criterion: count × effectiveness)

| # | Source | Used for | Status |
|---|---|---|---|
| 1 | Bitget spot candles (rTokens) | analog overlay, gaps | ✅ verified |
| 2 | Bitget futures candles + funding (perps) | basis, hedge cost | ✅ verified |
| 3 | Bitget order book | exit cost, depth history | ✅ verified |
| 4 | Bitget symbols/contracts (fees, status) | cost model | ✅ verified |
| 5 | Yahoo Finance chart API `query1.finance.yahoo.com/v8/finance/chart/{sym}` (needs a browser User-Agent) | underlying analogs, multi-year | ✅ verified: NVDA 501 daily bars, 2y |
| 6 | FRED — `fredgraph.csv?id=SERIES` works with **no key**; JSON API needs a free key | macro calendar, yields | ✅ verified (CSV) |
| 7 | **Nasdaq** `api.nasdaq.com/api/calendar/earnings?date=` + `/api/company/{sym}/earnings-surprise` — no key | days-to-earnings, past report dates | ✅ verified. (Yahoo quoteSummary/v7 are blocked — crumb auth.) |
| 8 | RSS: CNBC, MarketWatch, Cointelegraph, Federal Reserve press feed | event density | ✅ verified (Reuters feed is dead) |
| 9 | Bitget funding-rate history + `history-candles` (hourly back to at least May 2026) | funding feature, deep analogs | ✅ verified |
| 10 | Own order-book snapshot recorder | depth history | build day 1 |

Do **not** depend on `datahub.noxiaohao.com` (dead as of 2026-09-10).
Local env note: Python 3.11 present, `pip` not on PATH (use `python -m pip`); no venv yet.

## 8. Deliverables (Project Description part 5 + materials link)

1. Live demo URL (must stay up 9/22 → 10/7; no login wall)
2. Public GitHub repo with README, run instructions, data-recorder logs
3. 3–4 min video: the full research task above, start to finish
4. Research note (in repo): basis-vs-closed-hours study, analog engine method,
   calibration results, all numbers labelled **observed / estimated / targeted**
5. X post with `#BitgetHackathon` `@Bitget_AI` + retweet of official post
6. Form: 6-part description, "Role of the LLM" (Claude: parsing, narrative, tool
   routing; never the numbers), track/sub-theme, Demo Day ✔, K3 ✔

## 9. Judging map

| Criterion | Where we score |
|---|---|
| Feature depth | 8–9 live sources, each changes the answer; listed in UI |
| Research quality | measured basis study, analog distributions with n, calibration tests |
| LUI fluency | free-text ticket → follow-ups ("what if I hedge half?", "make it $10k") |
| Personalised thesis | closed-market rToken holder, $5k–50k, named in UI header |

## 10. Plan (11 days)

| Day | Build |
|---|---|
| 1 | Repo, data layer (sources 1–4), order-book recorder running, Yahoo/FRED/earnings/RSS tests |
| 2–3 | Analog engine v1 (features, kNN, forward outcomes, distributions) + research note draft |
| 4 | Stress library ported + rToken presets; VaR/CVaR |
| 5 | Exit-cost + hedge calc |
| 6–7 | FastAPI + chat UI + charts; LLM ticket parser + narrative |
| 8 | Journal + calibration (historical replay) |
| 9 | Deploy, uptime check, polish LUI, edge cases |
| 10 | Video, X post(s), research note final, form text |
| 11 | Buffer; submit before 9/21 UTC+8 |

X posts throughout (Best Spread Award).

## 11. Risks / unknowns

- rToken history is ~7 months → small rToken-specific samples; mitigated by underlying
  analogs + explicit n and refusal below min-sample.
- Four data sources untested (5–8). Day-1 task.
- Hosting must survive two weeks unattended — pick a paid/always-on tier, add uptime ping.
- LLM must never invent numbers: every figure rendered from code output with source tag.
- Crowding of the sub-theme is an estimate, not data.
