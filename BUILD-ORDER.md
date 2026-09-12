# BUILD-ORDER — what we study, from which repo, in which order

Rule: study the reference → re-implement in our own code. Nothing is pasted. No credits.
Order follows dependencies: each step only needs the steps above it.

| Step | What we build | Study this (repo → file) | Ours / from ref |
|---|---|---|---|
| 1 | **Data layer**: Bitget client (rToken candles, perp candles, funding, order book, fees), Yahoo native stock, Nasdaq earnings, FRED, RSS; order-book recorder running every minute | `ai-hedge-fund` → `hedge_fund/data/protocol.py` (the *interface* idea: one protocol, mock in tests) | **Ours** (interface idea from ref) |
| 2 | **As-of snapshot**: every feature computed at a timestamp, no look-ahead, content hash | `ai-hedge-fund` → `hedge_fund/features/snapshot.py` | From ref |
| 3 | **Regime classifier**: vol percentile, trend, liquidity → calm/normal/turbulent, up/down/sideways, thinning/normal/surging → label + size multiplier | `AlpacaTradingAgent` → `tradingagents/regime.py` | From ref |
| 4 | **rToken features**: basis level / z-score / widening rate, hour-of-week bucket (US open / closed / weekend), days-to-earnings, macro-event density, book-depth bucket, funding | — | **Ours** |
| 5 | **Analog search**: standardise features → nearest-neighbour → top-N past windows with similarity scores → refuse below min-sample | — (no repo has it) | **Ours** |
| 6 | **Forward outcomes + cohort summary**: return / MFE / MAE per window, PENDING if immature, n, win rate, medians, tags, data-quality flags, min-sample gate | `claude-trading-skills` → `skills/stockbee-20pct-study/scripts/run_20pct_study.py` | From ref |
| 7 | **Distribution statistics**: benchmark-adjusted returns, cumulative windows, t-test, bootstrap CI; leak guards; abstain when thin | `ai-hedge-fund` → `hedge_fund/event_study/stats.py`, `models.py`, `signals/base.py` (abstain) | From ref |
| 8 | **Stress framework + presets**: scenario objects, apply shocks, breach flags; Monte Carlo + reverse stress; block-bootstrap price paths; **preset numbers from our data** (weekend gap, earnings gap, vol ×2/×3, basis blowout, liquidity drought, funding spike, exchange halt) | `AgenticTrading` → `risk_agent_pool/agents/stress_testing.py`; `jesse` → `candle_pipelines/moving_block_bootstrap.py`, `research/monte_carlo/monte_carlo_candles.py` | Framework from refs · presets **ours** |
| 9 | **Exit cost + hedge**: walk live order book for the ticket size → slippage bps, "you can exit $X ≤ 25 bps"; square-root impact as fallback; perp hedge ratio + cost (fees + funding × hours) + residual basis | `AgenticTrading` → `transaction_cost_agent_pool/agents/pre_trade/impact_estimator.py` (formula only) | Book walk + hedge **ours** · impact formula from ref |
| 10 | **Gate + sizing + verdict**: pre-trade checklist (plan? stop? size? risk $), revenge cooldown, position sizer, hard clamps with audit events → GO / REDUCE_TO / HEDGE x% / NO_GO with reasons | `claude-trading-skills` → `pre-trade-discipline-gate`, `position-sizer`; `ai-hedge-fund` → `risk/limits.py`; `hermes` → `schemas/trade_journal_entry.schema.json` (ticket fields) | From refs |
| 11 | **Journal + calibration**: store every ticket; fill outcomes as bars mature; Kupiec / Christoffersen / traffic-light on our forecasts; calibration page | `claude-trading-skills` → `trader-memory-core` (lifecycle idea); `AgenticTrading` → `risk_agent_pool/agents/var_calculator.py` (tests ≈ 60 lines) | From refs |
| 12 | **Chat UI + API + charts**: free-text ticket → parse → run 2–11 → narrative; follow-ups ("hedge half?", "make it $10k"); LLM never invents numbers | — | **Ours** |
| 13 | **Deploy + demo**: always-on host, uptime ping, video, X post, form text | — | **Ours** |

---

## Tier 2 — DEPTH (start after Tier 1 step 13; each adds judge points; order = value ÷ effort)

