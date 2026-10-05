/**
 * Typed client for the Nightwatch API.
 *
 * The backend is the source of every number; this module only moves JSON. Types cover
 * the fields the UI renders and are intentionally loose where the report carries
 * large or optional structures.
 */
import type { Provenance } from "./provenance";

import { withIdentity } from "@/lib/identity";

/**
 * Where the backend lives.
 *
 * Set NEXT_PUBLIC_API_URL to call it directly (local development, or an API that has its
 * own certificate). When it is unset and the page is not being served from localhost we
 * fall back to the same-origin proxy at /api, which is how a Vercel deployment reaches a
 * backend that speaks plain http. That fallback means a deploy where the variable was
 * forgotten still works instead of calling the visitor's own machine.
 */
function resolveApiUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL;
  if (configured) return configured.replace(/\/$/, "");
  if (typeof window !== "undefined" && !/^(localhost|127\.|\[::1\])/.test(window.location.hostname)) return "/api";
  return "http://localhost:8000";
}

export const API_URL = resolveApiUrl();

import { SNAPSHOT_HEADER, snapshotFlag } from "./snapshot";

export type Side = "long" | "short";
export type HorizonKind = "next_open" | "window_end" | "hours";

export interface TicketInput {
  ticker: string;
  side: Side;
  notional_quote: number;
  account_equity_quote?: number | null;
  horizon_kind: HorizonKind;
  horizon_hours?: number | null;
  entry_price?: number | null;
  stop_price?: number | null;
  target_price?: number | null;
  thesis: string;
  invalidation: string;
  hedge_ratio?: number | null;
  /** Leverage on the stock's Bitget perpetual; 1 or null is a plain token position. */
  leverage?: number | null;
  as_of?: string | null;
  record?: boolean;
  open_positions?: { ticker: string; side: Side; notional_quote: number }[];
  lenses?: string[];
  /** The server's notes on how the sentence was read, e.g. horizon_label. */
  extra?: Record<string, unknown>;
  /** False asks for the unfiltered answer even on a night the desk would narrow. */
  auto_lens?: boolean;
}

export interface UniverseEntry {
  ticker: string;
  spot_symbol: string;
  perp_symbol: string | null;
  is_core: boolean;
  has_data: boolean;
}

export interface Health {
  ok: boolean;
  version: string;
  time: string;
  bars: number;
  orderbook_snapshots: number;
  last_book_ts: string | null;
  tickers_with_data: number;
  warm: { state: string; done: number; total: number };
  chat_ready: boolean;
  uptime_s?: number;
  llm?: { ready: boolean; provider?: string; model?: string };
}

export interface DataSource {
  key: string;
  label: string;
  what: string;
  cadence: string;
  last_update: string | null;
  rows: number;
  latest: string | null;
  latest_label: string | null;
  url: string;
  /** Only the Bitget US-stock row sets this: "unavailable" while the service is failing. */
  status?: "ok" | "unavailable" | "no data yet" | "degraded";
  down_since?: string | null;
  http_status?: number | null;
  /** What the feed is used for in a report, and the strongest thing it can do to an answer. */
  used_for?: string;
  used_for_zh?: string;
  effect?: string;
}

export interface GateRule {
  rule: string;
  decision: "GO" | "REVIEW_REQUIRED" | "NO_GO";
  reason: string;
}

export interface Cap {
  name: string;
  notional: number | null;
  detail: string;
}

export interface CohortStats {
  n: number;
  n_pending: number;
  insufficient: boolean;
  mean_pct: number | null;
  median_pct: number | null;
  std_pct: number | null;
  win_rate: number | null;
  p5: number | null;
  p25: number | null;
  p75: number | null;
  p95: number | null;
  es5_pct: number | null;
  es5_n: number | null;
  mfe_median_pct: number | null;
  mae_median_pct: number | null;
  mae_p5_pct: number | null;
  excess_mean_pct: number | null;
  max_abs_basis_p95_bps: number | null;
  tag_counts: Record<string, number>;
  ci_mean: { low: number; high: number } | null;
  ci_median: { low: number; high: number } | null;
  ci_p5: { low: number; high: number } | null;
  weighted_mean_pct: number | null;
  weighted_p5: number | null;
}

export interface HorizonReport {
  horizon: string;
  hours: number;
  cohort: CohortStats;
  baseline: {
    baseline: CohortStats;
    mean_diff_pct: number | null;
    permutation_p_value: number | null;
    p5_diff_pct: number | null;
  } | null;
  p5_adjusted: number | null;
  p95_adjusted: number | null;
  /** Empty of factors when the horizon is past the longest scored hold ("uncalibrated"),
   *  which can still carry a floor; every factor is therefore optional. */
  adjustment: { k_lo?: number; k_hi?: number; c_lo?: number; n_fit?: number; fitted_through?: string | null; scope?: string; uncalibrated?: boolean; floored_by?: string } | null;
  /** The position's own view: for a short, the token's upper tail turned over. */
  loss_p5_pct?: number | null;
  pnl_median_pct?: number | null;
  pnl_win_rate?: number | null;
}

/** One named condition narrowing which past moments count as comparable.
 *
 *  The model picks these by name from a fixed list; it never writes a threshold or a
 *  column. `definition` is shown beside the result so "only earnings nights" resolves
 *  to something a reader can check rather than a query nobody can see.
 */
export interface Lens {
  name: string;
  label: string;
  definition: string;
}

/** What a narrowed search found, and what it cost in evidence.
 *
 *  `applied` false with lenses present means the desk could not honour the request:
 *  narrowing left too little history to build a distribution from, and it says so
 *  rather than answering from a handful of hours.
 */
export interface LensResult {
  lenses: Lens[];
  names: string[];
  description: string;
  n_before: number;
  n_after: number;
  applied: boolean;
  refused: string;
  /** Set when the desk narrowed the search itself, with the reason. Empty when the
   *  trader asked for the condition. */
  auto?: string;
}

/** A filing recent enough that the market has not priced it yet.
 *
 *  Two halves, deliberately separate. `category` and `headline` are the model's words
 *  about text that was public when the filing landed. Everything prefixed `label_` is
 *  not the model's: it is what this desk's bars did after every other filing the model
 *  gave the same label to, which is the only reason the label is on the page.
 *
 *  No direction. The model offers one; it was measured at 49.5% against a coin.
 */
export interface FilingNote {
  ticker: string;
  accepted_at: string;
  form: string;
  items: string | null;
  hours_ago: number;
  inside_window: boolean;
  market_was_shut: boolean;
  category: string;
  headline: string;
  market_moving: "none" | "low" | "medium" | "high" | "unread";
  label_n: number | null;
  label_p5_pct: number | null;
  label_median_pct: number | null;
  label_mean_abs_pct: number | null;
}

