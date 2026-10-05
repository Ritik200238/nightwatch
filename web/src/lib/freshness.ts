import type { DataSource } from "./api";

/** How old a feed may be before it is called stale, per source key (hours). */
export const FRESH_H: Record<string, number> = { bitget_bars: 1, yahoo: 3, nasdaq: 24, fred: 24, rss: 6, sec_edgar: 12, bitget_mcp: 3, bitget_signal: 3, bitget_oi: 24, cboe_options: 3 };

export function ageHours(iso: string | null | undefined): number | null {
  return iso ? (Date.now() - new Date(iso).getTime()) / 3_600_000 : null;
}

export function fmtAge(iso: string | null | undefined, zh: boolean): string {
  const h = ageHours(iso);
  if (h == null) return zh ? "从未" : "never";
  if (h < 1) return zh ? `${Math.max(1, Math.round(h * 60))} 分钟前` : `${Math.max(1, Math.round(h * 60))} min ago`;
  if (h < 48) return zh ? `${h.toFixed(h < 10 ? 1 : 0)} 小时前` : `${h.toFixed(h < 10 ? 1 : 0)} h ago`;
  return zh ? `${Math.round(h / 24)} 天前` : `${Math.round(h / 24)} d ago`;
}

/** The Bitget order-book feed is judged by its newest book, not by the last candle pull. */
export function sourceAgeIso(r: DataSource): string | null {
  return r.key === "bitget_bars" ? (r.latest ?? r.last_update) : r.last_update;
}

export function isFresh(r: DataSource): boolean {
  if (r.status === "unavailable") return false; // a cache that is still warm is not a feed that is up
  const h = ageHours(sourceAgeIso(r));
  return h != null && h <= (FRESH_H[r.key] ?? 24);
}
