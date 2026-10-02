/**
 * Saved-snapshot fallback, kept pure so it can be tested without a server.
 *
 * Why: if the API box is down, a judge should see the last good answers and a plain
 * notice, never an error. The proxy serves these when the live backend cannot answer;
 * the client reads the header it sets and shows a banner.
 */

export const SNAPSHOT_HEADER = "x-nightwatch-snapshot";

export interface SnapshotData {
  generated_at: string;
  gets: Record<string, unknown>;
  reports: Record<string, Record<string, unknown>>;
}

/** Stable key for a GET: path plus query params sorted, so ?b=1&a=2 equals ?a=2&b=1. */
export function snapshotKey(path: string, search = ""): string {
  const p = new URLSearchParams(search.replace(/^\?/, ""));
  // The anonymous visitor id and language ride along on every call; they do not change the
  // answer, and kept in the key no browser request ever matched a saved one.
  const sorted = [...p.entries()].filter(([k]) => !k.startsWith("nw_")).sort(([a], [b]) => a.localeCompare(b));
  const q = new URLSearchParams(sorted).toString();
  return `/${path.replace(/^\/+|\/+$/g, "")}${q ? `?${q}` : ""}`;
}

/** Should a live answer be replaced by the snapshot? Network error (null), or 5xx. */
export function shouldFallback(status: number | null): boolean {
  return status === null || status >= 500;
}

/** Pick the demo report the text names (TSLA, NVDA, AAPL...), else TSLA. */
export function pickReport(data: SnapshotData, text: string): Record<string, unknown> | null {
  const names = Object.keys(data.reports);
  const upper = text.toUpperCase();
  const hit = names.find((t) => new RegExp(`(^|[^A-Z0-9])${t}([^A-Z0-9]|$)`).test(upper));
  return data.reports[hit ?? "TSLA"] ?? data.reports[names[0]] ?? null;
}

export function snapshotNotice(iso: string): string {
  return `The live server is unreachable right now; this is a saved example from ${iso}, not an answer to your trade.`;
}

const ISO_TIME = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?/g;

/** An ISO time as a person reads it, in their locale; the text unchanged if it is not a date. */
export function readableTime(iso: string, locale?: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

/** The first ISO time in a sentence, or "" when there is none. */
export function isoIn(text: string): string {
  return text.match(ISO_TIME)?.[0] ?? "";
}

/** Every ISO timestamp in a sentence, rewritten as a readable time in the reader's locale. */
export function readableTimes(text: string, locale?: string): string {
  return text.replace(ISO_TIME, (m) => readableTime(m, locale));
}

/** The notice shown in the chat for a saved answer, in the reader's language. */
export function snapshotNoticeFor(iso: string, lang: "en" | "zh"): string {
  const when = readableTime(iso, lang === "zh" ? "zh-CN" : undefined);
  return lang === "zh"
    ? `实时服务器暂时无法连接；下面是保存于 ${when} 的示例，不是对你这笔交易的回答。`
    : `The live server is unreachable right now; the example is a saved one from ${when}, not an answer to your trade.`;
}

/** True for an answer the proxy served from its saved copy. Such an answer is never a result. */
export function isSnapshotAnswer(res: { intent?: { kind?: string } | null }, headerIso: string | null): boolean {
  return res.intent?.kind === "snapshot" || headerIso !== null;
}

/** Body for a POST /chat or /analyze served from the snapshot, or null if none saved. */
export function snapshotPost(data: SnapshotData | null, path: string, requestBody: string): unknown | null {
  if (!data) return null;
  let parsed: { ticker?: string; messages?: { role: string; content: string }[] } = {};
  try {
    parsed = JSON.parse(requestBody || "{}");
  } catch {
    /* fall through to the default report */
  }
  if (path === "analyze") return pickReport(data, parsed.ticker ?? "");
  if (path === "chat") {
    const last = [...(parsed.messages ?? [])].reverse().find((m) => m.role === "user")?.content ?? "";
    const report = pickReport(data, last);
    if (!report) return null;
    const reply = snapshotNotice(data.generated_at);
    return {
      intent: { kind: "snapshot", missing_fields: [], reply },
      ticket: null,
      report,
      narrative: null,
      report_text: null,
      unverified_numbers: [],
      reply,
      mode: "rules",
    };
  }
  return null;
}

/** Body for a GET served from the snapshot, or null if that path was not saved. */
export function snapshotGet(data: SnapshotData | null, path: string, search: string): unknown | null {
  if (!data) return null;
  const v = data.gets[snapshotKey(path, search)];
  return v === undefined ? null : v;
}

// Client-side flag: set by api.ts when a response carries the header, read by the banner.
let current: string | null = null;
const listeners = new Set<() => void>();
export const snapshotFlag = {
  get: () => current,
  set(iso: string | null) {
    if (iso === current) return;
    current = iso;
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void) {
    listeners.add(l);
    return () => void listeners.delete(l);
  },
};