/** One retrieved scenario, drawn over the ticket's own horizon.
 *
 *  `values` is the token's move from that moment's entry close, in percent, on the
 *  shared `hours` grid. `stopped_at_h` is judged on the highs and lows rather than on
 *  the drawn line, because a close-to-close path understates how often a stop is hit.
 */
export interface ScenarioPath {
  ts: string;
  ticker: string;
  distance: number;
  /** Rank against every candidate hour searched: 0 the closest of hundreds of
   *  thousands, 100 the furthest. Every retrieved analog sits in the bottom fraction
   *  of this by construction, so it says how good the cohort is — not which half of
   *  the cohort a given match is in. Do not colour by it. */
  distance_percentile: number;
  /** Rank among the paths drawn here: 0 the closest, 1 the furthest. This is the one
   *  that separates the near half from the far half. */
  rank: number;
  values: number[];
  stopped_at_h: number | null;
}

export interface ScenarioPaths {
  hours: number[];
  paths: ScenarioPath[];
  fan: { p5: number[]; p25: number[]; p50: number[]; p75: number[]; p95: number[] };
  /** Signed distance of the stop from entry, in percent; null when no stop was given. */
  stop_pct: number | null;
  stopped: number;
  n_dropped: number;
}

/** One falsifiable claim about the retrieval, tested against the desk's own history.
 *
 *  `consequence` is the part that stops these being decoration: every study says what
 *  changed in the product because of it, including "nothing, and here is why".
 */
export interface Study {
  key: string;
  title: string;
  question: string;
  method: string;
  finding: string;
  consequence: string;
  /** Answers the question in `title`, not whether the answer was good news. */
  verdict: "yes" | "no" | "unclear";
  n: number;
  stats: Record<string, number>;
  ran_at: string;
  /** Null when the study is not a hypothesis test (a fixed tolerance, not a null). */
  p_value?: number | null;
  /** Benjamini-Hochberg adjusted p across every study that has one. */
  q_value?: number | null;
  survives_fdr?: boolean | null;
  /** How p was derived, in words, including any approximation. */
  p_method?: string;
  small_sample?: boolean;
  small_sample_note?: string | null;
}

/** The multiple-testing correction applied across the studies. */
export interface StudiesFdr {
  method: string;
  alpha: number;
  m_tests: number;
  m_studies: number;
  yes_total: number;
  yes_tested: number;
  yes_survive: number;
  yes_fail: string[];
}

/** A point estimate with a 95% interval; null where it could not be computed. */
export interface Est {
  est: number | null;
  lo: number | null;
  hi: number | null;
}

export interface MovementBlock {
  n_windows: number;
  n_weeks?: number;
  stats: Record<string, Est>;
  per_token?: { ticker: string; n_windows: number; n_closed: number; var_share: Est; time_share: number; per_hour_var_ratio: Est }[];
}

export interface WeekendBlock {
  n: number;
  n_weeks?: number;
  tokens?: number;
  mean_abs_move_pct?: number;
  mean_abs_gap_pct?: number;
  stats: Record<string, Est>;
  tokens_with_positive_slope?: number;
  tokens_scored?: number;
}

/** The measured study of what happens while the US market is shut. A measurement, not a
 *  hypothesis test: it is served beside the studies and is not part of their correction. */
export interface ClosedHours {
  key: string;
  ran_at: string;
  questions: string[];
  settings: { stale_hours: number; big_move: number; block_weeks: number; bootstrap_draws: number };
  data: { tokens: number; first_day: string; last_day: string; windows: number; closed_windows: number };
  movement: { primary: MovementBlock; fresh_only: MovementBlock; no_earnings: MovementBlock; hourly_tally?: { n_hours: number; stats: Record<string, Est> } };
  weekend?: { verdict: "yes" | "no" | "unclear"; dropped_stale: number; primary: WeekendBlock; by_anchor: Record<string, WeekendBlock> };
  overnight?: { by_anchor: Record<string, WeekendBlock> };
  liquidity: {
    n_snapshots: number;
    n_days?: number;
    first_day?: string;
    last_day?: string;
    n_weekend_windows?: number;
    tokens?: number;
    stats: Record<string, Est>;
  };
}

/** One stored headline or SEC filing a claim was checked against. */
export interface ThesisItem {
  id: string;
  kind: "news" | "filing";
  title: string;
  source: string;
  published_at: string;
  link: string | null;
}

export interface ThesisClaim {
  claim: string;
  status: "supported" | "contradicted" | "not_found" | "related";
  evidence: ThesisItem[];
  note: string;
}

/** The trader's reason against the headlines and filings stored before the report. */
export interface ThesisCheck {
  state: "checked" | "no_thesis" | "no_items";
  method: "model" | "keyword" | "none";
  ticker: string;
  window_days: number;
  items_considered: number;
  claims: ThesisClaim[];
  model: string | null;
}

/** What the report quotes for one token from that measurement. */
export interface ClosedHoursLine {
  ticker: string;
  line: string | null;
  ran_at: string | null;
  numbers: {
    closed_share_pct: number;
    closed_share_lo: number | null;
    closed_share_hi: number | null;
    time_share_pct: number;
    n_windows: number;
    weekend_slope_open?: number;
    weekend_slope_lo?: number | null;
    weekend_slope_hi?: number | null;
    n_weekends?: number;
  } | null;
}

export interface StudiesResponse {
  studies: Study[];
  fdr?: StudiesFdr;
  last_run: string | null;
  note: string;
  closed_hours?: ClosedHours | null;
}

/** One window length, scored on its own.
 *
 *  The overall reading can sit on target while both halves of it are wrong in
 *  opposite directions, which is what a single pooled factor produced here. These
 *  rows are how that stops being invisible.
 */
export interface BandEvaluation {
  band: string;
  n: number;
  raw_lo_coverage: number;
  adj_lo_coverage: number;
  adj_hi_coverage: number;
  raw_width: number;
  adj_width: number;
  adj_tail_band: string;
  k_lo: number;
  k_hi: number;
  c_lo?: number;
  n_nights?: number | null;
  adj_lo_night_ci?: [number, number] | null;
}

