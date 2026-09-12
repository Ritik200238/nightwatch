/** Number formatting used across the desk. One place, consistent rules. */

const usd0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function fmtUsd(v: number | null | undefined, digits: 0 | 2 = 0): string {
  if (v == null || Number.isNaN(v)) return "—";
  return (digits === 0 ? usd0 : usd2).format(v);
}

export function fmtCompact(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e6) return `${(v / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}K`;
  return usd0.format(v);
}

/** Signed percent, e.g. +1.23% / −0.45%. */
export function fmtPct(v: number | null | undefined, digits = 2, signed = true): string {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v.toFixed(digits);
  if (!signed) return `${s}%`;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}%`;
}

export function fmtBps(v: number | null | undefined, digits = 1, signed = false): string {
  if (v == null || Number.isNaN(v)) return "—";
  const s = `${Math.abs(v).toFixed(digits)} bps`;
  if (!signed) return s;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${s}`;
}

export function fmtPrice(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return usd2.format(v);
}

export function fmtHours(h: number | null | undefined): string {
  if (h == null || Number.isNaN(h)) return "—";
  if (h >= 720) return "> 30 d";
  if (h >= 48) return `${(h / 24).toFixed(1)} d`;
  return `${h.toFixed(h < 10 ? 1 : 0)} h`;
}

export function fmtRatio(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Hour-of-week buckets, as a person would say them. */
const BUCKET_LABELS: Record<string, string> = {
  us_regular: "US session",
  us_pre: "US pre-market",
  us_post: "US after-hours",
  weeknight: "Weeknight",
  friday_night: "Friday night",
  weekend: "Weekend",
  sunday_night: "Sunday night",
  holiday: "US holiday",
};

export function bucketLabel(b: string): string {
  return BUCKET_LABELS[b] ?? titleCase(b);
}
