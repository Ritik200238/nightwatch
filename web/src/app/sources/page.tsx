"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, api, peek, type DataSource } from "@/lib/api";
import { fmtAge, isFresh, sourceAgeIso } from "@/lib/freshness";
import { LoadingRecord, PageHead, PROOF_STACK, PROOF_WIDTH, RecordError } from "@/components/proof-page";
import { useLang } from "@/lib/lang";
import { localLatest, localSource } from "@/lib/source-zh";
import { ChevronDown } from "lucide-react";

/** What the strongest thing a feed can do to an answer is called, in Chinese. */
const EFFECT_ZH: Record<string, string> = { "moves the size": "可改变仓位", "sets a preset": "设定情景", "raises a flag": "触发提示", "context only": "仅供参考" };

function isBitgetCatalogueFeed(raw: DataSource): boolean {
  return raw.key === "bitget_mcp" || raw.key.startsWith("bitget_equity_") || raw.key.startsWith("bitget_sentiment_");
}

/** Every feed behind a report: what it is, how often it is pulled, when it last was. */
export default function SourcesPage() {
  const { tx, lang } = useLang();
  const zh = lang === "zh";
  const [rows, setRows] = useState<DataSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setError(null);
    const c = peek<DataSource[]>("/sources");
    if (c) setRows(c);
    void api
      .sources()
      .then((r) => live && setRows(r))
      .catch((e) => live && setError(e instanceof ApiError ? e.message : tx("The server did not answer.", "服务器没有响应。")));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  const { staleCatalogue, normalRows } = useMemo(() => {
    if (!rows) return { staleCatalogue: [], normalRows: [] };
    const stale: DataSource[] = [];
    const normal: DataSource[] = [];
    for (const r of rows) {
      if (isBitgetCatalogueFeed(r) && !isFresh(r)) {
        stale.push(r);
      } else {
        normal.push(r);
      }
    }
    // Only group if there are multiple stale catalogue feeds
    if (stale.length > 1) {
      return { staleCatalogue: stale, normalRows: normal };
    }
    return { staleCatalogue: [], normalRows: rows };
  }, [rows]);

  return (
    <div className={`${PROOF_WIDTH} ${PROOF_STACK}`}>
      <PageHead title={tx("Data sources", "数据来源")} intro={tx("Every number in a report comes from one of these feeds. Nothing is typed in by hand.", "报告里的每个数字都来自下面这些数据源，没有任何手工填写。")} />
      {error && !rows ? <RecordError message={error} onRetry={() => setAttempt((n) => n + 1)} /> : null}
      {error && rows ? (
        <p role="status" className="text-sm text-muted-foreground">
          {tx("Could not refresh just now; showing the last saved list. ", "刚才无法刷新，显示的是上次保存的列表。")}
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className="inline-flex min-h-10 items-center px-2 underline underline-offset-2">
            {tx("Try again", "重试")}
          </button>
        </p>
      ) : null}
      {!rows && !error ? <LoadingRecord blocks={[88, 88, 88]} onRetry={() => setAttempt((n) => n + 1)} /> : null}
      <ul className="grid grid-cols-1 divide-y divide-border border-y border-border md:grid-cols-2 md:gap-x-12 md:divide-y-0">
        {staleCatalogue.length > 0 ? (
          <li className="py-5 border-b border-border/60 col-span-1 md:col-span-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="flex items-center gap-2 text-sm font-semibold">
                <span aria-hidden className="h-2 w-2 rounded-full bg-amber-500" />
                <span>{tx("Bitget US-stock catalogue feeds", "Bitget 美股数据目录")}</span>
              </p>
              <p className="t-caption">
                <span className="text-amber-500 font-medium">{tx("upstream HTTP 503", "上游 HTTP 503")}</span> · {tx("degraded fallback active", "已启用降级缓存")}
              </p>
            </div>
            <p className="t-body mt-1 max-w-prose text-muted-foreground">
              {tx(
                "Bitget MCP test-environment catalogue endpoint returned HTTP 503 since Oct 5. Cached snapshot fallback is active so the desk continues operating safely. 10 catalogue feeds share this upstream dependency.",
                "Bitget 测试环境 MCP 目录端点自 10 月 5 日起返回 HTTP 503。系统已启用快照缓存降级回退，交易台保持安全运行。共有 10 个数据源共享此上游依赖。"
              )}
            </p>
            <details className="group mt-3">
              <summary className="inline-flex min-h-10 cursor-pointer items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
                <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                <span>
                  {tx(
                    `Show all ${staleCatalogue.length} affected feeds`,
                    `显示全部 ${staleCatalogue.length} 个受影响的数据源`
                  )}
                </span>
              </summary>
              <ul className="mt-3 grid grid-cols-1 gap-4 divide-y divide-border/40 border-t border-border/40 pt-3 md:grid-cols-2 md:divide-y-0">
                {staleCatalogue.map((raw) => {
                  const r = { ...localSource(raw, zh), latest_label: localLatest(raw.latest_label, zh) };
                  return (
                    <li key={r.key} className="pt-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noreferrer"
                          className="font-medium underline underline-offset-2 hover:text-foreground min-h-10 inline-flex items-center"
                        >
                          {r.label}
                        </a>
                        <span className="t-caption text-muted-foreground">{r.cadence}</span>
                      </div>
                      <p className="mt-0.5 text-muted-foreground">{r.what}</p>
                    </li>
                  );
                })}
              </ul>
            </details>
          </li>
        ) : null}
        {normalRows.map((raw) => {
          const fresh = isFresh(raw);
          const r = { ...localSource(raw, zh), latest_label: localLatest(raw.latest_label, zh) };
          return (
            <li key={r.key} className="py-5 md:border-b md:border-border/60">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="flex items-center gap-2 text-sm font-semibold">
                  <span aria-hidden className={`h-2 w-2 rounded-full ${fresh ? "bg-emerald-500" : "bg-amber-500"}`} />
                  <a href={r.url} target="_blank" rel="noreferrer" className="-my-2.5 inline-flex min-h-10 min-w-10 items-center underline-offset-2 hover:underline">
                    {r.label}
                  </a>
                </p>
                <p className="t-caption">
                  {fresh ? tx("fresh", "正常") : tx("stale", "过期")} · {tx("updated", "更新于")} {fmtAge(sourceAgeIso(r), zh)}
                </p>
              </div>
              <p className="t-body mt-1 max-w-prose text-muted-foreground">{r.what}</p>
              {r.used_for ? (
                <p className="t-body mt-1 max-w-prose">
                  <span className="font-medium">{tx("Used for: ", "用途：")}</span>
                  {zh ? r.used_for_zh || r.used_for : r.used_for}
                  {r.effect ? <span className="t-caption ml-2">{zh ? EFFECT_ZH[r.effect] ?? r.effect : r.effect}</span> : null}
                </p>
              ) : null}
              <p className="t-caption mt-1">
                {tx("Pulled", "频率")}: {r.cadence} · {r.rows.toLocaleString()} {tx("rows", "行")}
                {r.latest_label ? ` · ${r.latest_label}` : ""}
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