export interface AdjustedEvaluation {
  n_evaluated: number;
  raw_lo_coverage: number;
  adj_lo_coverage: number;
  raw_hi_coverage: number;
  adj_hi_coverage: number;
  raw_band_coverage: number;
  adj_band_coverage: number;
  raw_tail_band: string;
  adj_tail_band: string;
  raw_width: number;
  adj_width: number;
  k_lo_last: number | null;
  k_hi_last: number | null;
  c_lo_last?: number | null;
  lo_ci: [number, number];
  adj_lo_ci: [number, number];
  bands: BandEvaluation[];
  /** Distinct as-of nights behind n_evaluated. Forecasts on one night share its shock. */
  n_nights?: number | null;
  /** Breach-rate intervals from resampling whole nights; lo_ci/adj_lo_ci assume independent forecasts. */
  raw_lo_night_ci?: [number, number] | null;
  adj_lo_night_ci?: [number, number] | null;
}

export interface QuantileSkill {
  quantile: string;
  tau: number;
  loss_analog: number;
  loss_baseline: number;
  skill: number;
  diff_ci_low: number;
  diff_ci_high: number;
  win_share: number;
}

export interface SkillReport {
  n: number;
  per_quantile: QuantileSkill[];
  mean_loss_analog: number | null;
  mean_loss_baseline: number | null;
  skill: number | null;
  diff_ci_low: number | null;
  diff_ci_high: number | null;
  win_share: number | null;
  baseline_lo_coverage: number | null;
  baseline_hi_coverage: number | null;
  analog_lo_coverage: number | null;
  analog_hi_coverage: number | null;
  by_ticker: Record<string, number>;
}

export interface PeriodScore {
  label: string;
  start: string;
  end: string;
  n: number;
  thin: boolean;
  raw_lo_coverage: number;
  adj_lo_coverage: number;
  raw_band_coverage: number;
  adj_band_coverage: number;
  raw_width: number;
  adj_width: number;
  k_lo: number;
  k_hi: number;
  lo_ci: [number, number];
  skill: number | null;
  mean_abs_error_p50: number | null;
}

export interface WalkForward {
  periods: PeriodScore[];
  freq: string;
  n_total: number;
  improving: boolean | null;
  note: string;
}

export interface AnalogMatch {
  ts: string;
  ticker: string;
  distance: number;
  similarity: number;
  distance_percentile: number;
  bucket: string;
  features: Record<string, number>;
  /** The features where this moment sits closest to now, and those more than one robust
   *  standard deviation away - why it counts as similar, and where it does not. */
  alike_on?: string[];
  differs_on?: string[];
}

export interface HorizonOutcome {
  horizon: string;
  hours: number;
  status: "MATURED" | "PENDING";
  ret_pct: number | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  native_ret_pct: number | null;
  excess_pct: number | null;
  max_abs_basis_bps: number | null;
  tag: string | null;
}

export interface MatchOutcome {
  ts: string;
  entry_close: number;
  outcomes: Record<string, HorizonOutcome>;
}

export interface Scenario {
  id: string;
  name: string;
  /** Chinese name, from the backend's map. */
  name_zh?: string;
  severity: "mild" | "moderate" | "severe" | "extreme";
  horizon_h: number;
  price_move_pct: number;
  basis_shock_bps: number;
  depth_multiplier: number;
  vol_multiplier: number;
  halt_hours: number;
  funding_rate: number;
  probability_note: string;
  calibration: Record<string, number | string>;
}

export interface ScenarioImpact {
  scenario_id: string;
  mtm_pnl_quote: number;
  basis_pnl_quote: number;
  exit_cost_quote: number | null;
  hedge_pnl_quote: number;
  funding_cost_quote: number;
  total_pnl_quote: number | null;
  total_pct_of_notional: number | null;
  exit_fully_filled: boolean;
  breaches: Record<string, boolean>;
}

export interface MonteCarlo {
  n_paths: number;
  horizon_h: number;
  block_h: number;
  source_hours: number;
  /** Pre-binned terminal returns: what the chart draws. */
  terminal_hist?: { edges: number[]; counts: number[] };
  /** Only present on reports stored before the payload was trimmed. */
  terminal_ret_pct?: number[];
  worst_drawdown_pct?: number[];
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
  expected_shortfall_5_pct: number;
  prob_loss_gt: Record<string, number>;
  drawdown_p5: number;
}

export interface ExitQuote {
  notional_quote: number;
  side: "sell" | "buy";
  mid: number;
  avg_price: number | null;
  walk_cost_bps: number | null;
  fee_bps: number;
  total_cost_bps: number | null;
  total_cost_quote: number | null;
  levels_consumed: number;
  fully_filled: boolean;
  book_ts: string;
}

export interface HedgeQuote {
  hedge_ratio: number;
  hedged_notional: number;
  perp_symbol: string;
  entry_fee_quote: number;
  exit_fee_quote: number;
  funding_quote: number;
  funding_quote_p95: number;
  total_cost_quote: number;
  total_cost_bps_of_position: number;
  residual_basis_p95_bps: number | null;
  residual_basis_quote_p95: number | null;
  note: string;
}

export interface BucketLiquidity {
  bucket: string;
  n_snapshots: number;
  thin: boolean;
  hours_covered: number;
  spread_median_bps: number | null;
  spread_p95_bps: number | null;
  depth_25bps_median: number | null;
  depth_25bps_p5: number | null;
  share_below_reference: number | null;
}

export interface LiquidityHistory {
  symbol: string;
  since: string | null;
  until: string | null;
  n_snapshots: number;
  buckets: BucketLiquidity[];
  reference_notional: number;
  note: string;
}

export interface SizePoint {
  notional: number;
  verdict: string;
  gate: string;
  binding_cap: string | null;
  recommended_notional: number | null;
  worst_severe_pct: number | null;
  exit_cost_bps: number | null;
  risk_pct_of_equity: number | null;
}

export interface StopPoint {
  stop_distance_pct: number;
  stop_price: number;
  verdict: string;
  gate: string;
  risk_pct_of_equity: number | null;
  risk_budget_notional: number | null;
}

export interface Sensitivity {
  sizes: SizePoint[];
  stops: StopPoint[];
  max_go_notional: number | null;
  widest_stop_pct_for_requested_size: number | null;
  requested_notional: number;
  notes: string[];
  /** Only when no account size was given: the trade judged at a few account sizes. */
  account_ladder?: AccountPoint[];
  min_go_equity?: number | null;
}

export interface AccountPoint {
  equity: number;
  verdict: string;
  recommended_notional: number | null;
  binding_cap: string | null;
  /** Gate rules a bigger account alone cannot clear. */
  blocking?: string[];
}

export interface Lesson {
  forecast_id: number;
  as_of: string;
  ticker: string;
  kind: string;
  classification: string;
  text: string;
  notable: boolean;
  ret_pct: number;
  p5: number | null;
  bucket: string | null;
  regime_label: string | null;
}

