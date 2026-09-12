# COPY-MAP — exactly what we copy, from where, and what we write ourselves

Theme: Decision Stress Testing — *"Before opening a position, how does AI retrieve
historically similar scenarios? Input trade idea → retrieve historical distribution;
preset stress tests."*  Verified against code in `my-goal/` on 2026-09-12.

> **Working rule (set 2026-09-12): this is a STUDY map, not a copy map.**
> Every item marked COPY/ADAPT means: read that reference deeply — logic, edge cases,
> workflow — then **implement it ourselves from first principles** in our own code,
> naming, structure, UI and docs. No pasted source, comments, README text or distinctive
> names. Nothing important gets dropped because it's hard. Before any actual material is
> reused, check the licence and meet its terms (attribution only where required).

Legend: **COPY** = study closely, re-implement the same behaviour + edge cases ·
**ADAPT** = study, re-implement with changes for rToken/hourly data · **OURS** = no
reference exists, design from scratch.

---

## Job 1 — "Before opening a position" (the gate)

| Piece | Source | Action |
|---|---|---|
| Pre-trade checklist gate → `GO / NO_GO / REVIEW_REQUIRED`, revenge-trade window, journal row | `claude-trading-skills/skills/pre-trade-discipline-gate/scripts/check_pre_trade_discipline.py` (MIT, stdlib+yaml) | **COPY** |
| Risk-based sizing (fixed-fractional / ATR / Kelly, concentration caps) | `claude-trading-skills/skills/position-sizer/` | **COPY** |
| Drawdown circuit breaker (daily/weekly/monthly loss limits, losing-streak cooldown) | `claude-trading-skills/skills/drawdown-circuit-breaker/` | **COPY** |
| Thesis lifecycle + postmortem (IDEA → ENTRY_READY → ACTIVE → CLOSED, MAE/MFE) | `claude-trading-skills/skills/trader-memory-core/scripts/thesis_store.py` | **COPY** |
| Trade-ticket schema (ticker, direction, entry, stop, thesis, invalidation, review plan) | `hermes-…/schemas/trade_journal_entry.schema.json` | **COPY** |
| Risk-gate states `FULL_RISK_ALLOWED / SELECTIVE_ONLY / CASH_PRIORITY / RESEARCH_ONLY` | `hermes-…/skills/trading-risk-gate/SKILL.md` | **COPY** (as our posture labels) |
| Hard position/gross clamp with audit events | `ai-hedge-fund/hedge_fund/risk/limits.py` (`apply_limits`, `ClampEvent`) | **COPY** |

## Job 2 — "Retrieve historically similar scenarios → historical distribution"

### 2a. Describe "now" (the feature vector) — building blocks exist
| Piece | Source | Action |
|---|---|---|
| Volatility percentile, trend state, liquidity ratio → regime label + risk multiplier (pure pandas, loader injected) | `AlpacaTradingAgent/tradingagents/regime.py` (`classify_regime`, `RegimeConfig`) (Apache) | **COPY** |
| Funding-rate, drawdown/vol, momentum-thrust calculators (keyless crypto data) | `claude-trading-skills/skills/crypto-regime-analyzer/scripts/calculators/*.py` | **ADAPT** to Bitget funding |
| Macro regime composite score + transition probability | `claude-trading-skills/skills/macro-regime-detector/scripts/scorer.py` | **ADAPT** (feed FRED CSV) |
| Point-in-time "as-of" snapshot discipline (no look-ahead), content hash | `ai-hedge-fund/hedge_fund/features/snapshot.py` | **ADAPT** pattern |
| rToken-specific features: basis vs perp (level, z-score, widening rate), hour-of-week bucket (US open / closed / weekend), days-to-earnings, macro-event density, book-depth bucket | — | **OURS** |

### 2b. Find the similar past moments — nobody has it
| Piece | Source | Action |
|---|---|---|
| Numeric nearest-neighbour search over historical feature vectors (standardise → distance → top-N with scores; refuse below min-sample) | none of the 21 (only text-embedding memories: `AlpacaTradingAgent/…/memory.py` = OpenAI+chromadb; `AgenticTrading/…/intelligent_memory_indexer.py` = sklearn cosine on text) | **OURS** (~200–300 lines, scikit-learn `NearestNeighbors`) |
| "Situation → lesson" narrative memory idea (store what happened after similar setups; LLM reads it back) | `AlpacaTradingAgent/tradingagents/backtest/teach.py` (`compute_decision_outcomes`, `_deterministic_lesson`) | **ADAPT** idea only (no OpenAI/chromadb) |

