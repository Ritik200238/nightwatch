"use client";

import { CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Histogram } from "@/components/charts/histogram";
import { api, type MissesResponse, type Report, type VerifyResponse } from "@/lib/api";
import { fmtPct, fmtUsd } from "@/lib/format";
import { presetName } from "@/lib/i18n-terms";
import { type Lang, tr } from "@/lib/i18n";

/** Loss per stress test, in USDT, as horizontal bars (worst first). Built from report.stress. */
export function StressBars({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const rows = report.stress.presets
    .map((p, i) => ({ name: p.name, v: report.stress.impacts[i]?.total_pnl_quote }))
    .filter((r): r is { name: string; v: number } => typeof r.v === "number")
    .sort((a, b) => a.v - b.v)
    .slice(0, 6);
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => Math.abs(r.v)), 1);
  return (
    <figure className="min-w-0" aria-label={L("Result of each stress test in USDT", "每个压力测试的结果（USDT）")}>
      <figcaption className="mb-1.5 text-xs font-medium text-muted-foreground">{L("Loss in each stress test (USDT)", "每个压力测试的损失（USDT）")}</figcaption>
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.name} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-2 text-xs">
            <span className="truncate text-muted-foreground" title={presetName(lang, r.name)}>
              {presetName(lang, r.name)}
            </span>
            <span className="h-2.5 rounded-sm bg-muted" aria-hidden>
              <span className={`block h-full rounded-sm ${r.v < 0 ? "bg-status-critical" : "bg-status-good"}`} style={{ width: `${Math.max(2, (Math.abs(r.v) / max) * 100)}%` }} />
            </span>
            <span className="tabular-nums">{fmtUsd(r.v)}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