export interface WindowLoss {
  name: string;
  hours: number;
  realised_quote: number;
  limit_quote: number | null;
  used_fraction: number | null;
  n_trades: number;
}

export interface BreakerReport {
  state: "NORMAL" | "COOLDOWN" | "HALTED";
  reasons: string[];
  windows: WindowLoss[];
  losing_streak: number;
  n_taken: number;
  equity: number | null;
}

export interface BookRisk {
  gross_quote: number;
  net_quote: number;
  gross_pct_of_equity: number | null;
  net_pct_of_equity: number | null;
  largest_name: string | null;
  largest_pct_of_gross: number | null;
  top3_pct_of_gross: number | null;
  tail_loss_quote: number | null;
  standalone_tail_sum_quote: number | null;
  diversification_ratio: number | null;
}

export interface PairCorrelation {
  a: string;
  b: string;
  correlation: number | null;
  overlap_hours: number;
}

export interface Contribution {
  ticker: string;
  side: string;
  notional_quote: number;
  share_of_gross: number;
  component_quote: number | null;
  component_share: number | null;
  marginal_quote: number | null;
  note: string;
}

export interface Attribution {
  book_tail_quote: number | null;
  n_windows: number;
  contributions: Contribution[];
  notes: string[];
}

export interface PortfolioReport {
  positions: { ticker: string; side: string; notional_quote: number }[];
  before: BookRisk;
  after: BookRisk;
  attribution: Attribution | null;
  correlations: PairCorrelation[];
  mean_correlation_to_book: number | null;
  notes: string[];
  horizon_h: number;
  /** Holdings with no stored history: left out of the tail, never counted as flat. */
  unknown: string[];
  /** Start of the historical window in which the whole book lost most. */
  worst_window: string | null;
  /** The new trade's name when it is already held: held, combined, share of equity. */
  same_name: { ticker: string; held_signed_quote: number; combined_signed_quote: number; combined_pct_of_equity: number | null; same_direction_quote: number } | null;
  /** How many shared historical windows the tail was read from. */
  windows: number;
  /** The book's tail with the trade at the size the desk recommends. */
  tail_after_recommended_quote: number | null;
  /** The book_tail cap: the largest size that keeps the whole book's one-in-twenty loss inside the limit. */
  book_cap_quote: number | null;
  book_cap_pct_of_equity: number | null;
  book_cap_binds: boolean;
  /** Whole-book crash replays, rebalance plans and reverse stress. Absent when the book could not be measured. */
  stress?: BookStress | null;
}

export interface BookScore {
  tail_quote: number;
  tail_pct_of_equity: number | null;
  worst_window_quote: number;
  worst_crash_quote: number | null;
  worst_crash_name: string | null;
  inside_limit: boolean | null;
}

export interface RebalancePlan {
  lever: "smaller_trade" | "skip_trade" | "trim_holding" | "hedge_perp";
  ticker: string;
  amount_quote: number;
  fraction: number | null;
  cost_quote: number;
  before: BookScore;
  after: BookScore;
  achieves_limit: boolean;
  detail: string;
  notes: string[];
}

export interface BookCrash {
  key: string;
  name: string;
  date: string | null;
  held_quote: number | null;
  asked_quote: number | null;
  worst_ticker: string | null;
  missing: string[];
}

export interface BookReverseLevel {
  key: "limit" | "ten_pct";
  loss_quote: number;
  loss_pct_of_equity: number;
  shock_pct_before: number | null;
  shock_pct_after: number | null;
  windows_hit_before: number;
  windows_hit_after: number;
}

export interface BookStress {
  limit_quote: number | null;
  limit_pct_of_equity: number | null;
  breached: boolean | null;
  book_alone_over_limit: boolean;
  windows: number;
  direction: "down" | "up" | null;
  asked_score: BookScore | null;
  crashes: BookCrash[];
  plans: RebalancePlan[];
  reverse: BookReverseLevel[];
  liquidation: { ticker: string; leverage: number; distance_pct: number; windows_hit: number; windows: number; comes_before_limit: boolean | null } | null;
  notes: string[];
}

export interface Regime {
  id: number;
  n: number;
  share: number;
  centre: Record<string, number>;
  description: string;
  persistence: number | null;
  next_ret_median_pct: number | null;
  next_ret_p5_pct: number | null;
  next_ret_p95_pct: number | null;
  n_outcomes: number;
  /** Share of windows in this state that ended exactly where they started: the token
   *  never traded. It is why the medians sit on zero. */
  flat_share: number | null;
}

export interface RegimeMap {
  regimes: Regime[];
  transitions: number[][];
  current: number | null;
  horizon_h: number;
  n_fitted: number;
  note: string;
}

export interface Counterpoint {
  kind: string;
  text: string;
  magnitude_quote: number | null;
  source: string;
}

export interface SecondOpinion {
  verdict: string;
  against: Counterpoint[];
  supporting: Counterpoint[];
  summary: string;
}

export interface Watch {
  ticker: string;
  side: string;
  notional_quote: number;
  p5_pct: number | null;
  p5_quote: number | null;
  worst_preset: string | null;
  worst_preset_quote: number | null;
  exit_cost_bps: number | null;
  exit_fills: boolean;
  thin_share: number | null;
  regime_label: string | null;
  events: string[];
  flags: string[];
  headline: string;
  attention: number;
}

export interface TonightReport {
  as_of: string;
  window_end: string | null;
  hours: number;
  market_is_open: boolean;
  items: Watch[];
  gross_quote: number;
  tail_quote: number | null;
  summary: string;
  note: string;
}

/** The model's reading of a finished report. Written in the background; never changes
 *  the verdict, and any sentence citing a number not in the report is removed. */
export interface AgentStep {
  n: number;
  thought?: string;
  tool?: string;
  args?: Record<string, unknown>;
  result_summary?: string;
  seconds?: number;
}
export interface AgentRun {
  status: "running" | "done" | "failed" | "none";
  steps?: AgentStep[];
  final?: { summary?: string; findings?: string[]; verdict_restated?: string } | null;
  removed?: number;
  error?: string;
}

export interface AnalystTake {
  status: "pending" | "done" | "failed" | "unavailable" | "none";
  text?: string;
  removed?: number;
  model?: string;
  seconds?: number;
  lang?: string;
  /** Every number the take quotes, with the report section it came from. */
  citations?: { number: string; source: string }[];
  /** The two-sided case: each at most two sentences, every number tagged [section]. */
  for?: string;
  against?: string;
  /** One line restating the desk's verdict and size; never a new verdict. */
  reconcile?: string;
}

