# FEATURES — candidate list from the references, and the final pick

Internal planning doc. Sources in brackets are *study references only* (see
`COPY-MAP.md` working rule): everything is re-implemented by us; nothing ships from them.

Deadline 2026-09-21 (9 days from 2026-09-12). Theme = Decision Stress Testing:
(1) before opening a position → (2) retrieve similar scenarios / distribution → (3) preset stress tests.

---

## A. The 30 candidate features (what the references taught us)

### Gate & discipline (Job 1)
| # | Feature | Behaviour to preserve | Ref |
|---|---|---|---|
| 1 | **Pre-trade discipline gate** | Plan written? stop predefined? size within plan? planned-risk-$ vs actual-risk-$; invalid/missing inputs → REVIEW_REQUIRED, never silently pass; aggregate → GO / NO_GO / REVIEW_REQUIRED / NO_ACTIONABLE | claude-trading-skills |
| 2 | **Revenge-trade cooldown** | A losing exit within the last N hours blocks new entries | claude-trading-skills |
| 3 | **Drawdown circuit breaker** | Daily / weekly / monthly realised-loss limits + losing-streak cooldown → COOLDOWN / HALTED; duplicate-state → halt until fixed | claude-trading-skills |
| 4 | **Market posture gate** | FULL_RISK / SELECTIVE_ONLY / CASH_PRIORITY / RESEARCH_ONLY with reasons, blocked & allowed actions, missing-data list | hermes |
| 5 | **Position sizer** | Fixed-fractional risk %, ATR-based stop distance, Kelly from win/loss stats; concentration caps; whole vs fractional units | claude-trading-skills |
| 6 | **Hard exposure clamps** | Per-position and gross limits applied in order, each clamp recorded as an audit event; clamped exposure never redistributed | ai-hedge-fund |
| 7 | **Thesis journal lifecycle** | IDEA → ENTRY_READY → ACTIVE → CLOSED; review-due dates; linked reports; postmortem with P&L + MAE/MFE | claude-trading-skills |
| 8 | **Trade ticket schema** | ticker, side, entry, stop, target, risk $, setup, thesis, invalidation, regime, review plan | hermes |

### Describe "now" & find similar (Job 2)
| # | Feature | Behaviour to preserve | Ref |
|---|---|---|---|
| 9 | **Regime classifier** | Rolling vol percentile vs 1-yr history (+ absolute vol floor), trend vs SMA & its slope, share-volume vs *preceding* baseline → calm/normal/turbulent · up/down/sideways · thinning/normal/surging → favorable/mixed/hostile + size multiplier with floor | AlpacaTradingAgent |
| 10 | **Crypto regime components** | Funding-rate stress, drawdown/vol, momentum thrust → 0–100 composite | claude-trading-skills |
| 11 | **Macro regime composite** | Multi-component score, regime label, transition probability, consistency check | claude-trading-skills |
| 12 | **Point-in-time snapshot** | Every feature computed "as of" a timestamp; content hash for reproducibility; insufficient data raises, never guesses | ai-hedge-fund |
| 13 | **Forward outcomes per event** | Entry close → next H bars → close return, MFE, MAE (directional variants); PENDING when window not matured; outcome tags | claude-trading-skills |
| 14 | **Cohort summary** | n, win rate, medians, tag counts, data-quality flag counts, representative examples; **min-sample gate** before any conclusion | claude-trading-skills |
| 15 | **Abnormal-return statistics** | Market-model fit on estimation window, abnormal returns on event window, cumulative windows, t-test, **bootstrap CI** | ai-hedge-fund |
| 16 | **Leak guards** | Buffer between estimation and event windows; drop events whose data was only known later | ai-hedge-fund |
| 17 | **Situation → lesson memory** | When an outcome matures, auto-write a plain-language lesson; surface it when a similar situation appears | AlpacaTradingAgent |
| 18 | **Signal postmortem** | Predicted direction vs realised at 5d/20d → true/false positive, missed, regime mismatch; feed back into weights | claude-trading-skills |
| 19 | **Explicit abstain** | Model returns "no view" + reason when data is thin instead of a fake number | ai-hedge-fund |
| 20 | **Random-entry significance test** | Compare the setup's outcomes to a bootstrap of random entries on the same history — "is this better than chance?" | jesse |

