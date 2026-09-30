/** The small calls behind feedback, the usage page and re-checks. */
import { API_URL } from "@/lib/api";
import { withIdentity } from "@/lib/identity";

export class EngagementError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${withIdentity(path)}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  } catch {
    throw new EngagementError("Cannot reach the Nightwatch API.", 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const b = await res.json();
      detail = typeof b.detail === "string" ? b.detail : detail;
    } catch {
      /* keep statusText */
    }
    throw new EngagementError(detail, res.status);
  }
  return (await res.json()) as T;
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

export const engagement = {
  feedback: (body: { forecast_id: number; useful: boolean; note: string; lang: string }) =>
    call<{ ok: boolean }>("/feedback", { method: "POST", body: JSON.stringify(body) }),
  usage: () => call<Usage>("/usage"),
  watch: (body: { forecast_id: number; webhook?: string | null; lang: string }) =>
    call<Watch>("/watch", { method: "POST", body: JSON.stringify(body) }),
  getWatch: (id: string) => call<Watch>(`/watch/${encodeURIComponent(id)}`),
};