export interface EntryPlan {
  side: "buy" | "sell";
  notional: number;
  budget_bps: number;
  full_cost_bps: number | null;
  full_fills: boolean;
  slices: number | null;
  slice_notional: number | null;
  slice_cost_bps: number | null;
  limit_price: number | null;
  mid: number | null;
  book_ts: string;
  note: string;
}

export interface PlanCheck {
  invalidation: string;
  kind: "level" | "moving_average" | "move" | "wrong_side" | "untested";
  level: number | null;
  distance_pct: number | null;
  crossed: number | null;
  of: number | null;
  already: boolean;
  note: string;
  thesis_mismatch: string;
  /** The token's own one-in-twenty move over the hold, and whether the line is beyond it. */
  reach_pct?: number | null;
  too_far?: boolean;
}

/** Bitget signal skill's RSI beside the desk's own from Bitget candles. Context only. */
export interface SignalView {
  source: string;
  ticker: string;
  rsi: number;
  timeframe: string;
  reading: "oversold" | "overbought" | "neutral";
  own_rsi: number;
  agrees: boolean;
  fetched_at: string;
  macd: { macd: number; signal: number; histogram: number; cross: string | null } | null;
}

/** One dividend, split or exchange notice, with the source it came from. */
export interface CorporateEvent {
  kind: "dividend" | "split" | "suspension" | "notice";
  /** Ex-date / effective date, US Eastern calendar date (YYYY-MM-DD). */
  date: string;
  amount: number | null;
  currency: string | null;
  /** new:old, so 1:10 is a reverse split. */
  ratio: string | null;
  /** When the issuer or exchange said so, if the source says. */
  announced: string | null;
  source: string;
  source_label: string;
  detail: string | null;
  url: string | null;
  amount_pct_of_price?: number;
}

/** What the stored calendar knows about dividends, splits and Bitget notices around the
 *  hold. Point in time; never fetched during an analysis. */
export interface CorporateEvents {
  ticker: string;
  as_of: string;
  window_end: string;
  checked_at: string | null;
  /** False until the calendar has synced once: then "none" would mean "not looked". */
  covered: boolean;
  in_hold: CorporateEvent[];
  next_after: CorporateEvent | null;
  last_split: CorporateEvent | null;
  notices: CorporateEvent[];
  /** Set when something is inside the hold: says rToken handling is not verified. */
  handling: string | null;
  sources: string[];
}

/** More of Bitget's US-stock catalogue, read from the desk's cache (never fetched by the report):
 *  the company's own earnings date beside Nasdaq's, valuation, dividends, analyst consensus.
 *  Every entry is optional: the ones the service has not delivered are simply absent. Context only. */
export interface BitgetBlock {
  source: "Bitget";
  fetched_at: string | null;
  earnings_check: { status: "agree" | "differ" | "bitget_only" | "nasdaq_only"; bitget: string | null; nasdaq: string | null; gap_days: number | null } | null;
  entries: {
    equity_calendar?: { fetched_at: string | null; next_report?: string; days_ahead?: number; confirmed?: boolean; timing?: string; last_report?: string; days_ago?: number; text: string };
    equity_fundamental_ratios?: { fetched_at: string | null; pe?: number; pb?: number; ps?: number; div_yield_12m?: number; market_cap_usd?: number; period_ending?: string; text: string };
    equity_fundamental_dividends?: { fetched_at: string | null; next_ex_date?: string; next_amount?: number; days_ahead?: number; last_ex_date?: string; last_amount?: number; paid_last_12m: number; currency?: string; text: string };
    equity_estimates_consensus?: { fetched_at: string | null; target_consensus?: number; target_median?: number; target_high?: number; target_low?: number; text: string };
    equity_profile?: { fetched_at: string | null; sector?: string; industry?: string; exchange?: string; ceo?: string; employees?: number; text: string };
  };
}

/** Bitget's view of the underlying stock right now. None of it reaches the size. */
export interface StreetView {
  ticker: string;
  fetched_at: string;
  last_price: number | null;
  prev_close: number | null;
  n_ratings: number;
  n_firms: number;
  bullish: number;
  neutral: number;
  bearish: number;
  median_target: number | null;
  target_gap_pct: number | null;
  upgrades_recent: number;
  downgrades_recent: number;
  recent_changes: { date: string; firm: string; action: string; rating: string; target: number | null }[];
  insider_buys: number;
  insider_sells: number;
  insider_bought_value: number;
  insider_sold_value: number;
  insider_latest: { date: string; name: string; title: string; side: "buy" | "sell"; shares: number; price: number | null }[];
  mood_score: number | null;
  mood_rating: string | null;
  mood_week_ago: number | null;
  mood_month_ago: number | null;
  source: string;
  /** Desk's native close against Bitget's figure for the same close, in bps. */
  quote_gap_bps?: number | null;
  /** The token against the stock's live price and against the last close, in bps. */
  token_vs_live_bps?: number | null;
  token_vs_close_bps?: number | null;
  /** Seconds since this view was fetched, and whether it is being served as "last good"
   *  (the feed stopped answering, or it is more than 2 h old) rather than live. */
  age_s?: number | null;
  stale?: boolean;
  age_label?: string | null;
}

/** Open interest on the token's Bitget perpetual, with its change against the desk's own
 *  recorded reading about a day ago (null until the recorder has one that old). */
export interface OpenInterestView {
  symbol: string;
  contracts: number;
  usd: number | null;
  observed_at: string;
  change_24h_pct: number | null;
  compared_with_ts: string | null;
  line: string;
  /** Top decile of this perp's own 24 h changes: a caution flag on the report. */
  crowded?: boolean;
  threshold_pct?: number | null;
  crowded_line?: string | null;
}

/** The options market's one-standard-deviation move over this hold (Cboe delayed quotes)
 *  beside the desk's own one-in-twenty loss. */
export interface OptionsView {
  ticker: string;
  source: string;
  spot: number;
  expiry: string;
  atm_strike: number;
  atm_iv_pct: number;
  hold_h: number;
  implied_move_pct: number;
  straddle_move_pct: number;
  iv30_pct: number | null;
  /** The quote's own time (the last trade it prices), not when the desk fetched it. */
  quote_ts: string | null;
  fetched_at: string;
  /** The desk's own one-in-twenty loss for this position (negative), or null. */
  desk_p5_pct: number | null;
  line: string | null;
  /** True when the options market's move beat every severe move in the token's history, so the
   *  stress limit was sized on it. */
  sizing_binding?: boolean;
  history_severe_pct?: number | null;
}