### Stress & risk (Job 3)
| # | Feature | Behaviour to preserve | Ref |
|---|---|---|---|
| 21 | **Scenario framework** | Scenario = id, severity, factor shocks, probability, horizon; apply to positions; portfolio impact; breach flags (loss, concentration, liquidity) | AgenticTrading |
| 22 | **Sensitivity sweep** | Shock one factor across a range → impact curve → local sensitivity | AgenticTrading |
| 23 | **Monte Carlo + reverse stress** | Correlated-factor MC; reverse: search for the shock that produces a target loss | AgenticTrading |
| 24 | **VaR / CVaR family** | Parametric, historical, Monte Carlo (GARCH-vol optional); expected shortfall | AgenticTrading |
| 25 | **Calibration tests** | Kupiec POF, Christoffersen independence & conditional coverage, quantile loss, traffic light | AgenticTrading |
| 26 | **Square-root market impact** | Impact ∝ √(qty / volume) × σ, regime & time-of-day multipliers, temporary vs permanent split | AgenticTrading |
| 27 | **Slippage by time bucket** | Realised slippage grouped by time-of-day; worst trades | AgenticTrading |
| 28 | **Vol-scaled slippage** | Slippage bps scales with recent volatility, clamped min/max | AlpacaTradingAgent |
| 29 | **Block-bootstrap price paths** | Moving-block bootstrap of (Δclose, Δhigh, Δlow) → synthetic paths preserving short-range dependence → CI on outcomes | jesse |
| 30 | **Data-quality flags** | Every result carries flags (gaps, stale bars, thin samples) that propagate to the summary | claude-trading-skills |

---

## B. The pick — what we actually build

Judged on: feature depth (count × effectiveness), research quality, LUI fluency, personal thesis. 9 days. Our data: rToken hourly (7 mo), perps + funding, native stock (2 y), order book (live), Nasdaq earnings, FRED, RSS.

### Tier 1 — CORE (ships no matter what; this *is* the product)
| From list | Why it's essential |
|---|---|
| 1 Gate + 2 Revenge cooldown | Literal "before opening a position". Cheap, visible, judges get it instantly. |
| 8 Ticket schema | The input contract for the whole chat flow. |
| 9 Regime classifier + 12 As-of snapshot | The "describe now" half of similarity; leak-proof by construction. |
| **OURS: rToken features** (basis level/z/widening, hour-of-week bucket, days-to-earnings, macro-event density, book-depth bucket) | The features that make this *rToken* stress testing, not generic. |
| **OURS: nearest-neighbour analog search** (standardise → distance → top-N with scores → min-sample refusal) | The literal core question. Nobody has it. |
| 13 Forward outcomes + 14 Cohort summary + 19 Abstain + 30 Data-quality flags | Turns retrieved windows into an honest distribution with n and flags. |
| 15 Bootstrap statistics + 16 Leak guards | Research-quality signal: confidence intervals, not point guesses. |
| 21 Scenario framework + 23 MC & reverse stress + 29 Block-bootstrap paths | "Preset stress tests", done properly. |
| **OURS: rToken presets from data** (weekend gap, earnings gap, vol ×2/×3, basis blowout p95/p99, liquidity drought, funding spike, exchange halt) | The numbers that make the presets real. |
| 26 Square-root impact + **OURS: live order-book walk** → exit cost, "you can exit $X ≤ 25 bps" | The $200-deep-book problem, quantified. |
| **OURS: perp hedge calculator** (ratio, 2/6 bps + funding × hours, residual basis) | Turns the verdict into an action. |
| 5 Position sizer + 6 Hard clamps | Sized verdict: GO / REDUCE_TO / HEDGE x% / NO_GO. |
| 25 Calibration tests | The "killer extra": proof forecasts matched reality. |
| **OURS: chat LUI + Bitget data client + charts** | The accessible demo; LLM only parses & narrates, never invents numbers. |

### Tier 2 — DEPTH (do after Tier 1; each adds judge points cheaply)
| From list | Why |
|---|---|
| 20 Random-entry significance test | One extra chart: "this setup vs chance". Strong research signal, ~1 day. |
| 24 Historical + MC VaR/CVaR | Adds two more numbers to the verdict; reuses MC paths. |
| 22 Sensitivity sweep | "How bad if the gap is 2× / 3×?" — good demo moment. |
| 7 Thesis journal (simplified) + 17 Lesson memory + 18 Postmortem | Self-improving loop; strengthens "personal thesis" and Demo Day story. |
| 3 Circuit breaker + 4 Posture gate | Extra gate layers; cheap once 1 exists. |
| 10 Crypto regime components | Funding stress feature; small. |

### Tier 3 — STRETCH (not cut — built after Tier 2, or post-submission for Demo Day / Playbook; full order in `BUILD-ORDER.md` steps 21–26)
| From list | When it pays off |
|---|---|
| 11 Macro composite | Adds a macro layer to analogs once core + Tier 2 are solid. |
| 27 Slippage by time bucket / 28 Vol-scaled slippage | Once the order-book recorder has weeks of snapshots to calibrate on. |
| GARCH-vol VaR, component/marginal VaR + portfolio-aware mode | Multi-position tickets; Bitget's suggested "Portfolio Copilot" direction; Playbook fit. |
| Walk-forward validation; multi-agent second opinion | Deepens calibration; presentation layer on top of our numbers. |

### Sanity check on time (9 days)
Tier 1 ≈ 6–7 days (data layer + recorder 1, features + analog engine 2, outcomes/stats 1, stress + impact + hedge 1, LUI + charts + verdict 1–2). Tier 2 ≈ 1–2 days. Day 9 = deploy, video, X post, form. Tight but real; Tier 2 items drop first if needed, never Tier 1.
