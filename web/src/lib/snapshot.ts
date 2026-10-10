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

/** Should a live answer be replaced by the snapshot? Only when the backend is unreachable:
 *  a network error or timeout (null), or the gateway statuses a down or restarting server
 *  produces (502, 503, 504). A plain 500 is a bug in the desk, not an outage: showing a saved
 *  example of a different trade in its place hid two real bugs and misled the visitor, so a
 *  500 now reaches the page as an error. */
export function shouldFallback(status: number | null): boolean {
  return status === null || status === 502 || status === 503 || status === 504;
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

/** True for an answer the proxy served from its saved copy. Such an answer is never a result.
 *
 *  It is decided by the answer's own body, never by the shared `snapshotFlag`. That flag is
 *  set by whichever read last fell back to a saved copy, so an unrelated slow GET could set
 *  it while a live analysis was running, and the live answer was then thrown away as "not an
 *  answer to your trade". The proxy builds every saved chat answer with `snapshotPost`, which
 *  always marks `intent.kind` as "snapshot", and a streamed answer is never served from the
 *  saved copy at all. */
export function isSnapshotAnswer(res: { intent?: { kind?: string } | null }): boolean {
  return res.intent?.kind === "snapshot";
}

// Which parsed answers the proxy served from its saved copy, and from when. The shared flag
// below says only that some read fell back most recently; this says whether *this* answer did,
// so a page that holds one answer never takes an unrelated read's fallback for its own.
const savedCopies = new WeakMap<object, string>();

/** Remember that `data` (a parsed response body) came from the saved copy dated `iso`. A live
 *  answer, or one with no object body, is left unmarked. Returns `data` unchanged. */
export function markSavedCopy<T>(data: T, iso: string | null): T {
  if (iso && data !== null && typeof data === "object") savedCopies.set(data as object, iso);
  return data;
}

/** When this very answer's saved copy is from, or null for a live answer. */
export function savedCopyAt(data: unknown): string | null {
  return data !== null && typeof data === "object" ? (savedCopies.get(data as object) ?? null) : null;
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

/** What a /health reply means for liveness. A reply the proxy served from its saved copy is
 *  never "up": the box did not answer, so the page says it is down and when the copy is from. */
export type HealthVerdict = { state: "up" | "slow" } | { state: "down"; savedAt?: string };

export function classifyHealth(ok: boolean, headerIso: string | null, elapsedMs: number, slowAfterMs = 3_000): HealthVerdict {
  if (headerIso) return { state: "down", savedAt: headerIso };
  if (!ok) return { state: "down" };
  return { state: elapsedMs > slowAfterMs ? "slow" : "up" };
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
