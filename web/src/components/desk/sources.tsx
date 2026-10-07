"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";
import { useLang } from "@/lib/lang";
import { api, type DataSource } from "@/lib/api";
import { fmtTime } from "@/lib/format";

/** How stale a feed is allowed to look before its dot changes colour, per source. */
const FRESH_H: Record<string, number> = { bitget_bars: 1, yahoo: 3, nasdaq: 24, fred: 24, rss: 6, sec_edgar: 12, bitget_mcp: 3, bitget_oi: 24, cboe_options: 3 };

function ageHours(iso: string | null): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

function fmtAge(iso: string | null, zh: boolean): string {
  const h = ageHours(iso);
  if (h == null) return zh ? "从未" : "never";
  if (h < 1) return zh ? `${Math.max(1, Math.round(h * 60))} 分钟前` : `${Math.max(1, Math.round(h * 60))} min ago`;
  if (h < 48) return zh ? `${h.toFixed(h < 10 ? 1 : 0)} 小时前` : `${h.toFixed(h < 10 ? 1 : 0)} h ago`;
  return zh ? `${Math.round(h / 24)} 天前` : `${Math.round(h / 24)} d ago`;
}

/** The six feeds behind every report, with when each was last pulled. Collapsed by
 *  default: a user wants it once, a judge wants it every time. */
export function Sources() {
  const { tx, lang } = useLang();
  const zh = lang === "zh";
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
    return r.status === "unavailable" || h == null || h > (FRESH_H[r.key] ?? 24);
  }).length;

  return (
    <div>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between rounded-md text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        <span>
          <span className="text-sm font-medium">{tx("Data sources", "数据来源")}</span>{" "}
          <span className="ml-2 text-[13px] text-muted-foreground">{rows ? tx(`${rows.length} live feeds${stale ? ` · ${stale} behind` : ""}`, `${rows.length} 个实时数据源${stale ? ` · ${stale} 个滞后` : ""}`) : error ? tx("unavailable", "不可用") : tx("checking…", "检查中…")}</span>
        </span>
        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && rows ? (
        <ul className="mt-3 space-y-2">
          {rows.map((r) => {
            const h = ageHours(r.last_update);
            const ok = r.status !== "unavailable" && h != null && h <= (FRESH_H[r.key] ?? 24);
            return (
              <li key={r.key} className="border-t border-border pt-2 text-[13px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 font-medium">
                    <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${ok ? "bg-status-good" : "bg-status-warning"}`} />
                    <a href={r.url} target="_blank" rel="noreferrer" className="hover:underline">
                      {r.label}
                    </a>
                  </span>
                  <span className="tabular text-muted-foreground" title={r.last_update ? tx(`pulled ${fmtTime(r.last_update)}`, `拉取于 ${fmtTime(r.last_update)}`) : tx("never pulled", "从未拉取")}>
                    {tx("pulled ", "拉取于 ")}{fmtAge(r.last_update, zh)}
                  </span>
                </div>
                <p className="mt-1 text-muted-foreground">{r.what}</p>
                {r.used_for ? (
                  <p className="mt-1">
                    <span className="font-medium">{tx("Used for: ", "用途：")}</span>
                    {zh ? r.used_for_zh : r.used_for}
                    {r.effect ? <span className="ml-1 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{zh ? ({ "moves the size": "可改变仓位", "sets a preset": "设定情景", "raises a flag": "触发提示", "context only": "仅供参考" } as Record<string, string>)[r.effect] ?? r.effect : r.effect}</span> : null}
                  </p>
                ) : null}
                {r.status === "unavailable" ? (
                  <p className="mt-1 font-medium text-destructive">{zh ? "Bitget 美股数据：服务当前不可用，显示的是最近一次有效数据" : r.latest_label}</p>
                ) : (
                  <p className="mt-1 text-muted-foreground">
                    {r.rows.toLocaleString()} {tx("rows", "行")} · {r.cadence}
                    {r.latest ? ` · ${r.latest_label ?? tx("newest", "最新")}: ${fmtTime(r.latest)}` : ""}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      ) : open && error ? (
        <p className="mt-2 text-[13px] text-muted-foreground">{tx("Could not load the source list: ", "无法加载数据源列表：")}{error}</p>
      ) : null}
    </div>
  );
}