| Step | What we build | Study this (repo → file) | Ours / from ref | Why this order |
|---|---|---|---|---|
| 14 | **Random-entry significance test**: bootstrap N random windows of the same length on the same history → compare the analog cohort's outcome distribution against chance → p-value + "edge vs random" chart | `jesse` → `mcp/tools/significance_test.py`, `research/monte_carlo/monte_carlo_trades.py` (idea) | From ref | Cheapest big research-quality win; reuses step 5–7 outputs |
| 15 | **VaR / CVaR**: historical + Monte Carlo (from step 8 paths), 95/99 %, expected shortfall; shown next to the analog tail | `AgenticTrading` → `risk_agent_pool/agents/var_calculator.py` | From ref | Two more numbers on the verdict card; paths already exist |
| 16 | **Sensitivity sweep**: shock one factor across a range (gap ×0.5…×3, depth ÷1…÷10) → impact curve | `AgenticTrading` → `stress_testing.py` (sensitivity part) | From ref | Great live-demo moment ("what if the gap is 3×?") |
| 17 | **Lesson memory + postmortem**: when a journaled ticket's window matures → auto-write a plain-language lesson; classify predicted-vs-realised (true/false positive, missed, regime mismatch); surface lessons on similar future tickets | `AlpacaTradingAgent` → `backtest/teach.py`; `claude-trading-skills` → `signal-postmortem` | From refs | Self-improving loop; strengthens "personal thesis" + Demo Day story |
| 18 | **Circuit breaker + posture gate**: daily/weekly/monthly realised-loss limits, losing-streak cooldown → COOLDOWN/HALTED; market posture FULL_RISK / SELECTIVE_ONLY / CASH_PRIORITY / RESEARCH_ONLY with reasons + blocked actions | `claude-trading-skills` → `drawdown-circuit-breaker`; `hermes` → `trading-risk-gate` | From refs | Extra gate layers; cheap once step 10 exists |
| 19 | **Funding-stress + crypto regime component**: funding-rate z-score, drawdown/vol, momentum thrust → one more feature in step 4 and a preset in step 8 | `claude-trading-skills` → `crypto-regime-analyzer/scripts/calculators/` | From ref | Small; adds a data source to the depth count |
| 20 | **Embedding-based regime**: window embeddings → clustering → regime labels + Markov transition matrix (stickiness, most-likely next regime); used as an extra analog feature and shown as "regime map" | `regimetry` → pipeline (ingest → embed → cluster → interpret) | From ref | Polish; only if 14–19 are done |

## Tier 3 — STRETCH (best-version items; after Tier 2, or post-submission for Demo Day / Playbook)

| Step | What we build | Study this | Ours / from ref | Note |
|---|---|---|---|---|
| 21 | **Macro regime composite**: multi-component score (curve, credit, breadth proxies), regime label, transition probability, consistency check | `claude-trading-skills` → `macro-regime-detector/scripts/scorer.py` | From ref | Adds a macro layer to analogs |
| 22 | **Historical slippage analytics**: realised slippage from our recorded order-book snapshots by time bucket (US open / closed / weekend), worst windows; vol-scaled slippage model calibrated on it | `AgenticTrading` → `slippage_analyzer.py`; `AlpacaTradingAgent` → `backtest/engine.py` (`_VolatilitySlippageBroker`) | From refs | Only valuable once the recorder has weeks of data |
| 23 | **GARCH-vol VaR + component / marginal VaR** for multi-position tickets | `AgenticTrading` → `var_calculator.py` | From ref | For portfolio-level use (Open-Theme "Portfolio Copilot" direction) |
| 24 | **Portfolio-aware mode**: how the proposed trade changes beta, concentration, correlation, gross exposure across existing positions; hedge suggestions | `ai-hedge-fund` → `risk/limits.py`, `fund/spec.py` | Mostly ours | Bitget's own suggested Open-Theme idea; strong Playbook fit |
| 25 | **Walk-forward validation of the analog engine**: rolling re-fit, out-of-sample calibration by period | `AlpacaTradingAgent` → `backtest/engine.py` (`run_walk_forward`) | From ref | Turns calibration page into a time-series of trust |
| 26 | **Multi-agent second opinion**: bull / bear / risk critic over the numeric report (LLM debate on top of our data, never replacing it) | `tradingagents` → `agents/risk_mgmt/*`; `FinRobot` debate pattern | Pattern only | Presentation layer; last, because judges score numbers over prose |

**Repos touched: 6 main** (claude-trading-skills, ai-hedge-fund, AgenticTrading, jesse, AlpacaTradingAgent, hermes) **+ regimetry (Tier 2) + tradingagents/FinRobot (Tier 3 pattern only).** Everything else in `my-goal/`: context only.