### 2c. Measure what happened after them (the distribution)
| Piece | Source | Action |
|---|---|---|
| Forward outcomes per event: entry close → future bars → close return, MFE, MAE, outcome tag; PENDING when window not matured | `claude-trading-skills/skills/stockbee-20pct-study/scripts/run_20pct_study.py` (`update_forward_outcomes`, `classify_outcome`) | **COPY** |
| Cohort summary: sample size, win rate, medians, tag counts, data-quality flags, min-sample guard for any "rule" | same file (`summarize_cohorts`, `candidate_rule_from_cohort`) | **COPY** |
| Market-model abnormal returns, cumulative windows, t-test, **bootstrap confidence intervals** | `ai-hedge-fund/hedge_fund/event_study/stats.py` (`fit_market_model`, `compute_abnormal_returns`, `sum_car`, `ttest_cars`, `bootstrap_ci`) | **COPY** (benchmark = perp or native stock instead of SPY) |
| Result models (`EventCAR`, `WindowStats`, `BootstrapCI`, `AggregateResult`) + CAR distribution plots | `ai-hedge-fund/hedge_fund/event_study/models.py`, `plot.py` | **COPY** |
| Orchestration (`engine.py`) | earnings-only, SPY, daily bars, FinancialDatasets client | **REWRITE** for analog windows on hourly rToken data |
| Data access | `ai-hedge-fund/hedge_fund/data/protocol.py` (`DataClient` protocol; tests use a mock) | **COPY** protocol → write `BitgetDataClient` (**OURS**) |

## Job 3 — "Preset stress tests"

| Piece | Source | Action |
|---|---|---|
| Scenario framework: `StressScenario` / `StressTestResult` / `PortfolioPosition` dataclasses, `run_stress_test`, sensitivity sweep, `run_monte_carlo_stress`, `run_reverse_stress_test`, concentration (HHI) + breach indicators | `AgenticTrading/…/risk_agent_pool/agents/stress_testing.py` (OpenMDW; numpy/pandas only) | **COPY** framework · **DROP** its 2008/COVID/rate presets · **DROP** `_calculate_stress_risk_metrics` (hard-codes "assume 5% VaR") |
| VaR / CVaR (parametric, historical, Monte Carlo, GARCH) + **Kupiec POF, Christoffersen independence & conditional-coverage tests, Basel traffic light** | `AgenticTrading/…/risk_agent_pool/agents/var_calculator.py` | **COPY** the methods (~150 lines; drop `BaseRiskAgent` inheritance) |
| Square-root market-impact model (impact ∝ √(qty/volume)·σ, regime & time-of-day multipliers, temp/perm split) | `AgenticTrading/…/transaction_cost_agent_pool/agents/pre_trade/impact_estimator.py` (`SquareRootImpactModel`) | **ADAPT** formula only — file has bugs (`current_price = (bid_size+ask_size)/2` uses sizes; `calibrate()` is mock) |
| Slippage pattern by time-of-day (`_categorize_time`) | `AgenticTrading/…/transaction_cost_agent_pool/agents/post_trade/slippage_analyzer.py` | **ADAPT** buckets to US-open / closed / weekend |
| Volatility-scaled slippage (min/max bps, vol fraction) | `AlpacaTradingAgent/tradingagents/backtest/engine.py` (`_VolatilitySlippageBroker`) | **ADAPT** formula |
| Gap % (open vs previous close) | `AlpacaTradingAgent/tradingagents/dataflows/technical_brief.py` L436 | **COPY** one-liner; compute weekend/overnight gaps ourselves |
| Moving-block bootstrap of candles → synthetic price paths for Monte Carlo (numpy only) + CI aggregation | `jesse/jesse/candle_pipelines/moving_block_bootstrap.py`, `jesse/research/monte_carlo/monte_carlo_candles.py` (`_calculate_confidence_intervals_candles`) (MIT) | **COPY** |
| The actual presets and their numbers: weekend gap, earnings gap, vol spike ×2/×3, basis blowout (p95/p99 closed-hours basis), liquidity drought (depth ÷ 5), funding spike, exchange halt (can't exit N hours) | — (measured from our Bitget / Yahoo / Nasdaq data) | **OURS** |
| Live order-book walk → expected slippage for the ticket notional; "you can exit $X at ≤ 25 bps" | — (Bitget order book, verified) | **OURS** |
| Perp hedge ratio + cost (2/6 bps + funding × hours) + residual basis risk | — | **OURS** |

## Not copied (and why)
- `ai-market` — no LICENSE file. `live-trade-bench` — PolyForm Noncommercial. `AI-Trader` — no LICENSE file.
- `AlpacaTradingAgent/…/memory.py` — OpenAI embeddings + chromadb lock-in; idea only.
- `tradingagents` risk debators — LLM prompts, no math.
- `FinRobot` (AutoGen/OpenAI), `qlib`, `FinRL`, `freqtrade`, `FAgent` (cite CVaR paper only), `PrimoAgent`, `autonomous-llm-trading-agents`, `FinLLM-Leaderboard`, `Portfolio-Optimization-DRL`.

## Licences we ship with
MIT (claude-trading-skills, hermes, ai-hedge-fund, jesse) · Apache-2.0 (AlpacaTradingAgent — keep NOTICE) ·
OpenMDW-1.0 (AgenticTrading — keep licence text + notices in our repo).
