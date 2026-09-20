/**
 * Typed client for the Nightwatch API.
 *
 * The backend is the source of every number; this module only moves JSON. Types cover
 * the fields the UI renders and are intentionally loose where the report carries
 * large or optional structures.
 */

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
  as_of?: string | null;
  record?: boolean;
  open_positions?: { ticker: string; side: Side; notional_quote: number }[];
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
  adjustment: { k_lo: number; k_hi: number; n_fit: number; fitted_through: string | null; scope: string } | null;
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
  lo_ci: [number, number];
  adj_lo_ci: [number, number];
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
    };
    scope: "same_ticker" | "pooled";
    horizons: Record<string, HorizonReport>;
    matches_outcomes: MatchOutcome[];
  } | null;
  stress: {
    presets: Scenario[];
    impacts: ScenarioImpact[];
    monte_carlo: MonteCarlo | null;
    reverse_move_pct_for_5pct_loss: number | null;
    inputs_summary: Record<string, number>;
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
  sources: Record<string, unknown>[];
  warnings: string[];
  timings_ms: Record<string, number>;
  forecast_id: number | null;
}

export interface ChatResponse {
  intent: { kind: string; missing_fields: string[]; reply: string } & Record<string, unknown>;
  ticket: Record<string, unknown> | null;
  report: Report | null;
  narrative: string | null;
  report_text: string | null;
  unverified_numbers: string[];
  reply: string;
  /** "model" when an Anthropic key answered, "rules" when the built-in parser did. */
  mode?: "model" | "rules";
  /** Set when the turn answered a question about an existing report rather than running
   *  a new one: the report it read, and which kind of question it took it to be. */
  answered_about?: number | null;
  answer_kind?: string | null;
}

export interface Coverage {
  quantile: string;
  nominal: number;
  observed: number;
  n: number;
  ci_low: number;
  ci_high: number;
  within_ci: boolean;
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
  };
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
    res = await fetch(`${API_URL}${path}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  } catch {
    throw new ApiError("Cannot reach the Nightwatch API. Is the backend running?", 0);
  }
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
  analyze: (ticket: TicketInput) => request<Report>("/analyze", { method: "POST", body: JSON.stringify(ticket) }),
  chat: (messages: { role: "user" | "assistant"; content: string }[], accountEquity?: number | null, contextForecastId?: number | null) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      // The report already on screen, so "why not bigger" can be answered from it.
      body: JSON.stringify({ messages, account_equity_quote: accountEquity ?? null, context_forecast_id: contextForecastId ?? null }),
    }),
  calibration: (ticker?: string, kind?: string) => {
    const q = new URLSearchParams();
    if (ticker) q.set("ticker", ticker);
    if (kind) q.set("kind", kind);
    const s = q.toString();
    return request<CalibrationReport>(`/calibration${s ? `?${s}` : ""}`);
  },
  markTaken: (forecastId: number, taken = true) => request<{ forecast_id: number; taken: boolean }>(`/forecasts/${forecastId}/taken?taken=${taken}`, { method: "POST" }),
  forecasts: (limit = 100, ticker?: string, kind?: string) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (ticker) q.set("ticker", ticker);
    if (kind) q.set("kind", kind);
    return request<Record<string, unknown>[]>(`/forecasts?${q.toString()}`);
  },
};