/** One source a report used, what it supplied and whether it changed the answer. */
export interface SourceEffect {
  kind: string;
  label: string | null;
  effect: "moved_size" | "set_preset" | "raised_flag" | "context";
  supplied: string;
  supplied_zh: string;
  note: string;
  note_zh: string;
}

export interface FailureMode {
  key: string;
  title: string;
  trigger: string;
  mechanism: string;
  loss_quote: number | null;
  loss_pct: number | null;
  likelihood: string;
  source: string;
  short: string;
  /** Chinese name, from the backend's map, when it has one. */
  title_zh?: string;
  /** The same loss at the recommended size, when that is smaller than the one asked for. */
  loss_quote_at_recommended?: number | null;
}

export interface LeverageView {
  leverage: number;
  perp_symbol: string | null;
  margin_quote: number;
  liquidation_price: number | null;
  liquidation_distance_pct: number | null;
  mmr: number;
  max_leverage_at_size: number | null;
  tiers_source: "bitget" | "assumed";
  allowed: boolean;
  analog_hits: number | null;
  analog_of: number | null;
  presets_hit: string[];
  mc_share: number | null;
  notes: string[];
  /** The same position at other leverage levels, lowest first; empty without a perpetual. */
  ladder?: LadderRung[];
  /** The highest level the gate calls clear on this evidence, or null when none is. */
  safest_leverage?: number | null;
  /** Margin needed to move from the requested level to it; null when already that safe. */
  safest_extra_margin_quote?: number | null;
  /** One plain sentence on open interest and its 24 h change; absent when Bitget did not answer. */
  open_interest_line?: string;
  /** "crowded: OI +X% in 24h" when the perp's open interest is in its own top decile. */
  open_interest_crowded_line?: string | null;
}

export interface LadderRung {
  leverage: number;
  requested: boolean;
  liquidation_price: number | null;
  distance_pct: number | null;
  /** Notional / leverage: what holding the same size asks for at this level. */
  margin_quote: number;
  analog_hits: number | null;
  analog_of: number | null;
  /** Whether the calibrated 1-in-20 loss reaches the liquidation price. */
  p5_reaches: boolean | null;
  presets_hit: string[];
  gate: "GO" | "REVIEW_REQUIRED" | "NO_GO";
}

export interface Report {
  ticket: TicketInput & { created_at?: string | null };
  as_of: string;
  horizon_h: number;
  primary_horizon: string;
  snapshot: {
    ticker: string;
    as_of: string;
    bar_ts: string;
    features: Record<string, number | null>;
    labels: Record<string, string>;
    prices: Record<string, number | null>;
    quality_flags: string[];
    history_hours: number;
    content_hash: string;
  };
  analog: {
    result: {
      ok: boolean;
      reason: string;
      matches: AnalogMatch[];
      features_used: string[];
      features_dropped: string[];
      n_history_rows: number;
      n_candidates: number;
      n_distinct_available: number;
      distance_scale: number | null;
      /** Now, on the features the search used. */
      query?: Record<string, number>;
      /** Slow, market-wide fields (VIX, curve, dollar) left out of every "alike on". */
      broad_features?: string[];
      /** Distinct calendar weeks the matches fall in. */
      n_weeks?: number;
    };
    scope: "same_ticker" | "pooled";
    horizons: Record<string, HorizonReport>;
    matches_outcomes: MatchOutcome[];
    paths: ScenarioPaths | null;
    lens: LensResult | null;
    /** A hold over a weekend, matched to past weekend holds; k_weekend of n_matches were one. */
    weekend_hold?: { applies: boolean; restricted: boolean; n_before: number; n_after: number; note: string; k_weekend: number | null; n_matches: number | null } | null;
  } | null;
  stress: {
    presets: Scenario[];
    impacts: ScenarioImpact[];
    monte_carlo: MonteCarlo | null;
    reverse_move_pct_for_5pct_loss: number | null;
    inputs_summary: Record<string, number> & { earnings_in_window?: boolean; hours_to_earnings?: number | null };
  };
  execution: {
    exit_quote: ExitQuote | null;
    cost_curve: { notional: number; walk_cost_bps: number | null; total_cost_bps: number | null; levels: number; fully_filled: boolean }[] | null;
    max_notional_within_budget: number | null;
    hedge_quote: HedgeQuote | null;
    book_ts: string | null;
    book_source: string;
    liquidity_history: LiquidityHistory | null;
  };
  gate: { decision: "GO" | "REVIEW_REQUIRED" | "NO_GO"; rules: GateRule[]; risk_quote: number | null; risk_pct_of_equity: number | null; risk_basis: string };
  sizing: { recommended_notional: number | null; binding_cap: string | null; caps: Cap[]; hedge_ratio_suggested: number | null; hedge_rationale: string };
  verdict: { verdict: "GO" | "REDUCE_TO" | "HEDGE" | "NO_GO" | "REVIEW"; requested_notional: number; recommended_notional: number | null; hedge_ratio: number | null; reasons: string[]; caps: Cap[] };
  sensitivity: Sensitivity | null;
  lessons: Lesson[];
  breaker: BreakerReport;
  portfolio: PortfolioReport | null;
  regimes: RegimeMap | null;
  second_opinion: SecondOpinion | null;
  filings: FilingNote[];
  /** Analysts, insiders, market mood and a live quote for the stock, from Bitget's
   *  US-stock data. Context only; null for past moments and when the service is down. */
  street?: StreetView | null;
  /** Earnings calendar (cross-checked against Nasdaq), valuation, dividends and consensus from Bitget's catalogue. Context only; null for past moments. */
  bitget?: BitgetBlock | null;
  /** Ex-dividend dates, splits and Bitget notices around the hold, from the stored calendar. */
  corporate_events?: CorporateEvents | null;
  /** Perp open interest and its 24 h change. Context only; null for past moments or when Bitget did not answer. */
  open_interest?: OpenInterestView | null;
  /** What the options market implies for this hold, beside the desk's own 1-in-20 loss.
   *  Null for past moments, names with no listed options, or while the cache is cold. */
  options?: OptionsView | null;
  /** For every source used: what it supplied and whether it changed the answer. */
  source_effects?: SourceEffect[];
  /** The signal skill's RSI, only when it agrees with our own; null otherwise. Context only. */
  signal?: SignalView | null;
  /** The trader's invalidation read for a testable level and measured; plus a flag when
   *  the stated reason reads against the position. */
  plan_check?: PlanCheck | null;
  /** How to get into the recommended size on the live book. */
  entry_plan?: EntryPlan | null;
  /** A leveraged ticket's liquidation price and how often history reached it. */
  leverage?: LeverageView | null;
  /** What the verdict assumes, written by rules from the report's own fields. */
  assumptions?: { topic: string; text: string; kind: "fact" | "caveat" }[];
  /** How this trade loses money, worst first: trigger, mechanism, cost and how often. */
  failure_modes?: FailureMode[];
  /** Where the stated reason depends on an event the data can date, and does not match. */
  premise?: string[];
  weekend_only?: WeekendOnly | null;
  /** Who turned the sentence into a ticket: "rules" when no model was needed. Chat reports only. */
  read_by?: { parsed_by: string; provider?: string | null; model?: string | null } | null;
  /** US regular sessions around the hold (NYSE calendar), for the market-clock strip. */
  timeline?: { as_of: string; hold_end: string; market_open_at_as_of: boolean; next_open: string | null; sessions: { open: string; close: string }[] } | null;
  /** The chained journal receipt for this verdict; see /verify. */
  receipt?: string | null;
  /** Where each headline number came from: live Bitget, history, assumed or AI. */
  provenance?: Provenance | null;
  sources: Record<string, unknown>[];
  warnings: string[];
  timings_ms: Record<string, number>;
  forecast_id: number | null;
}

