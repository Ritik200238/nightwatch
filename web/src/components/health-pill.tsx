"use client";

import { useEffect, useState } from "react";
import { api, type Health } from "@/lib/api";
import { fmtTime } from "@/lib/format";

/** Backend liveness + data freshness, polled every 30s. */
export function HealthPill() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const h = await api.health();
        if (!cancelled) {
          setHealth(h);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "offline");
      }
    };
    void load();
    const id = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (error) {
    return (
      <span role="status" className="inline-flex shrink-0 items-center gap-2 rounded-full border border-destructive/40 px-3 py-1 text-xs whitespace-nowrap text-destructive">
        <span aria-hidden className="h-2 w-2 rounded-full bg-destructive" />
        API offline
      </span>
    );
  }
  if (!health) {
    return <span role="status" className="h-7 w-32 shrink-0 animate-pulse rounded-full bg-muted" aria-label="Checking API" />;
  }
  const warm = health.warm.state === "running" ? ` · warming ${health.warm.done}/${health.warm.total}` : "";
  return (
    <span role="status" title={`${health.tickers_with_data} tokens · last order book ${fmtTime(health.last_book_ts)}${warm}`} className="inline-flex shrink-0 items-center gap-2 rounded-full border border-border px-3 py-1 text-xs whitespace-nowrap text-muted-foreground">
      <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-status-good" />
      {/* Narrow screens keep the signal (live, N tokens) and drop the timestamp. */}
      <span className="tabular">
        {health.tickers_with_data} tokens
        <span className="hidden sm:inline">
          {" · book "}
          {fmtTime(health.last_book_ts)}
          {warm}
        </span>
      </span>
    </span>
  );
}
