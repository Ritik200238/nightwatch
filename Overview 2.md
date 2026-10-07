# Nightwatch: Comprehensive Product and Technical Overview

> **Single Source of Truth**  
> *Target File:* `Overview 2.md`  
> *Repository:* Nightwatch (`Ritik200238/nightwatch`)  
> *Codebase Freeze:* `method-freeze-3` (`630697a2409881a5b8ab6216d384e6ac0082a1f6`, frozen 2026-10-07)  
> *Deployment Target:* [nightwatch-gules.vercel.app](https://nightwatch-gules.vercel.app)  

---

## 1. Product Overview

### 1.1 Product Name
**Nightwatch** — A Decision Stress Tester for Tokenized US Stocks (rTokens) on Bitget.

### 1.2 One-Line Description
A pre-trade risk desk for tokenized US equities that stress-tests positions against real crashes, past analog moments, and live Bitget order books before you place a trade, giving a mathematically sized verdict scored in public.

### 1.3 Detailed Product Description
Nightwatch is an institutional-grade pre-trade intelligence and risk analytics platform built specifically for tokenized US equities (rTokens, e.g., `rTSLA`, `rNVDA`, `rAAPL`) and their corresponding perpetual futures on Bitget. 

While US equity cash markets trade for only 6.5 hours a day (9:30 AM to 4:00 PM Eastern Time, Monday through Friday), their synthetic tokenized counterparts on cryptocurrency exchanges trade 24 hours a day, 7 days a week, 365 days a year. During nights, weekends, and federal holidays, traditional price discovery halts. When material corporate announcements, earnings releases, geopolitical developments, or macroeconomic data land during closed-market hours, the token reprices on an illiquid, thinned crypto order book. When regular US trading re-opens, the underlying equity often gaps violently, causing massive basis dislocations, slippage, and sudden liquidations for leveraged traders.

Nightwatch acts as a rigorous filter before an order is drafted or executed. It accepts trade intentions in plain natural language (English or Simplified Chinese) or through a structured parameters ticket. It then executes an auditable, six-stage deterministic pipeline:
1. **Retrieval**: Searches the token's own and pooled hourly historical records for past moments that match current volatility, basis, and macroeconomic regimes.
2. **Distribution**: Computes the empirical distribution of forward returns over the exact target holding window.
3. **Stress Testing**: Subjects the trade to rToken-native empirical stress presets (weekend gaps, earnings gaps, volatility shocks, fair-value blowouts, book droughts, exchange halts) alongside historical crash replays (COVID-19, 2022 Inflation Shock, March 2023 US Banking Crisis, August 2024 Carry Trade Unwind, April 2025 Tariff Shock).
4. **Execution & Liquidity Modeling**: Walks Bitget's live level-2 order book depth for the exact requested position size to compute true market impact, slippage, and immediate exit costs.
5. **Decision & Sizing Gate**: Evaluates the position against strict Kelly/volatility/liquidity limits, margin tier maintenance, user risk budgets, portfolio concentration caps, and personal circuit breakers to issue a concrete, bounded verdict: **`GO`**, **`REDUCE_TO`**, **`HEDGE`**, **`REVIEW`**, or **`NO_GO`**.
6. **Public Accountable Journaling**: Cryptographically hashes each verdict into a tamper-evident SHA-256 chain, anchors the hash daily to the Bitcoin blockchain via OpenTimestamps, and grades forecasts against reality once the holding window matures.

Nightwatch never executes orders autonomously. The human trader or orchestrating agent retains final discretion.

### 1.4 Core Problem
Traders holding tokenized US stocks during closed-market windows face four fundamental vulnerabilities:
1. **Blindness to Regime Dynamics**: Traditional equity tools (Bloomberg, FactSet, TradingView) go dark outside US market hours and do not account for crypto liquidity dynamics or token basis divergence.
2. **Asymmetric Gap and Liquidity Shocks**: Token order books at 3:00 AM on Sunday morning are drastically thinner than cash equity books at 2:00 PM on Tuesday. A modest sell-off can cascade down the book, triggering severe slippage or liquidation.
3. **LLM Hallucination in Trading**: Generic AI chatbots ("fintech copilots") invent financial numbers, hallucinate price targets, hallucinate nonexistent news, and offer generic, ungrounded optimism ("looks bullish!") without verifying whether liquidity exists to exit.
4. **Lack of Verifiable Track Records**: Most algorithmic and AI trading platforms make unverifiable marketing claims without publishing their historical errors, false predictions, or empirical calibration rates.

### 1.5 Why the Problem Matters
With the rapid expansion of Real-World Assets (RWAs) and 24/7 tokenized securities on platforms like Bitget, billions of dollars of equity volume are transitioning to crypto venues. Retail and semi-professional traders routinely take 5×–20× leverage on perpetual contracts for synthetic equities over weekends. Without pre-trade stress testing, retail capital is routinely wiped out by routine weekend basis blowouts and Monday morning opening gaps.

### 1.6 Target Users
1. **Primary**: Retail and semi-pro crypto traders on Bitget holding or intending to hold rTokens (`rTSLA`, `rNVDA`, `rAAPL`, `rSPY`, `rQQQ`, etc.) or perp futures across nights and weekends.
2. **Autonomous AI Agents & Developers**: Automated trading agents operating on Bitget Agent Hub or external autonomous execution loops needing a read-only risk validation engine before broadcasting orders (accessed via Model Context Protocol / MCP or the Nightwatch Skill).
3. **Risk-Conscious Desk Operators & Auditors**: Fund managers and evaluators seeking mathematically rigorous, publicly auditable risk assessments with immutable Bitcoin-anchored receipts.

### 1.7 Product Value Proposition
- **Turn Natural Language into Quantitative Safety**: Type *"long 20k TSLA over the weekend"* or *"周末做多特斯拉 2万U"* and receive institutional-grade VaR, crash replays, and order-book exit costs in under 5 seconds.
- **Guardrail Against Hallucinations**: Every single numerical figure displayed is generated by deterministic Python algorithms and labeled with its source and freshness. The LLM is restricted to reading and synthesizing text; any hallucinated number is intercepted and stripped.
- **Provable Calibration**: An open, self-auditing calibration record demonstrating that its stated 5% tail risk (`p5` line) actually breaches approximately 5% of the time, complete with cryptographic receipts and a dedicated public page listing every historical miss.

### 1.8 Key Differentiators
| Dimension | Generic AI Chatbot / FinTech App | Nightwatch Pre-Trade Desk |
| :--- | :--- | :--- |
| **Past Analogs** | Unsubstantiated claims or none | Formal k-NN retrieval with Mahalanobis distance, whitening, and episode deduplication across 24 tokens. |
| **Stress Testing** | Generic percentage drops | 15+ token-native presets fitted from empirical history, scaled by session calendar and holding length, plus real crash replays. |
| **Exit Cost** | Assumes infinite mid-market liquidity | Walks Bitget's live Level-2 order book up to $500,000 depth, calculating exact slippage, cost curve, and liquidity drought risk. |
| **Leverage Safety** | Ignored or linear margin formula | Full 2×–20× liquidation ladder derived from Bitget's published perpetual margin tiers, verified against analog paths. |
| **Integrity & Receipts**| Closed-box claims | Public SHA-256 hash-chained receipts anchored into Bitcoin blocks via OpenTimestamps (`.ots` proofs). |
| **Treatment of Misses**| Buried or deleted | Publicly cataloged on `/wrong`, scored automatically once holds mature. |
| **Directional Bias** | Claims predictive alpha | Openly states **zero directional edge**; focuses strictly on downside sizing and risk containment. |

### 1.9 Current Product Maturity
- **Core Engine & Deterministic Pipeline**: Production-grade (`v0.1.0`), frozen at `method-freeze-3`.
- **Backend API**: Production-deployed FastAPI with threadpool offloading, rate limiting, and memory caching.
- **Frontend Desk**: Production-deployed Next.js 16 (App Router) on Vercel with streaming SSE, bilingual support (EN/ZH), and client-side fallback snapshot caching.
- **Active Tokens**: 24 core tokenized US equities with active historical data syncing; pipeline architecture prepared for 112 tokens.
- **Real-World User Adoption**: Early-stage / evaluation phase (tested rigorously in automated test harnesses and hackathon judging; outside adoption currently monitored via `/usage`).

---

## 2. Vision & Mission

### 2.1 Long-Term Vision
To establish the universal safety and risk verification layer for 24/7 global synthetic asset markets, ensuring that no autonomous agent or human trader ever enters an off-hours derivatives or tokenized position without mathematically understanding and pricing its tail risk.

### 2.2 Product Mission
Empower traders with complete, transparent, and unembellished risk intelligence for tokenized equities by grounding every recommendation in historical truth, live order-book reality, and tamper-evident mathematics.

### 2.3 Core Philosophy
1. **"The Human Decides; the Machine Informs"**: Nightwatch will never autonomously broadcast an order to an exchange. Its role is purely diagnostic and protective.
2. **"LLMs are Analysts, Not Fortune-Tellers"**: Generative AI must never calculate a price, derive a percentile, determine a liquidation barrier, or issue a sizing decision. AI parses user intent, reads structured data, and translates insights into plain language.
3. **"Closer is Not Tighter"**: Mathematical elegance must yield to empirical validation. When internal studies revealed that weighting nearby historical neighbors worsened out-of-sample calibration, the complex weighting scheme was eliminated in favor of robust unweighted cohorts.
4. **"If a Judge or Trader Can Break Our Claim, We Must Break It First"**: Disclose all negative findings, unproven hypotheses, and calibration breaches in public view.

### 2.4 Present Implementation vs. Future Vision
```
+-----------------------------------------------------------------------------+
|                           CURRENT IMPLEMENTATION                            |
|  - 24 Core rTokens & Perps on Bitget                                        |
|  - In-process SQLite DB with WAL mode                                       |
|  - Bitget Level-2 Order Book Polling (every 60s)                            |
|  - Read-only MCP Server & Bitget Agent Hub Skill file                       |
|  - Webhook-based Tripwires and Re-checks                                    |
|  - Public Calibration, Bitcoin Anchors, and Misses Track Record             |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                                FUTURE VISION                                |
|  - 100+ Tokenized Equities, ETFs, and Commodities                           |
|  - High-availability distributed timescale/cluster storage                 |
|  - Sub-second WebSocket order-book streaming                                |
|  - Multi-exchange cross-venue rToken aggregation (Binance, Bybit, OKX, etc.) |
|  - Direct Bitget API OAuth integration for 1-click book syncing             |
|  - Push notifications via Telegram, WhatsApp, and Mobile App                |
+-----------------------------------------------------------------------------+
```

---

## 3. Product Goals

### 3.1 Primary Goals
- Provide sub-5-second, institutional-grade risk diagnostics for any proposed tokenized US stock trade.
- Prevent capital wipeouts caused by off-hours holding, illiquid order books, and high leverage.

### 3.2 User Goals
- Quickly understand how an off-hours trade idea can fail before committing USDT.
- Determine the maximum safe position size and optimal stop-loss placement given personal equity.
- Identify whether current token prices deviate from underlying fair value.
- Receive alerts when price levels approach stop-loss, liquidation, or 1-in-20 tail loss points.

### 3.3 Product Goals
- Deliver an intuitive terminal interface that accepts messy natural language in English and Chinese without requiring financial engineering expertise.
- Maintain transparent public track records (`/calibration`, `/wrong`, `/studies`) that establish trust.
- Provide interoperable integrations for AI agents via Model Context Protocol (MCP) and custom agent skills.

### 3.4 Technical Goals
- Keep deterministic risk pipeline execution times under 2 seconds on standard server hardware.
- Maintain zero-downtime availability using intelligent client-side snapshot fallbacks (`src/snapshot/index.ts`).
- Enforce strict statistical calibration: the empirical breach rate of the 95th-percentile loss (`p5`) must remain statistically bounded near 5.0% across all evaluated hold horizons.
- Ensure 100% trace integrity in the SHA-256 receipt chain with daily Bitcoin block confirmations.

### 3.5 Success Criteria (Measurable Project Milestones)
- **Calibration Precision**: Empirical tail breach rate within 3.0%–5.5% on out-of-sample forward forecasts.
- **Test Integrity**: Over 1,500 automated tests passing across 104 test suites in CI (`ci.yml`).
- **Zero Hallucination Rate**: Zero unverified numbers bypassing the `unverified_numbers` guardrails in user-facing LLM outputs.
- **Uptime & Smoke Verification**: Automated Playwright end-to-end smoke tests passing every 30 minutes on production (`browser-smoke.yml`).

---

## 4. Complete Feature Inventory

### Feature 1: Natural Language Trade Intake & Intent Parser
- **Purpose**: Translates free-form trader input (English or Chinese) into a strongly typed `TradeTicket`.
- **Problem Solved**: Eliminates cumbersome multi-step parameter entry forms for fast-moving traders.
- **User Experience**: Users type natural sentences such as *"Long 15k TSLA over the weekend stop 380"* or *"周末做多特斯拉 2万U"*. The system responds with an instant confirmation card: *"I read this as Long TSLA, 20,000 USDT, Hold until Monday Open"*.
- **Technical Implementation**:
  - Implemented in `nightwatch/api/llm.py` (`parse_intent`), `nightwatch/api/intake.py`, and `nightwatch/api/intake_zh.py`.
  - Uses a **dual-engine architecture**: An ultra-fast regex-based parser (`intake.py`) extracts tickers, notionals, sides, stops, leverage, and horizons in <1 ms. If ambiguity or complex phrasing exists, the system delegates to an LLM provider (Anthropic Claude or Qwen 3.8 Max) with Pydantic JSON schema constraints (`ParsedIntent`).
  - Contains Chinese-specific numeral parsers (`"2万U"` -> `20,000 USDT`).
  - Guards against hostile inputs, negative sizes, and malformed structures.
- **Status**: **Fully Implemented and Verified**.

### Feature 2: Analog Engine (Historical k-NN Retrieval)
- **Purpose**: Discovers historically comparable market moments to evaluate forward empirical distributions.
- **Problem Solved**: Replaces speculative forecasting with empirical precedent.
- **Technical Implementation**:
  - Implemented in `nightwatch/analog/engine.py`, `lens.py`, and `outcomes.py`.
  - Constructs a normalized feature vector: 3 volatility metrics (realized vol, Parkinson vol, Garman-Klass vol), basis divergence (token vs. equity close), relative liquidity (book depth / historical median), and event proximities (hours to earnings, hours to FOMC).
  - Normalizes features using historical median and Median Absolute Deviation (MAD) to prevent outlier distortion.
  - Applies **Cholesky whitening** (Mahalanobis distance) to eliminate collinearity between correlated volatility features.
  - Implements **Episode Deduplication**: Matches within `min_separation_h` (typically 36 hours) are deduplicated so the top $k=80$ neighbors represent distinct market episodes rather than consecutive hours of the same shock.
  - **Pooled Fallback**: If a token's individual history yields fewer than the required distinct episodes (e.g., newly listed tokens), the engine pools across normalized features of all 24 covered tokens.
- **Status**: **Fully Implemented and Frozen** (`method-freeze-3`).

### Feature 3: Empirical Stress-Test Scenarios & Crash Replays
- **Purpose**: Evaluates position resilience under extreme historical and synthetic shock conditions.
- **Problem Solved**: Standard Value-at-Risk (VaR) models assume normal distributions and fail during fat-tailed liquidity crises.
- **Technical Implementation**:
  - Implemented in `nightwatch/stress/scenarios.py` and `crash_replays.json`.
  - Generates 15+ token-native presets fitted from the token's own empirical historical distribution:
    - *Weekend Gap*: Empirical 99th percentile gap over closed-market sessions.
    - *Earnings Gap*: Empirical post-announcement price jump.
    - *Volatility Shock*: 3× realized vol expansion.
    - *Basis Blowout*: Severe divergence between synthetic token and cash underlying.
    - *Order Book Drought*: 80% reduction in available level-2 depth.
    - *Exchange Halt*: Inability to exit for 4–12 hours.
  - **Crash Replays**: Applies exact historical price paths from five major systemic crises:
    1. *COVID-19 Crash* (March 2020)
    2. *2022 Inflation Shock* (June 2022)
    3. *US Regional Banking Crisis* (March 2023)
    4. *Yen Carry Trade Unwind* (August 2024)
    5. *Tariff & Trade Shock* (April 2025)
  - Asymmetric evaluation: Shocks are applied strictly to the vulnerable tail (downside for longs, upside squeezes for shorts).
- **Status**: **Fully Implemented**.

### Feature 4: Live Order-Book Exit & Entry Cost Curve
- **Purpose**: Calculates the true monetary cost of entering and exiting a position based on live order books.
- **Problem Solved**: Traders frequently size trades assuming mid-market prices, only to suffer massive slippage when executing large notionals on thin order books.
- **Technical Implementation**:
  - Implemented in `nightwatch/execution/exit_cost.py` and `nightwatch/data/book_metrics.py`.
  - Walks Bitget's live Level-2 order book snapshots (up to 100 bids and asks) up to $500,000 notional.
  - Calculates cumulative filled volume, weighted average execution price, absolute slippage in basis points (bps), and total cost in quote currency (USDT).
  - Evaluates whether the position can be fully liquidated (`fully_filled: bool`).
  - Generates an optimal **Entry Slicing Plan**: Recommends chunked limit orders to prevent immediate market dislocation.
- **Status**: **Fully Implemented**.

### Feature 5: Leverage Safety Ladder & Perpetual Margin Tiers
- **Purpose**: Evaluates liquidation risks across leverage levels from 2× to 20×.
- **Problem Solved**: Perpetual traders frequently underestimate the non-linear increase in liquidation probability when moving from 2× to 5× or 10× leverage.
- **Technical Implementation**:
  - Implemented in `nightwatch/execution/leverage.py` and rendered via `web/src/components/report/leverage-safety.tsx`.
  - Directly queries Bitget's live USDT-margined perpetual margin tier contracts (`Venue.BITGET_UMCBL`) to extract exact maintenance margin rates ($MMR$) and initial margin requirements ($IMR$).
  - Derives exact liquidation price:
    $$\text{Liq Price}_{\text{long}} = \text{Entry Price} \times \left(1 - \frac{1}{\text{Leverage}} + MMR\right)$$
  - Evaluates how many historical analog paths ($k=80$) and stress scenarios crossed this liquidation barrier.
  - Flags when liquidation risk transitions from safe to hazardous.
- **Status**: **Fully Implemented**.

### Feature 6: Rule Gate Decision & Sizing Engine
- **Purpose**: Issues the final bounded verdict (**`GO`**, **`REDUCE_TO`**, **`HEDGE`**, **`REVIEW`**, **`NO_GO`**) and calculates recommended sizing.
- **Problem Solved**: Transforms complex risk distributions into an unambiguous, actionable decision.
- **Technical Implementation**:
  - Implemented in `nightwatch/decision/gate.py`, `sizing.py`, and `ticket.py`.
  - Evaluates a 6-factor constraint rule gate:
    1. *Concentration Rule*: Position cannot exceed a specified percentage of total portfolio equity (default 20%).
    2. *Risk Budget Rule*: 1-in-20 potential loss (`p5`) must not exceed the user's allocated risk tolerance.
    3. *Liquidity Rule*: Position size cannot exceed 10% of visible order-book depth within 200 bps of mid-price.
    4. *Liquidation Rule*: Liquidation distance must exceed 2× the 95th-percentile adverse price excursion.
    5. *Written Plan Rule*: If a trade carries high volatility or event risk, the trader must supply a written rationale ("because...") and invalidation level ("wrong if...").
    6. *Circuit Breaker Rule*: Refuses new trades if the user's recent personal taken trades exceed cumulative daily/weekly loss thresholds.
- **Status**: **Fully Implemented**.

### Feature 7: Thesis vs. News & Filing Verification
- **Purpose**: Cross-references the trader's stated reasoning against real financial news and SEC filings.
- **Problem Solved**: Traders frequently base trades on stale news, incorrect assumptions, or rumors already refuted in corporate disclosures.
- **Technical Implementation**:
  - Implemented in `nightwatch/decision/thesis_check.py` and `nightwatch/api/thesis_capture.py`.
  - Decomposes the user's written thesis into testable factual claims.
  - Searches SQLite-stored news headlines (Google News, Yahoo Finance RSS) and SEC EDGAR filings (8-K, 10-Q, 10-K) ingested within the prior 14 days.
  - Classifies each claim into three verified states:
    - `in_the_news`: Stored headlines confirm the assertion (includes hyperlinked source).
    - `news_says_otherwise`: Stored headlines contradict the assertion.
    - `not_in_our_feeds`: No corroborating news found within indexed data.
  - Guardrail: The model only selects IDs from the pre-filtered database; it is strictly prohibited from generating fake quotes or headlines.
- **Status**: **Fully Implemented**.

### Feature 8: "Tonight" Portfolio Scanner (`/tonight`)
- **Purpose**: Scans an existing book of overnight positions to identify which asset poses the greatest risk before regular market open.
- **Problem Solved**: Multi-asset holders need an immediate executive summary of off-hours vulnerabilities across their entire portfolio.
- **Technical Implementation**:
  - Implemented in `nightwatch/decision/tonight.py`, exposed at `/tonight` in API and frontend.
  - Takes up to 12 concurrent open positions, merges duplicate tickers, and executes a full pipeline pass for each asset across the closed-market window.
  - Ranks holdings by absolute monetary risk ($USDT at risk in a 1-in-20 drop), identifies thin order-book shares, and highlights upcoming corporate earnings or dividend dates.
- **Status**: **Fully Implemented**.

### Feature 9: Cryptographic Receipts & Bitcoin Blockchain Anchoring
- **Purpose**: Creates an immutable, tamper-evident audit trail for every live forecast.
- **Problem Solved**: Financial forecasting services routinely delete bad calls or alter historical predictions retroactively.
- **Technical Implementation**:
  - Implemented in `nightwatch/journal/receipts.py` and `anchor.py`.
  - Every live report is assigned a sequential ID ($seq$).
  - Computes a canonical SHA-256 digest of the trade parameters, timestamp, predicted $p5$ return, and sizing verdict, cryptographically chained to the previous digest:
    $$\text{Digest}_n = \text{SHA-256}(\text{Digest}_{n-1} \,\|\, \text{Payload}_n)$$
  - Endpoints `/api/verify` and `/api/verify/{id}` recompute the entire hash chain from genesis in real time to verify that zero historical entries have been edited.
  - **OpenTimestamps Integration**: Daily hash digests are compiled and submitted to the Bitcoin blockchain via OpenTimestamps (`.ots` files), downloadable via `/anchors/{name}` and verifiable on opentimestamps.org.
- **Status**: **Fully Implemented**.

### Feature 10: Public Calibration & "What We Got Wrong" Journal (`/calibration`, `/wrong`)
- **Purpose**: Evaluates forecast accuracy against realized market outcomes once the holding horizon elapses.
- **Problem Solved**: Provides full transparency on model reliability and surfaces failures.
- **Technical Implementation**:
  - Implemented in `nightwatch/journal/calibration.py`, `adjust.py`, `replay.py`, and rendered at `/calibration` and `/wrong`.
  - Background process (`mature_and_learn`) scans matured forecasts, looks up actual Bitget closing prices, and grades whether the realized return breached the predicted $p5$ loss line.
  - Evaluates empirical breach rates against the nominal 5.0% target.
  - Implements **Whole-Night Resampling**: Because forecasts generated on the same evening share the same underlying market shock, standard i.i.d. variance underestimates uncertainty. Nightwatch resamples across whole trading dates to construct honest confidence intervals (e.g., 2.2% to 4.8%).
  - **The Misses Page (`/wrong`)**: Publicly catalogs every single forecast where realized loss exceeded the stated 1-in-20 bound, showing the exact date, ticker, predicted loss, actual loss, and cryptographic receipt.
- **Status**: **Fully Implemented**.

### Feature 11: Price Tripwires, Pre-Commit Plans & Re-Checks
- **Purpose**: Extends pre-trade analysis into active off-hours position monitoring and disciplined execution.
- **Problem Solved**: Traders make rational risk plans before entering a trade, but panic or freeze during adverse price action at 3:00 AM.
- **Technical Implementation**:
  - Implemented in `nightwatch/journal/tripwires.py`, `plans.py`, and `watches.py`.
  - **Tripwires**: Users can arm one-click price tripwires tied to their stop-loss, invalidation price, liquidation barrier, or 1-in-20 loss price. The background recorder checks Bitget 1-minute high/low bars every 60 seconds. Upon breach, the tripwire fires once, records the exact trigger price and timestamp, re-runs the risk desk, and dispatches an HTTPS webhook payload.
  - **Pre-Commit Plans**: Allows users to pre-commit to actions (**Hold**, **Cut Half**, **Exit**, **Hedge**) across 4 concrete adverse price points. Alerts remind the trader of their pre-committed decision.
  - **Re-Checks (`/watch/{id}`)**: Re-runs the full analysis at the next regular US market close and reports any structural regime shifts.
- **Status**: **Fully Implemented**.

### Feature 12: Read-Only Model Context Protocol (MCP) Server
- **Purpose**: Enables external AI assistants (Claude Desktop, Cursor, AI agents) to query Nightwatch risk analytics.
- **Problem Solved**: AI agents drafting orders lack built-in financial risk evaluation tools.
- **Technical Implementation**:
  - Implemented in `nightwatch/api/mcp_server.py`, served at `/api/mcp` and `/mcp`.
  - Exposes three JSON-RPC 2.0 tools:
    1. `stress_test`: Executes full pipeline analysis for a given ticker, side, size, equity, and horizon.
    2. `list_conditions`: Enumerates available analog filters ("lenses") with historical sample sizes.
    3. `list_tokens`: Lists all covered tokenized equities with active trading data.
  - Compatible with standard MCP clients:
    ```bash
    claude mcp add nightwatch --transport http https://nightwatch-gules.vercel.app/api/mcp
    ```
- **Status**: **Fully Implemented**.

---

## 5. Complete User Flows

### Flow 1: First-Time User Onboarding & Quick Exploration
```
[User Lands on Desk]
         │
         ▼
[Views Hero & 4-Step Pipeline Strip]
         │
         ├──> [Clicks Example Chip: "NVDA weekend 15k", "5x TSLA overnight", etc.]
         │          │
         │          ▼
         │    [Auto-Populates Chat / Form]
         │          │
         ▼          ▼
[Executes Stress Test Pipeline in 1-4 seconds]
         │
         ▼
[Receives Prominent Sized Verdict (GO / REDUCE / NO GO)]
         │
         ▼
[Explores Provenance Dots & Tooltips on Every Number]
```
1. **Landing**: The user opens `https://nightwatch-gules.vercel.app`. The desk presents a clean header with system status indicators, market clock, and an interactive trade input panel.
2. **Preset Discovery**: First-time users see curated demo chips reflecting realistic scenarios ("NVDA weekend 15k", "5x TSLA overnight", "周末做多特斯拉 2万U").
3. **Execution**: Clicking a chip sends the payload to the streaming endpoint (`/api/chat/stream`).
4. **Visual Feedback**: A multi-stage progress indicator animates through:
   - *Parsing trade intent...*
   - *Retrieving similar past moments...*
   - *Computing return distribution...*
   - *Running stress tests & crash replays...*
   - *Walking live Bitget order book...*
   - *Applying sizing & rule gate...*
5. **Report Display**: The full `ReportView` renders with a prominent verdict badge, key metric cards, and expandable analytic sections.

### Flow 2: Core Conversational Workflow (Chat Desk)
1. **Natural Input**: The user types *"Long 20k TSLA over the weekend because earnings were strong, wrong if below 210"*.
2. **Clarification Handling**: If the user omits mandatory parameters (e.g., typing *"Should I buy NVDA?"*), the system detects missing fields and replies with a focused prompt: *"Which direction and what size in USDT?"*. If account equity is provided without trade size, it automatically assumes the maximum permissible size under concentration rules.
3. **Verdict Review**: The user reviews the generated report, noting the 1-in-20 downside loss (e.g., -$1,420 USDT) and worst stress preset (e.g., Weekend Gap: -$2,100 USDT).
4. **Conversational Follow-Up**: The user types follow-up questions directly in the chat sidebar:
   - *"What if it gaps down 10%?"* -> Generates a comparative shock analysis with a visual bar chart comparing the shock to the 1-in-20 loss.
   - *"What about 5x leverage?"* -> Re-runs the trade on Bitget's perpetual contract, displays liquidation price, and updates the leverage safety table.
   - *"Compare with SPY"* -> Runs a comparative analysis against the benchmark index.

### Flow 3: Form-Based Parameter Entry & Condition Lenses
1. **Form Selection**: The user switches from the Chat tab to the **Ticket Form** tab.
2. **Manual Configuration**: Directly inputs Ticker (`TSLA`), Direction (`Long`), Size (`20,000`), Horizon (`Through Weekend`), Stop Price (`210`), and Leverage (`1x`).
3. **Condition Filtering ("Lenses")**: The user expands the **Lenses** menu to restrict historical matching to specific market environments:
   - *Only Earnings Nights* (`earnings_night`)
   - *High Volatility Regimes* (`high_volatility`)
   - *Wide Token Basis* (`basis_divergence`)
   - *Thin Order Books* (`illiquid_book`)
4. **Evidence Cost Feedback**: The UI immediately displays the sample size cost of each filter (e.g., *"Leaving 142 distinct episodes across universe"*).
5. **Execution**: Clicking **Analyze Trade** executes the identical deterministic pipeline without LLM overhead.

### Flow 4: Post-Decision Protection (Tripwires & Pre-Commit Plans)
1. **Arming a Tripwire**: On an active report, the user navigates to the **Alerts & Plan** section.
2. **Threshold Selection**: Selects a suggested price line (Stop Loss: $210.00, 1-in-20 Price: $198.50, or Liquidation: $175.00).
3. **Webhook Entry**: Optionally inputs an HTTPS webhook URL (or Telegram chat ID).
4. **Activation**: Clicks **Arm Tripwire**. The backend registers the trigger in the SQLite `tripwires` table.
5. **Pre-Commit Action Plan**: In the **Pre-Commit Plan** card, the user selects advance actions for four adverse scenarios:
   - At Stop Price ($210): *Cut Half*
   - At 1-in-20 Loss ($198.50): *Exit Entire Position*
   - At Liquidation Warning ($175): *Hedge 100% on Perp*
6. **Execution Monitoring**: The background recorder monitors Bitget 1-minute ticks. If a level is breached, a webhook payload is dispatched with the user's pre-committed instructions.

### Flow 5: Public Audit & Verification Workflow
1. **Permalink Sharing**: The user copies the permanent link (`/r/{forecast_id}`) to share the exact report with a colleague or judge.
2. **Chain Verification**: The auditor visits `/api/verify` to verify the mathematical integrity of the SHA-256 receipt chain from genesis to the current block.
3. **Bitcoin Proof Check**: The auditor visits `/anchors`, downloads the latest `.ots` file, and validates it against the Bitcoin blockchain on `opentimestamps.org`.
4. **Calibration Review**: The auditor visits `/calibration` and `/wrong` to evaluate historical breach rates and inspect all historical misses.

---

## 6. Technical Architecture

### 6.1 Application Architecture Overview
Nightwatch is structured as a decoupled, multi-tier distributed system consisting of:
1. **Data Ingestion & Sync Layer**: Asynchronous polling clients for 21 external market feeds writing to an append-optimized SQLite database with Write-Ahead Logging (WAL).
2. **Continuous Background Recorder**: Independent daemon process recording Bitget Level-2 order books and 1-minute k-lines every 60 seconds, evaluating tripwires, and maturing forecasts.
3. **Core Quantitative Pipeline**: Pure Python deterministic analytical engine implementing analog retrieval, stress scenarios, order-book execution, and rule gate sizing.
4. **FastAPI Application Server**: High-throughput REST and Server-Sent Events (SSE) API handling rate limiting, in-memory caching, provider dispatch, and MCP endpoints.
5. **Next.js Frontend Terminal**: React 19 / Next.js 16 App Router application providing streaming UX, internationalization, and client-side fallback snapshot caching.

```
                           +───────────────────────────────────────────────────+
                           │                 CLIENT INTERFACES                 │
                           │  - Web Terminal (Next.js 16 / React 19)           │
                           │  - Model Context Protocol (MCP) Clients           │
                           │  - Telegram Bot Interface                         │
                           +───────────────────────────────────────────────────+
                                                     │
                                                     ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────────+
│                                        FASTAPI APPLICATION LAYER                                      │
│  - Edge Protection & Rate Limiting (`guard.py`)                                                       │
│  - Natural Language Intake & LLM Dispatch (`llm.py`, `providers.py`, `intake.py`)                     │
│  - Streaming Server-Sent Events (`/chat/stream`)                                                      │
│  - Read-Only MCP Server (`mcp_server.py`)                                                             │
+───────────────────────────────────────────────────────────────────────────────────────────────────────+
           │                                         │                                      │
           ▼                                         ▼                                      ▼
+──────────────────────+                  +──────────────────────+               +──────────────────────+
│   ANALOG RETRIEVAL   │                  │    STRESS TESTING    │               │  EXECUTION & SIZING  │
│  - k-NN Engine       │                  │  - 15+ Fitted Presets│               │  - Order-Book Walk   │
│  - Mahalanobis Dist  │                  │  - Crash Replays     │               │  - Margin Tiers (MMR)│
│  - Episode Dedup     │                  │  - Monte Carlo       │               │  - Sizing Rule Gate  │
+──────────────────────+                  +──────────────────────+               +──────────────────────+
           │                                         │                                      │
           └─────────────────────────────────────────┼──────────────────────────────────────┘
                                                     ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────────+
│                                     PIPELINE ORCHESTRATOR (`analyze.py`)                              │
│  Transforms `TradeTicket` + Market Snapshot ──> Fully Computed `AnalysisReport`                      │
+───────────────────────────────────────────────────────────────────────────────────────────────────────+
                                                     │
                                                     ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────────+
│                                          DATA & STORAGE LAYER                                         │
│  - SQLite Engine (WAL Mode, Point-in-Time `as_of` Queries)                                            │
│  - Ingest Clients: Bitget Spot/Perp, Bitget MCP, Bitget Signal, Yahoo, Nasdaq, FRED, SEC, Cboe        │
│  - Tamper-Evident SHA-256 Receipt Chain & OpenTimestamps Bitcoin Anchors                             │
+───────────────────────────────────────────────────────────────────────────────────────────────────────+
```

### 6.2 Frontend Architecture (Next.js 16 / React 19)
- **Directory**: `web/`
- **Routing**: Modern App Router (`web/src/app/`)
  - `/` -> Main Pre-Trade Terminal (`desk-page.tsx`)
  - `/calibration` -> Public Statistical Calibration Dashboard
  - `/wrong` -> Historical Misses Catalog
  - `/studies` -> 11 Empirical Methodology Studies with FDR correction
  - `/sources` -> Data Feeds Status and Freshness Monitor
  - `/tonight` -> Overnight Multi-Position Risk Scanner
  - `/status` -> System Health, DB Latency, and Memory Diagnostics
  - `/usage` -> Anonymous Telemetry and Client Engagement
  - `/r/[id]` -> Permanent Shareable Report Permalink
  - `/watch/[id]` -> Re-Check Status and History
  - `/api/[...path]` -> Next.js Edge Proxy to FastAPI Backend
- **Component Hierarchy**:
  - `DeskPage`: Root coordinator managing ticket state, active report, and tab switching.
  - `Chat`: Streaming chat sidebar with message memory, starter chips, and instant follow-ups.
  - `TicketForm`: Manual parameter entry with live condition lens counts.
  - `ReportView`: Massive 2,000+ line reactive report container rendering:
    - `ThreeSteps`: Overview of retrieval, distribution, and stress testing.
    - `DecisionCard`: Prominent verdict badge, sizing recommendation, and binding constraints.
    - `LeverageSafety`: Interactive 2×–20× liquidation risk table.
    - `ThesisCheck`: News/SEC filing claim corroboration card.
    - `BookContrast`: Side-by-side single ticket vs. concentrated portfolio analysis.
    - `MarketClock`: Live countdown to US market open/close and off-hours duration.
    - `Tripwire`: Interactive price alert configuration interface.
    - `PlanCard`: Pre-commit contingency action planner.
    - `SourceEffects`: Explicit listing of which data sources influenced the sizing decision.
- **Client-Side Resilience & Snapshot Fallback**:
  - Implemented in `web/src/lib/snapshot.ts` and `web/src/snapshot/index.ts`.
  - Statically bundles a pre-rendered `generated.json` snapshot of standard reports at build time.
  - If the backend is temporarily unreachable (e.g., during cold container restarts or network drops returning 502/503/504), the frontend intercepts the error and seamlessly renders the valid cached snapshot with a transparent fallback banner.

### 6.3 Backend Architecture (FastAPI & Pipeline)
- **Directory**: `nightwatch/`
- **Concurrency Model**:
  - FastAPI runs on Uvicorn.
  - CPU-bound mathematical operations (Cholesky factorization, Monte Carlo simulations, order-book walking) are offloaded to an asynchronous threadpool via `starlette.concurrency.run_in_threadpool`, ensuring long analyses never block HTTP health checks or concurrent requests.
  - Global `RequestFirstLock` prioritizes interactive human requests over background cache warming routines.
- **Data Persistence**:
  - `nightwatch/data/store.py`: Single-file SQLite database with Write-Ahead Logging (`PRAGMA journal_mode=WAL`).
  - Strict Point-in-Time Correctness: All queries support an optional `as_of` timestamp. Queries filter strictly `WHERE ts <= :as_of`, eliminating lookahead bias during historical replay and calibration.
  - Connection Watchdog: Implements automatic self-healing reconnection if a SQLite read cursor lags behind the active WAL file by more than 180 seconds.

---

## 7. Technology Stack

### 7.1 Language & Runtimes
- **Python**: `3.11+` (Backend API, data ingestion, quantitative engine)
- **Node.js**: `v22+` (Frontend build and runtime)
- **TypeScript**: `5.x` (Frontend application code)

### 7.2 Backend Frameworks & Libraries
- **FastAPI**: `0.115+` (REST API, SSE streaming, OpenAPI documentation)
- **Uvicorn**: `0.30+` (ASGI server with uvloop)
- **Pydantic**: `2.6+` (Data validation, schema enforcement, structured LLM output validation)
- **Pandas**: `2.2+` (Time-series manipulation, feature frames)
- **NumPy**: `1.26+` (Matrix mathematics, Cholesky decomposition, vector distances)
- **HTTPX**: `0.28+` (Asynchronous and synchronous HTTP clients with connection pooling)
- **Feedparser**: `6.0+` (RSS news parsing for Google News and Yahoo Finance)
- **OpenTimestamps**: `0.7+` (Bitcoin blockchain cryptographic timestamping client)
- **Hatchling**: `1.24+` (Python build backend)
- **Ruff**: `0.5+` (Fast linting and code formatting)
- **Pytest**: `8.0+` & **pytest-asyncio** (Comprehensive test suite)

### 7.3 Frontend Frameworks & Libraries
- **Next.js**: `16.3.5` (React Server Components, App Router, standalone Docker build)
- **React**: `19.2.8` (Concurrent rendering, Server Actions)
- **Tailwind CSS**: `v4.x` with `@tailwindcss/postcss`
- **@base-ui/react**: Unstyled, accessible UI component primitives
- **Recharts**: Responsive financial charts and shock comparison graphs
- **Lucide React**: Clean UI iconography
- **Class Variance Authority (CVA)** & **clsx / tailwind-merge**: Component variant styling

### 7.4 Deployment & Infrastructure
- **Frontend Hosting**: Vercel (Edge-cached Next.js deployment)
- **Backend Hosting**: Small AWS Lightsail instance (1 vCPU, 1 GB RAM, Ubuntu Linux)
- **Containerization**: Multi-stage `Dockerfile` and `compose.yaml`
- **CI/CD**: GitHub Actions (`ci.yml`, `uptime.yml`, `browser-smoke.yml`)

---

## 8. AI / Intelligence Layer

### 8.1 The Strict Architectural Division of Labor
Nightwatch enforces an uncompromising architectural principle: **The AI is an analyst, not a calculator.**

```
+─────────────────────────────────────────────────────────────────────────────+
|                         WHAT THE AI IS ALLOWED TO DO                        |
|  1. Parse unstructured user messages into strongly typed `TradeTicket`s.   |
|  2. Identify missing parameters and ask concise clarifying questions.       |
|  3. Read the finalized, fully computed report and synthesize a briefing.    |
|  4. Match user thesis assertions against stored news and SEC filing titles. |
|  5. Answer conversational follow-ups by quoting facts already in the report.|
+─────────────────────────────────────────────────────────────────────────────+
                                       ▲
                                       │ STRICT SEPARATION
                                       ▼
+─────────────────────────────────────────────────────────────────────────────+
|                       WHAT THE AI IS FORBIDDEN FROM DOING                   |
|  1. NEVER calculate or estimate a price or return.                          |
|  2. NEVER compute an empirical percentile (p5, p50, p95).                   |
|  3. NEVER calculate a liquidation price or maintenance margin.              |
|  4. NEVER determine an order-book exit cost or slippage value.              |
|  5. NEVER issue or alter a sizing decision or verdict (GO/NO GO).           |
+─────────────────────────────────────────────────────────────────────────────+
```

### 8.2 Supported LLM Providers & Model Dispatch
Implemented in `nightwatch/api/providers.py` and `nightwatch/api/llm.py`:
1. **Anthropic Claude**: Claude Opus 5 via the official Python SDK, utilizing native structured JSON output schemas (`output_format=schema`) and server-side fallbacks.
2. **Qwen 3.8 Max**: Integrated via Bitget's Hackathon Gateway (`qwen3.8-max`). Utilizes structured system prompts (`_schema_hint`) and strict Pydantic post-validation. Thinking mode is explicitly disabled (`thinking=False`) to reduce latency from ~80s down to ~4s.
3. **Deterministic Rule-Based Fallback**: If no API keys are configured (`ANTHROPIC_API_KEY` and `BITGET_QWEN_API_KEY` unset) or if external AI gateways experience outages, the system automatically falls back to regex-based parsing (`intake.py`) and templated briefing generators (`intake.brief_short`). The system continues functioning seamlessly with zero external AI dependencies.

### 8.3 Anti-Hallucination Guardrail (`unverified_numbers`)
Any text generated by an LLM is routed through the verification engine in `nightwatch/api/llm.py`:
- The engine scans the LLM's generated narrative using regular expressions to extract every numeric token (percentages, prices, notionals, basis points).
- It compares each extracted number against the complete set of numbers present in the deterministic `AnalysisReport`.
- If the LLM generates even a single numeric value that cannot be traced back to the report (allowing only small structural integers 1–6 for numbered list items), **the entire LLM narrative is immediately discarded**.
- The system silently replaces the discarded narrative with the grounded, rule-based deterministic summary, logging the incident.

### 8.4 Autonomous Stress-Test Agent (`nightwatch/api/agent.py`)
In addition to standard narration, Nightwatch features an autonomous analytical agent:
- Operates under a strict budget: maximum 5 sequential tool calls, 40-second execution timeout.
- Bound to five read-only deterministic tools:
  1. `rerun`: Re-evaluates the trade under altered parameters.
  2. `base_rate`: Queries historical shock frequencies.
  3. `safest_ways`: Evaluates multi-scenario hedge combinations.
  4. `explain`: Retrieves underlying factor attribution.
  5. `bitget_data`: Queries Bitget corporate actions and funding rates.
- Mandatory Citation Enforcement: Every factual statement in the agent's final report must include an explicit bracketed citation tag (e.g., `[evidence]`, `[stress]`). Sentences containing uncited assertions are stripped.

---

## 9. Integrations

Nightwatch integrates with 21 distinct live data sources, each monitored with its real update latency and displayed publicly on `/sources`:

| Integration | Feed Type | Data Exchanged | Update Cadence | Fallback Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **Bitget Spot API** | REST / Public | 1m/1h OHLCV bars, Level-2 order books (100 depth) | 30–60 seconds | Stored SQLite history; offline warning banner. |
| **Bitget Perp API** | REST / Public | U-margined perpetual bars, funding rates, open interest | 30–60 seconds | Uses 1x spot token math; flags perp data as unavailable. |
| **Bitget Margin Tiers** | REST / Public | Contract maintenance margin rates ($MMR$) and tiers | Daily cache | Fallback to conservative standard 5% maintenance margin. |
| **Bitget US-Stock MCP** | Model Context Protocol | Live quotes, analyst consensus, insider trades, financials | Hourly cache | Suppressed on `/sources`; report notes feed inactive. |
| **Bitget Signal Skill** | MCP Tool | 4-hour technical RSI indicators | Hourly cache | Cross-checks with internal candle RSI; ignored if divergent. |
| **Bitget Wallet RWA** | REST / Public | Token listing and contract status | 25 min cache | Assumes active trading status if unreachable. |
| **Yahoo Finance** | HTTP Scraper | Underlying US equity 1h candles, dividend schedules | Hourly / Daily | Interpolates from Bitget token prices. |
| **Nasdaq Events** | HTTP Scraper | Corporate earnings dates and consensus forecasts | Daily sync | Assumes no imminent earnings event; logs data gap. |
| **FRED (St. Louis Fed)** | REST API | Macro time series (US 10Y Yield, VIX, DXY, EFFR) | Daily sync | Uses trailing 1-year percentile window from SQLite cache. |
| **SEC EDGAR** | RSS / HTTP | Corporate 8-K, 10-Q, 10-K regulatory filings | 12 hours | Fallback to headline news keyword analysis. |
| **News RSS Feeds** | RSS XML | Google News & Yahoo Finance articles and headlines | 1 hour | Flags thesis check as "not in our feeds". |
| **Cboe Options Data** | Delayed HTTP | Implied volatility surfaces and option chains | Hourly cache | Monte Carlo falls back to realized historical volatility. |
| **OpenTimestamps** | Bitcoin Protocol | SHA-256 calendar digests anchored into Bitcoin blocks | Daily batch | Local hash chain remains unbroken; flags anchor pending. |
| **Telegram Bot** | Bot API (Long Poll) | Plain-text trade intake and push alerts | Event-driven | Built and tested; disabled until `TELEGRAM_BOT_TOKEN` set. |

---

## 10. UI / UX System

### 10.1 Design Philosophy
Nightwatch adheres to an **information-dense, terminal-first design aesthetic**. It avoids generic SaaS landing page patterns, unnecessary marketing hero carousels, and ungrounded chat bubbles. It renders dense financial information using clear typography, structured grids, and instant hover-state data provenance.

### 10.2 Color System & Visual Hierarchy
- **Palette**: Built on Tailwind CSS v4 and shadcn-style neutral design tokens (`brand.md`). Dark theme optimized for long trading sessions.
- **Verdict Color Coding**:
  - **`GO`**: Muted Emerald / Bright Green (`text-emerald-400`, `bg-emerald-950/40`) — Trade approved within all risk boundaries.
  - **`REDUCE_TO`**: Amber / Warm Yellow (`text-amber-400`, `bg-amber-950/40`) — Trade permitted only after downsizing notional.
  - **`HEDGE`**: Cyan / Blue (`text-cyan-400`, `bg-cyan-950/40`) — Trade permitted only with offsetting perpetual contract.
  - **`REVIEW`**: Purple / Indigo (`text-indigo-400`, `bg-indigo-950/40`) — Action required (missing stop, unconfirmed equity, thesis conflict).
  - **`NO_GO`**: Crimson / Bright Red (`text-rose-400`, `bg-rose-950/40`) — Trade rejected; excessive tail risk or liquidation hazard.

### 10.3 Bilingual Internationalization (EN / ZH)
- First-class native bilingual support for English and Simplified Chinese across all components and API responses.
- Implemented natively via `LangContext` (`web/src/lib/lang.tsx`) without external dependencies:
  - `tx("English Text", "中文文本")` helper function for inline rendering.
  - Complete Chinese translation dictionary for data sources (`source-zh.ts`) and methodology studies (`studies-zh.ts`).
  - Automatic language detection from input phrasing (`intake.language_of`) ensures Chinese queries receive fluent Chinese analytical summaries.

### 10.4 Provenance & Data Tagging System (`SourceChip`)
Every numerical figure displayed on the interface features an interactive provenance dot:
- **`Live`** (Green dot): Live data pulled directly from exchange or market feeds within the last 5 minutes.
- **`History`** (Blue dot): Derived from the token's historical database or analog cohort.
- **`Assumed`** (Yellow dot): Defaulted parameter (e.g., standard account equity if unspecified).
- **`AI`** (Purple dot): Synthesized text or extraction by the language model.
Hovering or clicking any dot reveals a detailed tooltip displaying the exact source feed, sample size, and millisecond timestamp.

---

## 11. Data & State

### 11.1 Core Data Entities (Backend SQLite Schema)
Implemented in `nightwatch/data/store.py`:
- **`bars`**: OHLCV candle records (`venue`, `symbol`, `interval`, `open_time_ms`, `open`, `high`, `low`, `close`, `volume`). Indexed on `(symbol, interval, open_time_ms)`.
- **`orderbook_snapshots`**: Level-2 book depth (`venue`, `symbol`, `ts_ms`, `bids_json`, `asks_json`, `spread_bps`, `mid_price`).
- **`instruments`**: Token metadata mapping Bitget spot symbols (`rTSLAUSDT`) to perpetual symbols (`TSLAUSDT`) and Yahoo tickers (`TSLA`).
- **`forecasts`**: Immutable record of every generated verdict (`id`, `as_of`, `ticker`, `side`, `notional`, `horizon_h`, `verdict`, `recommended_notional`, `stated_p5_pct`, `exit_ts`, `outcome_pct`).
- **`receipts`**: SHA-256 hash chain (`seq`, `forecast_id`, `digest`, `prev_digest`, `created_at`).
- **`tripwires`**: Active and triggered price alerts (`id`, `forecast_id`, `level`, `label`, `webhook`, `triggered_at`, `trigger_price`).
- **`plans`**: Pre-commit action choices across 4 failure scenarios.
- **`news` & `filings`**: Scraped headlines and SEC filings with publication timestamps.
- **`macro` & `earnings`**: Trailing economic indicators and upcoming corporate calendars.

### 11.2 State Management & Data Flow
```
User Action (Chat/Form)
       │
       ▼
Next.js React State (`desk-page.tsx`)
       │
       ▼ (HTTP POST /chat/stream or /analyze)
FastAPI Pipeline Context (`AnalysisContext`)
       │
       ├──> SQLite Point-in-Time Read (`Store`)
       ├──> Feature Frame Construction (`FeatureSnapshot`)
       ├──> Analog Engine k-NN Search (`AnalogEngine`)
       ├──> Scenario Stress Evaluation (`apply_scenario`)
       ├──> Live Order Book Walk (`BitgetPublicClient`)
       └──> Decision Gate Sizing (`evaluate_gate`)
       │
       ▼
Deterministic Report (`AnalysisReport`)
       │
       ├──> Hashed into Receipt Chain (`receipts.py`)
       ├──> Cached in Memory (`ReportStore`)
       └──> Streamed to Frontend via SSE
       │
       ▼
Frontend `ReportView` State + `sessionStorage` Persistence
```

- **Client Persistence**: Chat history and active report IDs are preserved across page reloads using `sessionStorage` keys (`nw-desk-chat-v1`, `nw-desk-report-v1`).
- **Public Dashboard Caching**: Public statistics pages (`/calibration`, `/wrong`, `/sources`) utilize client-side `localStorage` caching (`nw.record.[path]`) via `record-cache.ts` to provide instant rendering while background updates revalidate.

---

## 12. Security & Reliability

### 12.1 Edge Protection & Proxy Authentication
- Implemented in `nightwatch/api/guard.py`.
- While the backend port is exposed on Lightsail, direct unauthorized requests are blocked using a shared proxy secret (`x-nightwatch-proxy-secret`).
- Vercel edge functions inject the cryptographic secret. Direct hits from external actors lacking the secret are rejected with `403 Forbidden`, protecting the server's AI budget.
- Localhost calls (`127.0.0.1`, `::1`) bypass the secret check to permit internal health monitoring and cron execution.

### 12.2 Per-Client Token Bucket Rate Limiting
- In-memory `RateLimiter` implements token-bucket algorithms keyed by client IP (`x-nightwatch-client-ip` forwarded from Vercel) or browser identifier:
  - `POST /chat`: 20 requests/minute, burst of 12.
  - `POST /analyze`: 20 requests/minute, burst of 12.
  - `POST /agent/`: 3 requests/minute, burst of 3 (heavy LLM protection).
  - `POST /analyst/`: 10 requests/minute, burst of 5.
  - `POST /tonight`: 4 requests/minute, burst of 2.
  - `POST /mcp`: 20 requests/minute, burst of 10.
- Exceeded limits return clean `429 Too Many Requests` responses with standard `Retry-After` headers.

### 12.3 Error Sanitization & Information Leakage Prevention
- `nightwatch/api/guard.py` implements `plain_message`:
  - Catches raw Python exceptions (`KeyError`, `IndexError`, `sqlite3.OperationalError`, internal file paths, stack traces).
  - Sanitizes them into safe, human-readable user messages (e.g., *"The desk could not run that. Check the token and the numbers, or try again in a moment."*).
  - Prevents internal system details or database structures from leaking to external callers.

### 12.4 Concurrency & Memory Safeguards on Small Hardware
- Designed specifically to operate within a constrained **1 GB RAM** Lightsail instance:
  - `_BoundedCache`: In-memory caches enforce strict LRU caps to prevent unbounded growth.
  - `llm_slot`: Concurrency semaphore limits simultaneous LLM requests to 2, preventing gateway timeouts and memory pressure.
  - Frame Toucher: Periodically touches feature frames in memory to prevent aggressive operating system swap behavior.

---

## 13. Testing & Validation

### 13.1 Evidence-Based Test Suite Summary
Nightwatch maintains an extensive automated test suite consisting of **104 test suites** in the `tests/` directory:

| Test Category | File Examples | What is Verified |
| :--- | :--- | :--- |
| **Pipeline & Sizing** | `test_pipeline.py`, `test_decision.py`, `test_sizing.py`, `test_breaker.py` | Complete end-to-end execution; verification of sizing caps, Kelly formulas, and circuit breakers. |
| **Analog Engine** | `test_analog_engine.py`, `test_analog_outcomes.py`, `test_lens.py` | k-NN Mahalanobis retrieval, Cholesky whitening, episode deduplication, and lens filtering. |
| **Stress Testing** | `test_stress.py`, `test_scenarios.py` | Preset shock applications, asymmetric tail selection, crash replay math, and Monte Carlo paths. |
| **Execution & Order Books** | `test_execution.py`, `test_leverage.py`, `test_book_sizing.py` | Level-2 book walking, cost curve derivation, slippage calculation, and margin tier liquidations. |
| **AI Layer & Guards** | `test_llm.py`, `test_agent.py`, `test_analyst.py`, `test_intake.py` | Verification that LLMs never calculate numbers; verification of `unverified_numbers` stripping; tool loop bounds. |
| **Receipts & Cryptography** | `test_receipts.py`, `test_anchor.py` | SHA-256 hash chaining, genesis linking, break detection, and OpenTimestamps serialization. |
| **Statistical Integrity** | `test_fdr.py`, `test_calibration.py`, `test_adjust.py`, `test_walkforward.py` | Benjamini-Hochberg FDR correction, out-of-sample expanding adjustments, and whole-night resampling. |
| **Security & Hardening** | `test_hardening.py`, `test_api_hostile_inputs.py`, `test_locking.py` | Rate limiter enforcement, proxy secret checks, and rejection of hostile inputs (`NaN`, `Infinity`, negative notionals). |
| **Frontend Unit Tests** | `web/src/lib/*.test.mjs` | Node.js native tests for client-side ticket validation (`errors`), date formatting (`hours`), and regex cleaners (`plain`). |
| **Browser End-to-End** | `web/e2e/smoke.mjs` | Headless Chromium Playwright smoke test navigating live desk, clicking chips, and verifying report renders. |

### 13.2 CI/CD Verification Workflows
- **`ci.yml`**: Runs on every push and pull request to `main`. Executes `ruff check`, `python -m pytest -q -p no:warnings`, and `npm run build`.
- **`uptime.yml`**: Scheduled GitHub Action running every 15 minutes. Curls production API endpoints and verifies database write freshness.
- **`browser-smoke.yml`**: Scheduled GitHub Action running every 30 minutes. Spins up Chromium via Playwright, opens `https://nightwatch-gules.vercel.app`, interacts with every demo chip, types a trade, and verifies report generation without console errors.

### 13.3 Untested Areas & Explicit Limitations
- **Live Automated Order Execution**: Untested and unbuilt by architectural design. Nightwatch never sends order broadcasts to Bitget or any other trading venue.
- **Production High-Concurrency Stress**: Not benchmarked for thousands of concurrent requests (the single 1 GB Lightsail instance is sized for hackathon judging and evaluation, not high-frequency retail load).

---

## 14. Product Strengths / Special Features

1. **The Full Chain from a Single Sentence**: Unlike competing tools that offer fragmented features (a chatbot, a separate charting tool, a separate risk calculator), Nightwatch connects natural language intake directly to k-NN retrieval, fat-tailed stress tests, live order-book walking, and sized verdicts in a unified, sub-5-second workflow.
2. **Absolute Defense Against AI Hallucination**: By strictly decoupling computation from narration and enforcing the automated `unverified_numbers` sanitizer, Nightwatch solves the fatal flaw of "AI in finance."
3. **Cryptographically Proven Integrity**: While financial services routinely alter past forecasts, Nightwatch's SHA-256 hash-chained receipts and daily Bitcoin block timestamping provide irrefutable proof that predictions were registered before market outcomes occurred.
4. **Radical Public Transparency (`/wrong`, `/studies`)**: The platform openly catalogs its historical prediction misses and publishes 11 rigorous internal methodology studies—including the explicit admission that the model has **no directional predictive edge** and that historical neighbor weighting was discarded after failing out-of-sample tests.
5. **Authentic Bitget Ecosystem Depth**: Integrates with live Bitget Spot order books, Perpetual futures, perpetual margin tiers, open interest, the Bitget US-stock MCP service, the Bitget Signal skill, and Bitget Wallet RWA listing data.

---

## 15. Limitations / Known Issues

### 15.1 Known Limitations
- **Zero Directional Edge**: Nightwatch is strictly a risk measurement and position-sizing engine. It does not predict whether an equity will move up or down, and openly states so.
- **Hardware Scale Constraints**: Running on a 1 GB RAM Lightsail instance means that during heavy background cache warming or multiple simultaneous LLM calls, latency can increase to 4–8 seconds.
- **Universe Size**: Currently covers 24 core tokenized US equities and ETFs with complete historical syncs (though the universe architecture is configured to support 112).

### 15.2 Partially Implemented / Dormant Features
- **Telegram Bot**: Fully written, tested, and containerized in `nightwatch/api/telegram_bot.py`, but currently dormant in production because `TELEGRAM_BOT_TOKEN` is unset.
- **Direct User Account Sync**: The desk requires traders to type their equity and holdings manually; OAuth integration to read live Bitget balances directly is not implemented.
- **Email Notifications**: Tripwires and re-checks dispatch webhooks and log alerts, but email delivery is not implemented.

### 15.3 Technical Debt
- **Replay Backfill Memory Spike**: Re-running full historical replays across all tokens simultaneously on the production server can exhaust the 1 GB machine's memory, requiring replays to be executed off-line or in small batches.

---

## 16. Current Status

| Component | Status | Verification Evidence |
| :--- | :--- | :--- |
| **Deterministic Pipeline** | **Fully Implemented & Frozen** | Frozen at `method-freeze-3`, verified across 104 test suites. |
| **FastAPI Backend** | **Fully Implemented & Deployed** | Live on Lightsail, monitored every 15 min via `uptime.yml`. |
| **Next.js Web Desk** | **Fully Implemented & Deployed** | Live on Vercel at `nightwatch-gules.vercel.app`, smoke-tested every 30 min. |
| **Bilingual UI (EN/ZH)** | **Fully Implemented** | Complete dual-language dictionaries and automatic intent translation. |
| **Bitget Data Integrations** | **Fully Implemented** | Live Level-2 books, margin tiers, MCP server, and signal skill active. |
| **Receipts & Bitcoin Anchoring** | **Fully Implemented** | 7 of 7 daily anchors confirmed in Bitcoin via OpenTimestamps. |
| **Public Track Record** | **Fully Implemented** | `/calibration`, `/wrong`, `/studies`, `/sources` live and recalculating. |
| **MCP Risk Server** | **Fully Implemented** | Streamable JSON-RPC HTTP endpoint active at `/api/mcp`. |
| **Agent Hub Skill File** | **Fully Implemented** | Packaged in repo at `skills/nightwatch-stress-test/SKILL.md`. |
| **Telegram Bot** | **Implemented but Inactive** | Code complete; awaiting production bot token. |
| **Automated Order Execution** | **Intentionally Excluded** | Excluded by product design; human retains execution authority. |

---

## 17. Future Roadmap

### 17.1 Verified Roadmap Items (Documented in Code & Docs)
- **Universe Expansion**: Complete the throttled backfill to expand from 24 core tokens to the full 112 shortlisted tokenized US equities cataloged in `UNIVERSE_CANDIDATES.md` and `docs/universe-expansion.md`.
- **Telegram Alert Activation**: Configure production bot tokens to enable push alert delivery for price tripwires and next-close re-checks.
- **Production Server Upgrade**: Migrate the backend from the 1 GB Lightsail container to a 4 GB / 2 vCPU instance to eliminate cache warming bottlenecks and allow continuous out-of-sample replay refits.

### 17.2 Potential Enhancements (Architectural Recommendations)
- **Bitget OAuth Portfolio Connect**: Enable users to connect their Bitget API keys (read-only) to automatically import open rToken and perpetual positions into the `/tonight` risk scanner.
- **WebSocket Depth Streaming**: Upgrade from 30–60 second REST order-book polling to persistent Bitget WebSocket feeds for sub-second book walk precision.
- **Cross-Exchange RWA Aggregation**: Expand ingestion to cover tokenized equities across additional emerging crypto venues (e.g., Kraken, Bybit, decentralized RWA protocols).

---

## 18. Quick Reference

- **Product Summary**: Nightwatch is a pre-trade decision stress tester for tokenized US stocks (rTokens) on Bitget, designed specifically for off-hours trading windows when traditional equity markets are shut.
- **Core Workflow**: Natural Language Trade Intake $\rightarrow$ Historical Analog Retrieval $\rightarrow$ Empirical Distribution $\rightarrow$ 15+ Stress Presets & Crash Replays $\rightarrow$ Live Bitget Order-Book Walk $\rightarrow$ Sized Rule Gate Verdict (**`GO`**, **`REDUCE_TO`**, **`HEDGE`**, **`REVIEW`**, **`NO_GO`**).
- **Core Technologies**: Python 3.11, FastAPI, Pandas, NumPy, SQLite (WAL mode), Next.js 16.3.5, React 19.2.8, Tailwind CSS v4, Base UI, OpenTimestamps (Bitcoin).
- **AI Implementations**: Anthropic Claude Opus 5 & Qwen 3.8 Max (Bitget Gateway) used strictly for parsing, narration, and thesis verification; strict `unverified_numbers` guardrails discard any hallucinated metrics; 100% deterministic mathematical computation.
- **Key Integrations**: Bitget Spot & Perp REST APIs, Bitget Margin Tiers, Bitget US-Stock MCP, Bitget Signal Skill, Bitget Wallet RWA, Yahoo Finance, Nasdaq Events, FRED Macro, SEC EDGAR, RSS feeds, Cboe Options, OpenTimestamps / Bitcoin.
- **Auditability & Integrity**: Cryptographic SHA-256 receipt chain, daily Bitcoin block anchors, public track record (`/calibration`), transparent catalog of historical prediction misses (`/wrong`), and 11 empirical methodology studies (`/studies`).
- **Testing Scale**: 104 test suites, 1,500+ automated tests passing in CI, continuous 15-minute API health checks, and 30-minute Playwright browser smoke tests on production.
- **Live Product URL**: [https://nightwatch-gules.vercel.app](https://nightwatch-gules.vercel.app)
- **Exact File Path**: `C:\Users\ritik\bgs2\Overview 2.md`