/** One finished stage of an analysis, in both languages, from /chat/stream. */
export interface ChatStep {
  stage: string;
  en: string;
  zh: string;
  ms: number;
}

/** The small picture under a chat answer. Every number in it is a field of the answer or of
 *  the report on screen; the backend builds it and the page only draws it. */
export interface ShockCard {
  kind: "shock";
  ticker: string | null;
  side: "long" | "short";
  size: number;
  /** The stock's move and the position's, in percent. */
  move_pct: number;
  pnl_pct: number;
  pnl_quote: number;
  p5_pct: number | null;
  p5_quote: number | null;
  worst_quote: number | null;
  worst_name: string | null;
  past: { p5_move_pct: number | null; p1_move_pct: number | null; windows: number | null; beyond: "1_in_20" | "1_in_100" | null } | null;
}
export interface CompareRow {
  key: "verdict" | "size" | "p5" | "worst" | "worst_pct" | "exit";
  unit: "verdict" | "usd" | "pct" | "bps";
  before: string | number | null;
  after: string | number | null;
}
export interface CompareCard {
  kind: "compare";
  ticker: string | null;
  rows: CompareRow[];
}
export interface BaseRateCard {
  kind: "base_rate";
  ticker: string;
  move_pct: number;
  up: boolean;
  weekend: boolean;
  windows: { n: number; hits: number; share: number; since: string; biggest_pct: number } | null;
  conditional: { n: number; hits: number; share: number } | null;
}
export interface WaysCard {
  kind: "ways";
  rows: { label: string; label_zh: string | null; verdict: string; size: number; hours: number; p5_pct: number | null; p5_quote: number | null; worst_quote: number | null; exit_bps: number | null }[];
  pick: string | null;
}
export type ChatCard = ShockCard | CompareCard | BaseRateCard | WaysCard;

export interface ChatResponse {
  /** A compact picture of the answer's own numbers, where one helps. Absent otherwise. */
  card?: ChatCard;
  intent: { kind: string; missing_fields: string[]; reply: string } & Record<string, unknown>;
  ticket: Record<string, unknown> | null;
  report: Report | null;
  narrative: string | null;
  report_text: string | null;
  unverified_numbers: string[];
  reply: string;
  /** "model" when the language layer answered, "rules" when the built-in parser did,
   *  "what_if" when the question was a counterfactual and the desk ran it. */
  mode?: "model" | "rules" | "what_if";
  /** Set when the turn answered a question about an existing report rather than running
   *  a new one: the report it read, and which kind of question it took it to be. */
  answered_about?: number | null;
  answer_kind?: string | null;
  /** On a what-if, which fields of the ticket the question asked to vary. The model
   *  named them; it did not compute anything that follows from them. */
  changed?: Record<string, unknown>;
}

export interface Coverage {
  quantile: string;
  nominal: number;
  observed: number;
  n: number;
  ci_low: number;
  ci_high: number;
  within_ci: boolean;
  n_nights?: number | null;
  night_ci_low?: number | null;
  night_ci_high?: number | null;
}

export interface SinceFreeze {
  frozen_at: string;
  git_tag: string | null;
  git_commit: string | null;
  note: string | null;
  label: string;
  n: number;
  breaches: number;
  rate: number | null;
  wilson_ci: [number, number] | null;
  n_nights: number;
  night_ci: [number, number] | null;
  hi_breaches: number;
  hi_rate: number | null;
}

