"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type DataSource } from "@/lib/api";
import { fmtTime } from "@/lib/format";

/** How stale a feed is allowed to look before its dot changes colour, per source. */
const FRESH_H: Record<string, number> = { bitget_bars: 1, yahoo: 3, nasdaq: 24, fred: 24, rss: 6, sec_edgar: 12 };

function ageHours(iso: string | null): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

function fmtAge(iso: string | null): string {
  const h = ageHours(iso);
  if (h == null) return "never";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min ago`;
  if (h < 48) return `${h.toFixed(h < 10 ? 1 : 0)} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

/** The six feeds behind every report, with when each was last pulled. Collapsed by
 *  default: a user wants it once, a judge wants it every time. */
export function Sources() {
  const [rows, setRows] = useState<DataSource[] | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await api.sources();
        if (!cancelled) {
          setRows(r);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "unavailable");
      }
    };
    void load();
    const id = setInterval(load, 120_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const stale = rows?.filter((r) => {
    const h = ageHours(r.last_update);
    return h == null || h > (FRESH_H[r.key] ?? 24);
  }).length;

  return (
    <div>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between rounded-md text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        <span>
          <span className="text-sm font-medium">Data sources</span>{" "}
          <span className="ml-2 text-xs text-muted-foreground">{rows ? `${rows.length} live feeds${stale ? ` · ${stale} behind` : ""}` : error ? "unavailable" : "checking…"}</span>
        </span>
        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && rows ? (
        <ul className="mt-3 space-y-2">
          {rows.map((r) => {
            const h = ageHours(r.last_update);
            const ok = h != null && h <= (FRESH_H[r.key] ?? 24);
            return (
              <li key={r.key} className="rounded-lg border border-border bg-background/40 px-3 py-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 font-medium">
                    <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${ok ? "bg-status-good" : "bg-status-warning"}`} />
                    <a href={r.url} target="_blank" rel="noreferrer" className="hover:underline">
                      {r.label}
                    </a>
                  </span>
                  <span className="tabular text-muted-foreground" title={r.last_update ? `pulled ${fmtTime(r.last_update)}` : "never pulled"}>
                    pulled {fmtAge(r.last_update)}
                  </span>
                </div>
                <p className="mt-1 text-muted-foreground">{r.what}</p>
                <p className="mt-1 text-muted-foreground">
                  {r.rows.toLocaleString()} rows · {r.cadence}
                  {r.latest ? ` · ${r.latest_label ?? "newest"}: ${fmtTime(r.latest)}` : ""}
                </p>
              </li>
            );
          })}
        </ul>
      ) : open && error ? (
        <p className="mt-2 text-xs text-muted-foreground">Could not load the source list: {error}</p>
      ) : null}
    </div>
  );
}
