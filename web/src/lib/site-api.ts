/** Server-side reads of the public API, for metadata and share images. */
const BASE = (process.env.NEXT_PUBLIC_API_URL || "https://nightwatch-gules.vercel.app/api").replace(/\/$/, "");

export async function serverGet<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${BASE}${path}`, { next: { revalidate: 3600 }, signal: AbortSignal.timeout(4000) });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

export interface ShareFacts {
  ticker: string;
  side: string;
  size: string;
  verdict: string;
}

function money(n: number): string {
  return n >= 1000 ? `$${Math.round(n / 100) / 10}k`.replace(".0k", "k") : `$${Math.round(n)}`;
}

/** The few facts a share card needs, from a stored report; null when it is gone. */
export async function shareFacts(id: string): Promise<ShareFacts | null> {
  const r = await serverGet<{ ticket?: { ticker?: string; side?: string; notional_quote?: number }; verdict?: { verdict?: string } }>(`/reports/${encodeURIComponent(id)}`);
  const t = r?.ticket;
  const v = r?.verdict?.verdict;
  if (!t?.ticker || !t.side || !v || typeof t.notional_quote !== "number") return null;
  return { ticker: t.ticker, side: t.side, size: money(t.notional_quote), verdict: v };
}