export interface CalibrationReport {
  matured_now: number;
  n_matured: number;
  coverage: Coverage[];
  tail: {
    n: number;
    breaches: number;
    expected_rate: number;
    observed_rate: number;
    pof_stat: number | null;
    pof_p_value: number | null;
    independence_stat: number | null;
    independence_p_value: number | null;
    conditional_stat: number | null;
    conditional_p_value: number | null;
    band: "green" | "amber" | "red" | "insufficient";
    n_nights?: number | null;
    night_ci?: [number, number] | null;
  };
  since_freeze?: SinceFreeze;
  independence_note?: string;
  pit_histogram: Record<string, number>;
  mean_width_p5_p95: number | null;
  mean_abs_error_p50: number | null;
  by_ticker: Record<string, number>;
  adjusted: AdjustedEvaluation | null;
  skill: SkillReport | null;
  walk_forward: WalkForward | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${withIdentity(path)}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  } catch {
    throw new ApiError("Cannot reach the Nightwatch API. Is the backend running?", 0);
  }
  // The proxy sets this header when the box is down and it answered from a saved copy.
  snapshotFlag.set(res.headers.get(SNAPSHOT_HEADER));
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  universe: (core = true) => request<UniverseEntry[]>(`/universe?core=${core}`),
  sources: () => request<DataSource[]>("/sources"),
  report: (forecastId: string | number) => request<Report>(`/reports/${forecastId}`),
  tonight: (positions: { ticker: string; side: string; notional_quote: number }[], accountEquity?: number | null) =>
    request<TonightReport>("/tonight", { method: "POST", body: JSON.stringify({ positions, account_equity_quote: accountEquity ?? null }) }),
  analyze: (ticket: TicketInput) => request<Report>("/analyze", { method: "POST", body: JSON.stringify(ticket) }),
  chat: (messages: { role: "user" | "assistant"; content: string }[], accountEquity?: number | null, contextForecastId?: number | null) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      // The report already on screen, so "why not bigger" can be answered from it.
      body: JSON.stringify({ messages, account_equity_quote: accountEquity ?? null, context_forecast_id: contextForecastId ?? null }),
    }),
  /** The same turn as `chat`, with each finished analysis stage reported to `onStep` while
   *  it runs. If the stream cannot start, or is cut before the answer, this asks plain
   *  `/chat` instead, so a proxy that buffers or an old backend only loses the live steps. */
  chatStream: async (
    messages: { role: "user" | "assistant"; content: string }[],
    accountEquity: number | null | undefined,
    contextForecastId: number | null | undefined,
    onStep: (s: ChatStep) => void,
    lang: "en" | "zh" = "en",
  ): Promise<ChatResponse> => {
    const again = () =>
      request<ChatResponse>("/chat", {
        method: "POST",
        body: JSON.stringify({ messages, account_equity_quote: accountEquity ?? null, context_forecast_id: contextForecastId ?? null }),
      });
    let res: Response;
    try {
      res = await fetch(`${API_URL}${withIdentity("/chat/stream")}`, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify({ messages, account_equity_quote: accountEquity ?? null, context_forecast_id: contextForecastId ?? null }),
      });
    } catch {
      return again();
    }
    if (!res.ok || !res.body || !(res.headers.get("content-type") ?? "").startsWith("text/event-stream")) return again();
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    // Once a step has arrived the analysis is running on the server, and asking again would
    // run (and journal) the same trade twice; past that point a cut stream is an error.
    let started = false;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let cut: number;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          const kind = /^event: (.+)$/m.exec(block)?.[1];
          const data = /^data: (.+)$/m.exec(block)?.[1];
          if (!kind || !data) continue; // a keep-alive comment
          const parsed = JSON.parse(data);
          if (kind === "step") {
            started = true;
            onStep(parsed as ChatStep);
          }
          else if (kind === "done") return parsed as ChatResponse;
          else if (kind === "error") throw new ApiError(typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail), Number(parsed.status) || 500);
        }
      }
    } catch (e) {
      if (e instanceof ApiError) throw e;
    }
    if (started) throw new ApiError(lang === "zh" ? "连接在答案送达前中断了，请再发一次。" : "The connection dropped before the answer arrived. Please send it again.", 503);
    return again(); // cut before anything ran
  },
  calibration: (ticker?: string, kind?: string) => {
    const q = new URLSearchParams();
    if (ticker) q.set("ticker", ticker);
    if (kind) q.set("kind", kind);
    const s = q.toString();
    return request<CalibrationReport>(`/calibration${s ? `?${s}` : ""}`);
  },
  studies: () => request<StudiesResponse>("/studies"),
  closedHours: (ticker: string) => request<ClosedHoursLine>(`/closed-hours/${encodeURIComponent(ticker)}`),
  thesisCheck: (forecastId: number, lang: string) => request<ThesisCheck>(`/thesis-check/${forecastId}?lang=${lang === "zh" ? "zh" : "en"}`),
  verify: () => request<VerifyResponse>("/verify"),
  anchors: () => request<{ anchors: Anchor[] }>("/anchors"),
  misses: () => request<MissesResponse>("/misses"),
  analystStart: (forecastId: number, lang: "en" | "zh") => request<AnalystTake>(`/analyst/${forecastId}?lang=${lang}`, { method: "POST" }),
  agentStart: (forecastId: number, lang: "en" | "zh") => request<AgentRun>(`/agent/${forecastId}?lang=${lang}`, { method: "POST" }),
  agentGet: (forecastId: number, lang: "en" | "zh") => request<AgentRun>(`/agent/${forecastId}?lang=${lang}`),
  analystGet: (forecastId: number, lang: "en" | "zh") => request<AnalystTake>(`/analyst/${forecastId}?lang=${lang}`),
  lenses: (ticker?: string) =>
    request<{
      lenses: Lens[];
      counts: Record<string, number>;
      floor_hours: number;
      /** Per condition across every token: hours, and the separate past events those
       *  hours amount to. Below min_episodes the search cannot answer it. */
      pooled?: Record<string, { hours: number; episodes: number }>;
      min_episodes?: number;
      suggested?: string[];
      history_hours?: number;
      note?: string;
    }>(
      `/lenses${ticker ? `?ticker=${ticker}` : ""}`,
    ),
  markTaken: (forecastId: number, taken = true) => request<{ forecast_id: number; taken: boolean }>(`/forecasts/${forecastId}/taken?taken=${taken}`, { method: "POST" }),
  forecasts: (limit = 100, ticker?: string, kind?: string) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (ticker) q.set("ticker", ticker);
    if (kind) q.set("kind", kind);
    return request<Record<string, unknown>[]>(`/forecasts?${q.toString()}`);
  },
};

/** What past Friday-close-to-Monday-open weekends did to the token, shown when "over the
 *  weekend" was asked early in the week and holding from now is a longer trade. */
export interface WeekendOnly {
  n: number;
  since: string;
  p5_pct: number;
  median_pct: number;
  worst_pct: number;
  typical_h: number;
  today: string;
  hold_from_now_h: number;
  /** "Over the weekend" asked early in the week was read as the coming Friday-to-Monday hold. */
  scheduled?: boolean;
  scheduled_h?: number;
}

/** The receipt chain over every live verdict, recomputed on request. */
export interface VerifyResponse {
  ok: boolean;
  checked: number;
  head: string;
  first_break: { seq: number; forecast_id: number; reason: string } | null;
  unchained: number;
  chained_since: number | null;
  anchors?: number;
  anchored_in_bitcoin?: number;
  anchors_broken?: string[];
}

/** One daily head of the receipt chain, timestamped into Bitcoin through OpenTimestamps. */
export interface Anchor {
  name: string;
  seq: number;
  head: string;
  verified: string | null;
  state: string;
  block: number | null;
  checked_at: string | null;
  proof: string | null;
}

/** A live verdict whose outcome went past the one-in-twenty line it stated. */
export interface Miss {
  id: number;
  as_of: string;
  ticker: string;
  side: string;
  notional: number;
  horizon_h: number;
  verdict: string | null;
  stated_p5_pct: number;
  outcome_pct: number;
  loss_quote: number;
  beyond_quote: number;
  receipt: string | null;
}

export interface MissesResponse {
  totals: Record<
    string,
    {
      scored: number;
      missed: number;
      rate: number;
      /** Repeated tickets on one ticker and outcome count once here. */
      distinct_events?: number;
      distinct_missed?: number;
      distinct_rate?: number | null;
      distinct_ci?: [number, number];
      n_nights?: number;
      night_ci?: [number, number] | null;
    }
  >;
  misses: Miss[];
  target_rate: number;
}
