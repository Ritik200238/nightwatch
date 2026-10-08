/**
 * The last good answer for a public-record page, kept in the browser.
 *
 * Why: the record pages (/calibration, /wrong, /studies ...) read slow, heavy endpoints.
 * A visitor who has been here before should see the last numbers at once and watch them
 * refresh, not stare at a loading block. Storage can be missing or full; every call here
 * fails quietly and the page works without it.
 */

const PREFIX = "nw.record.";
const MAX_CHARS = 1_500_000;

/** Paths worth remembering: reads whose answer changes slowly and is the same for everyone. */
const REMEMBERED = ["/sources", "/studies", "/calibration", "/misses", "/stop-benchmark", "/verify", "/anchors", "/usage", "/lenses", "/universe"];

export function isRemembered(path: string): boolean {
  const p = path.split("?")[0];
  // A stored report never changes once written, so a copy is as good as the original.
  return REMEMBERED.includes(p) || /^\/reports\/\d+$/.test(p);
}

export function remember(path: string, data: unknown): void {
  try {
    const s = JSON.stringify({ t: Date.now(), d: data });
    if (s.length <= MAX_CHARS) localStorage.setItem(PREFIX + path, s);
  } catch {
    /* storage full or blocked: nothing to do */
  }
}

/** The remembered answer and when it was saved, or null. */
export function recall<T>(path: string): { data: T; at: number } | null {
  try {
    const raw = localStorage.getItem(PREFIX + path);
    if (!raw) return null;
    const j = JSON.parse(raw) as { t: number; d: T };
    return typeof j.t === "number" ? { data: j.d, at: j.t } : null;
  } catch {
    return null;
  }
}