/** How the nearest past moments ended, with the one-in-twenty line marked. */
export function AnalogMini({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const a = report.analog;
  const h = a?.horizons?.[report.primary_horizon];
  const c = h?.cohort;
  if (!a || !h || !c || c.insufficient) {
    return <p className="text-xs text-muted-foreground">{L("Not enough distinct past moments to draw how they ended.", "互不相同的历史时刻太少，无法绘制结果分布。")}</p>;
  }
  const values = (a.matches_outcomes ?? []).map((m) => m.outcomes[report.primary_horizon]?.ret_pct).filter((x): x is number => typeof x === "number");
  if (!values.length) return null;
  const short = report.ticket.side === "short";
  // The chart is the token's move; a short is hurt by the upper tail.
  const line = short ? (h.p95_adjusted ?? c.p95) : (h.p5_adjusted ?? c.p5);
  const loss = h.loss_p5_pct ?? line;
  return (
    <figure className="min-w-0" aria-label={L("How the most similar past moments ended", "最相似的历史时刻最终如何")}>
      <figcaption className="text-xs font-medium text-muted-foreground">
        {L(`How ${a.result.matches.length} similar past moments ended (${report.primary_horizon})`, `${a.result.matches.length} 个相似历史时刻的结果（${report.primary_horizon}）`)}
      </figcaption>
      <Histogram
        values={values}
        markers={line != null ? [{ value: line, label: L("1 in 20", "二十分之一") }] : []}
        binCount={16}
        height={130}
        lang={lang}
        ariaLabel={L("Outcome distribution of similar past moments with the one-in-twenty line", "相似历史时刻的结果分布及二十分之一线")}
      />
      <p className="text-xs text-muted-foreground">{L(`One in twenty ended worse than ${fmtPct(loss, 1)}.`, `二十次里有一次比 ${fmtPct(loss, 1)} 更差。`)}</p>
    </figure>
  );
}

function secs(a: string | null | undefined, b: string): number | null {
  if (!a) return null;
  const d = (new Date(b).getTime() - new Date(a).getTime()) / 1000;
  return Number.isFinite(d) ? Math.max(0, Math.round(d)) : null;
}

function ms(v: number | undefined): string {
  return typeof v === "number" ? ` · ${v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`}` : "";
}

/** The tool calls behind the answer, read off the report's own fields. */
export function BuildTrace({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const tm = report.timings_ms ?? {};
  const bookTs = report.execution.book_ts ?? report.execution.exit_quote?.book_ts;
  const age = secs(bookTs, report.as_of);
  const a = report.analog;
  const items: { key: string; label: string }[] = [];
  if (report.execution.exit_quote || bookTs) {
    items.push({ key: "book", label: `${L("Bitget order book", "Bitget 订单簿")} (${report.execution.book_source}${age != null ? `, ${age}s ${L("old", "前")}` : ""})${ms(tm.book)}` });
  }
  items.push({ key: "candles", label: `${L("Bitget candles + features", "Bitget K 线与特征")} (${L("bar", "K 线")} ${(report.snapshot.bar_ts ?? "").slice(0, 16).replace("T", " ")})${ms(tm.snapshot)}` });
  if (report.street) items.push({ key: "street", label: `${L("Bitget US-stock MCP", "Bitget 美股 MCP")}${ms(tm.street)}` });
  if (report.signal) items.push({ key: "signal", label: `${L("bitget-signal skill", "bitget-signal 技能")} (${L("agrees with our RSI", "与自算 RSI 一致")})` });
  if (a) items.push({ key: "analog", label: `${L("Analog search", "相似时刻检索")} (${a.result.matches.length} ${L("of", "/")} ${(a.result.n_candidates ?? 0).toLocaleString()} ${L("hours", "小时")})${ms(tm.analog)}` });
  items.push({ key: "stress", label: `${report.stress.presets.length} ${L("stress presets", "个压力预设")}${ms(tm.stress)}` });
  return (
    <div className="mt-4 rounded-lg border border-border bg-muted/20 px-3 py-2">
      <p className="mb-1 text-xs font-medium text-muted-foreground">{L("How this answer was built", "这个答案是怎么得出的")}</p>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {items.map((i) => (
          <li key={i.key} className="flex items-center gap-1">
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-status-good" aria-hidden />
            <span>{i.label}</span>
          </li>
        ))}
        <QwenItem report={report} lang={lang} />
      </ul>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {L("Built from this report's own fields", "依据本报告自身的字段生成")}
        {tm.total != null ? L(` · ${tm.total} ms in total`, ` · 总计 ${tm.total} 毫秒`) : ""}
      </p>
    </div>
  );
}

/** The analyst's take arrives a few seconds after the report; read its status, never start it. */
function QwenItem({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const id = report.forecast_id;
  const [done, setDone] = useState<boolean | null>(null);
  useEffect(() => {
    if (id == null || id <= 0) return;
    let stop = false;
    void (async () => {
      for (let i = 0; i < 12 && !stop; i++) {
        try {
          const t = await api.analystGet(id, lang);
          if (stop) return;
          if (t.status === "done") return setDone(true);
          if (t.status !== "pending") return setDone(false);
        } catch {
          return;
        }
        await new Promise((r) => setTimeout(r, 3000));
      }
    })();
    return () => {
      stop = true;
    };
  }, [id, lang]);
  if (id == null || id <= 0 || done === false) return null;
  return (
    <li className="flex items-center gap-1">
      {done ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-status-good" aria-hidden /> : <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden />}
      <span>{done ? L("Qwen analyst", "Qwen 分析师") : L("Qwen analyst writing…", "Qwen 分析师撰写中…")}</span>
    </li>
  );
}

type Record_ = { misses: MissesResponse | null; verify: VerifyResponse | null };
let recordCache: Promise<Record_> | null = null;
function loadRecord(): Promise<Record_> {
  recordCache ??= Promise.all([api.misses().catch(() => null), api.verify().catch(() => null)]).then(([misses, verify]) => ({ misses, verify }));
  return recordCache;
}

/** The live scoreboard in one line, fetched once per page load. */
export function CredStrip({ lang }: { lang: Lang }) {
  const L = tr(lang);
  const [rec, setRec] = useState<Record_ | null>(null);
  useEffect(() => {
    let alive = true;
    void loadRecord().then((r) => alive && setRec(r));
    return () => {
      alive = false;
    };
  }, []);
  const tk = rec?.misses?.totals?.ticket;
  if (!tk || !tk.scored) return null;
  const target = rec?.misses?.target_rate ?? 0.05;
  const rate = (tk.rate ?? 0) * 100;
  return (
    <p className="mt-2 text-xs text-muted-foreground">
      <Link href="/wrong" className="underline underline-offset-2 hover:text-foreground">
        {L(
          `Live record: ${tk.scored.toLocaleString()} verdicts scored, ${rate.toFixed(0)}% went past their 1-in-20 line (target ${(target * 100).toFixed(0)}%)`,
          `实时记录：已评分 ${tk.scored.toLocaleString()} 个结论，${rate.toFixed(0)}% 越过了各自的二十分之一线（目标 ${(target * 100).toFixed(0)}%）`,
        )}
        {rec?.verify?.ok ? L(" · receipts verified", " · 回执已校验") : ""}
      </Link>
    </p>
  );
}
