/** The small calls behind feedback, the usage page and re-checks. */
import { API_URL } from "@/lib/api";
import { withIdentity } from "@/lib/identity";
import { friendlyDetail, stillBusyMessage } from "@/lib/errors";
import { isRemembered, remember } from "@/lib/record-cache";
import { SNAPSHOT_HEADER, snapshotFlag } from "@/lib/snapshot";

export class EngagementError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const lang = typeof localStorage !== "undefined" && (() => { try { return localStorage.getItem("nightwatch.lang") === "zh"; } catch { return false; } })() ? "zh" : "en";
  const isRead = (init?.method ?? "GET").toUpperCase() === "GET";
  let res: Response | null = null;
  // Bounded, with one retry for a read, so a slow box ends in a plain message not a spinner.
  for (let attempt = 0; attempt < (isRead ? 2 : 1); attempt++) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), isRead ? 25_000 : 40_000);
    try {
      res = await fetch(`${API_URL}${withIdentity(path)}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) }, signal: ctl.signal });
      if (!(isRead && [502, 503, 504].includes(res.status))) break;
    } catch {
      /* retry once below */
    } finally {
      clearTimeout(timer);
    }
    await new Promise((r) => setTimeout(r, 1_500));
  }
  if (!res) throw new EngagementError(stillBusyMessage(lang), 0);
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const b = await res.json();
      detail = b.detail ?? b;
    } catch {
      /* keep statusText */
    }
    throw new EngagementError(friendlyDetail(detail, res.status, lang), res.status);
  }
  // A copy the proxy saved is shown with the banner but never remembered as a fresh reading.
  const savedAt = res.headers.get(SNAPSHOT_HEADER);
  snapshotFlag.set(savedAt);
  const data = (await res.json()) as T;
  if (isRead && isRemembered(path) && !savedAt) remember(path, data);
  return data;
}

export interface Usage {
  counted_since: string | null;
  live_verdicts: number;
  journal_live_verdicts_all_time: number;
  distinct_anonymous_clients: number;
  clients_stable_across_restarts: boolean;
  by_language: Record<string, number>;
  feedback: { useful: number; not_useful: number };
  last_notes: { at: string; useful: boolean; note: string; lang: string }[];
  follow_ups_by_answer_kind: Record<string, number>;
  note: string;
}

export interface WatchSummary {
  as_of: string | null;
  verdict: string | null;
  recommended_notional: number | null;
  requested_notional: number | null;
  gate: string | null;
  tail_p5_pct: number | null;
  median_pct: number | null;
}

export interface Watch {
  id: string;
  forecast_id: number;
  created_at: string;
  due_at: string;
  status: "pending" | "done" | "failed";
  webhook_host: string | null;
  before: WatchSummary;
  after: WatchSummary | null;
  moved: boolean | null;
  done_at: string | null;
  error: string | null;
  webhook_status: string | null;
  email: string;
}

export interface Tripwire {
  id: string;
  forecast_id: number;
  ticker: string;
  side: string;
  level: number;
  direction: "below" | "above";
  label: "stop" | "invalidation" | "liquidation" | "p5" | "custom";
  ref_price: number | null;
  created_at: string;
  status: "armed" | "fired" | "expired";
  webhook_host: string | null;
  before: WatchSummary;
  after: WatchSummary | null;
  fired_at: string | null;
  fired_price: number | null;
  error: string | null;
  webhook_status: string | null;
  /** The action chosen in advance for this line, when it came from a plan. */
  plan?: { key: string; action: PlanAction; detail: string | null; saved_at: string; reminder: string } | null;
}

export type PlanAction = "hold" | "cut_half" | "exit" | "hedge";

export interface PlanScenario {
  key: string;
  title: string;
  title_zh?: string | null;
  price: number;
  ref_price: number;
  move_pct: number;
  direction: "below" | "above";
  loss_quote: number | null;
  loss_pct: number | null;
  history: string;
  chance: number | null;
  actions: Partial<Record<PlanAction, { size_quote: number; perp_symbol?: string }>>;
  chosen?: { action: PlanAction; detail: string | null; saved_at: string; tripwire_id: string | null; tripwire_status: string | null; fired_price: number | null };
}

export interface PlanView {
  forecast_id: number;
  receipt: string | null;
  scenarios: PlanScenario[];
  saved_at: string | null;
  arm_error?: string | null;
}

export interface TripwireSuggestion {
  label: Tripwire["label"];
  level: number;
  direction: "below" | "above";
  note: string;
}

export const engagement = {
  tripwireSuggest: (forecastId: number) => call<{ suggestions: TripwireSuggestion[] }>(`/tripwire/suggest/${forecastId}`),
  tripwiresFor: (forecastId: number) => call<{ tripwires: Tripwire[] }>(`/tripwire/report/${forecastId}`),
  tripwireArm: (body: { forecast_id: number; level: number; label: string; webhook?: string | null; lang: string }) =>
    call<Tripwire>("/tripwire", { method: "POST", body: JSON.stringify(body) }),
  planGet: (forecastId: number) => call<PlanView>(`/plan/${forecastId}`),
  planSave: (body: { forecast_id: number; choices: Record<string, PlanAction>; arm: boolean; webhook?: string | null; lang: string }) =>
    call<PlanView>("/plan", { method: "POST", body: JSON.stringify(body) }),
  feedback: (body: { forecast_id: number; useful: boolean; note: string; lang: string }) =>
    call<{ ok: boolean }>("/feedback", { method: "POST", body: JSON.stringify(body) }),
  usage: () => call<Usage>("/usage"),
  watch: (body: { forecast_id: number; webhook?: string | null; lang: string }) =>
    call<Watch>("/watch", { method: "POST", body: JSON.stringify(body) }),
  getWatch: (id: string) => call<Watch>(`/watch/${encodeURIComponent(id)}`),
};
