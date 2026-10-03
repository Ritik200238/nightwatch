/** Where a number on the report came from, in words.
 *
 *  The backend (nightwatch/pipeline/provenance.py) says which of four kinds each headline
 *  number is - live from Bitget, measured from history, assumed, or written by the AI -
 *  with the facts behind it (age, sample size, feed). This file only turns those facts
 *  into the chip text and the tooltip, in English and Chinese. */
import type { Lang } from "./i18n";
import { tr } from "./i18n";

export type ProvKind = "live" | "history" | "assumed" | "ai";

export interface ProvEntry {
  kind: ProvKind;
  source?: string;
  feed?: string;
  ts?: string | null;
  age_s?: number | null;
  mode?: string;
  stale?: boolean;
  n?: number | null;
  n_candidates?: number | null;
  n_fit?: number | null;
  n_paths?: number | null;
  unit?: string;
  horizon?: string;
  hits?: number | null;
  preset?: string;
}

export interface Provenance {
  kinds: ProvKind[];
  items: {
    exit_cost?: ProvEntry;
    loss_line?: ProvEntry;
    worst_stress?: ProvEntry;
    analog?: ProvEntry;
    monte_carlo?: ProvEntry;
    liquidation?: ProvEntry;
    size?: ProvEntry;
    analyst?: ProvEntry;
    /** One entry per stress preset id. */
    stress?: Record<string, ProvEntry>;
  };
}

/** "40s", "12 min", "3 h". */
export function ageText(s: number, lang: Lang): string {
  if (s < 90) return `${Math.round(s)}${lang === "zh" ? " 秒" : "s"}`;
  if (s < 5400) return `${Math.round(s / 60)}${lang === "zh" ? " 分钟" : " min"}`;
  return `${(s / 3600).toFixed(1)}${lang === "zh" ? " 小时" : " h"}`;
}

function sample(e: ProvEntry, lang: Lang): string | null {
  const L = tr(lang);
  if (e.n == null) return null;
  const n = e.n.toLocaleString();
  if (e.unit === "day") return L(`${n} past day`, `${n} 个历史交易日`);
  if (e.unit === "hour") return L(`${n} past hours`, `${n} 个历史小时`);
  return L(`${n} past moments`, `${n} 个历史时刻`);
}

export const KIND_NAME: Record<ProvKind, { en: string; zh: string }> = {
  live: { en: "Live", zh: "实时" },
  history: { en: "History", zh: "历史" },
  assumed: { en: "Assumed", zh: "假设" },
  ai: { en: "AI", zh: "AI" },
};

/** The one-line meaning of each kind, for the legend. */
export const KIND_MEANING: Record<ProvKind, { en: string; zh: string }> = {
  live: { en: "read from Bitget just now", zh: "刚从 Bitget 读取" },
  history: { en: "measured from past data", zh: "由历史数据测得" },
  assumed: { en: "a preset or rule, not measured", zh: "预设或规则，并非测得" },
  ai: { en: "written by the AI; moves no number", zh: "由 AI 撰写；不改变任何数字" },
};

/** Chip text: the kind plus the one fact that matters (age or sample size). */
export function chipText(e: ProvEntry, lang: Lang): string {
  const k = lang === "zh" ? KIND_NAME[e.kind].zh : KIND_NAME[e.kind].en;
  if (e.kind === "live" && e.age_s != null && e.age_s > 0) return `${k} · ${ageText(e.age_s, lang)}${e.stale ? "!" : ""}`;
  // A crash replay is one real day, not a sample of one: "n=1" would read as thin evidence.
  if (e.kind === "history" && e.unit === "day") return `${k} · ${lang === "zh" ? "真实一日" : "real day"}`;
  if (e.kind === "history" && e.n != null) return `${k} · n=${e.n.toLocaleString()}`;
  return k;
}

/** Tooltip: the exact source, timestamp and sample. */
export function detailText(e: ProvEntry, lang: Lang): string[] {
  const L = tr(lang);
  const out: string[] = [];
  if (e.kind === "live") {
    out.push(
      e.feed
        ? L(`Live from Bitget: ${e.source ?? ""} (${e.feed}).`, `来自 Bitget 实时数据：${e.source ?? ""}（${e.feed}）。`)
        : L(`Live from Bitget: ${e.source ?? ""}.`, `来自 Bitget 实时数据：${e.source ?? ""}。`),
    );
    if (e.ts) out.push(L(`Read ${new Date(e.ts).toUTCString()}${e.age_s ? `, ${ageText(e.age_s, lang)} before this verdict` : ""}.`, `读取时间 ${new Date(e.ts).toUTCString()}${e.age_s ? `，早于本结论 ${ageText(e.age_s, lang)}` : ""}。`));
    if (e.mode && e.mode !== "live") out.push(e.stale ? L("This book was older than the freshness limit and a fresh read failed; treat the cost as approximate.", "这份盘口已超过新鲜度上限，且重新读取失败；成本仅供参考。") : L("Taken from the desk's own once-a-minute recording of this book.", "取自本系统每分钟一次的盘口记录。"));
  } else if (e.kind === "history") {
    const s = sample(e, lang);
    out.push(L(`Measured from history: ${e.source ?? ""}.`, `由历史数据测得：${e.source ?? ""}。`));
    if (s) out.push(L(`Sample: ${s}${e.n_candidates ? ` retrieved from ${e.n_candidates.toLocaleString()} candidate hours` : ""}${e.horizon ? `, held ${e.horizon}` : ""}.`, `样本：${s}${e.n_candidates ? `，从 ${e.n_candidates.toLocaleString()} 个候选小时中检索` : ""}${e.horizon ? `，持有 ${e.horizon}` : ""}。`));
    if (e.n_fit) out.push(L(`The tail is calibrated on ${e.n_fit.toLocaleString()} earlier scored forecasts.`, `尾部经 ${e.n_fit.toLocaleString()} 个更早已评分的预测校准。`));
    if (e.n_paths) out.push(L(`${e.n_paths.toLocaleString()} simulated paths.`, `${e.n_paths.toLocaleString()} 条模拟路径。`));
  } else if (e.kind === "assumed") {
    out.push(L(`Assumed, not measured: ${e.source ?? "a preset or policy rule"}.`, `假设值，并非测得：${e.source ?? "预设或策略规则"}。`));
  } else {
    out.push(L("Written by the Qwen analyst after the report was finished. It cannot change a number, and any figure it quotes is checked against the report.", "由 Qwen 分析师在报告完成后撰写。它无法改变任何数字，所引用的数字都会与报告核对。"));
  }
  return out;
}
