"use client";

import type { ReactNode } from "react";
import { Histogram } from "@/components/charts/histogram";
import { fmtPct, fmtRatio, fmtUsd } from "@/lib/format";
import { presetName } from "@/lib/i18n-terms";
import { fmtDateL, fmtHoursL, type Lang, STRINGS, t as tl, tr } from "@/lib/i18n";
import { plainReason } from "@/lib/plain";
import type { Report } from "@/lib/api";

/** The three steps the verdict is built from, always open, directly under the verdict:
 *  similar past moments, what happened after them, the stress tests, then which of them
 *  set the verdict. Every number is a field of the report; nothing is computed from
 *  outside it. */

const words = (lang: Lang, fs?: string[]) =>
  (fs ?? []).map((f) => STRINGS[lang].feature[f] ?? STRINGS.en.feature[f] ?? f.replace(/_/g, " ")).join(lang === "zh" ? "、" : ", ");

type Driver = 0 | 1 | 2 | 3; // 0 = the account and plan rules, not one of the three steps

/** Which step set the verdict, from the gate's non-passing rules and the binding cap. */
function whoDecided(report: Report): { step: Driver; en: string; zh: string } {
  const v = report.verdict;
  const analogBasis = /analog/i.test(report.gate.risk_basis ?? "");
  const stepOf = (name: string): Driver => {
    const k = name.replace(/ /g, "_");
    if (k === "stress" || k === "exit_liquidity" || k === "liquidation") return 3;
    if (k === "risk_budget") return analogBasis ? 2 : 0;
    return 0;
  };
  const failing = report.gate.rules.filter((r) => r.decision !== "GO");
  if ((v.verdict === "NO_GO" || v.verdict === "REVIEW") && failing.length) {
    const r = failing.find((x) => x.decision === "NO_GO") ?? failing[0];
    const step = stepOf(r.rule);
    return { step, en: plainReason(`${r.rule}: ${r.reason}`, "en"), zh: plainReason(`${r.rule}: ${r.reason}`, "zh") };
  }
  const cap = report.sizing.caps.find((c) => c.name === report.sizing.binding_cap);
  if (cap && cap.notional != null && cap.notional < report.ticket.notional_quote - 1) {
    const step = stepOf(cap.name);
    const label = tl("en", "cap", cap.name);
    return { step, en: `${label} limit holds the size at ${fmtUsd(cap.notional)}`, zh: `${tl("zh", "cap", cap.name)}上限把仓位限制在 ${fmtUsd(cap.notional)}` };
  }
  return { step: 0, en: "no limit cut the size", zh: "没有任何上限削减仓位" };
}

function StepCard({ n, title, active, children, lang }: { n: 1 | 2 | 3; title: string; active: boolean; children: ReactNode; lang: Lang }) {
  return (
    <li className={`min-w-0 rounded-lg border px-3 py-3 ${active ? "border-primary bg-primary/5" : "border-border bg-muted/20"}`}>
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary text-xs font-bold text-primary-foreground" aria-hidden>
          {n}
        </span>
        <span className="sr-only">{lang === "zh" ? `第 ${n} 步：` : `Step ${n}: `}</span>
        {title}
      </h3>
      <div className="space-y-2 text-[13px] leading-relaxed">{children}</div>
    </li>
  );
}

export function ThreeSteps({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const t = report.ticket;
  const a = report.analog;
  const primary = a?.horizons?.[report.primary_horizon];
  const cohort = primary?.cohort;
  const decided = whoDecided(report);
  const verdictName = report.verdict.verdict === "REVIEW" ? tl(lang, "verdictName", "REVIEW") : tl(lang, "verdictName", report.verdict.verdict);

  // Step 1 -------------------------------------------------------------------
  const matches = a?.result.ok ? a.result.matches : [];
  const times = matches.map((m) => new Date(m.ts).getTime()).filter((x) => Number.isFinite(x));
  const earliest = times.length ? new Date(Math.min(...times)).toISOString() : null;
  const latest = times.length ? new Date(Math.max(...times)).toISOString() : null;
  const spanDays = times.length ? Math.round((Math.max(...times) - Math.min(...times)) / 86_400_000) : 0;
  const closest = [...matches].sort((x, y) => y.similarity - x.similarity).slice(0, 3);
  const side = t.side === "short" ? L("short", "做空") : L("long", "做多");
  const label = typeof t.extra?.horizon_label === "string" ? t.extra.horizon_label : null;
  const hold = label ? `${label} (${Math.round(report.horizon_h)} h)` : fmtHoursL(report.horizon_h, lang);
  const said = `${side} ${Math.round(t.notional_quote).toLocaleString("en-US")} ${t.ticker}, ${hold}`;
  const by = report.read_by?.parsed_by;
  const modelName = by && by !== "rules" ? by.charAt(0).toUpperCase() + by.slice(1) : null;
  const lens = a?.lens;
  const wk = a?.weekend_hold;
  const lensLine = (() => {
    if (!lens || lens.names.length === 0) return L("Lens: none, every kind of moment counts", "筛选条件：无，所有类型的时刻都参与比较");
    if (!lens.applied) return `${L("Lens asked for but not applied: ", "已请求筛选但未能应用：")}${(lang === "zh" && lens.refused_zh) || lens.refused}`;
    const who = lens.auto ? L("chosen by the desk", "由系统自动选择") : modelName ? L(`chosen by ${modelName} from your wording`, `由 ${modelName} 根据你的措辞选择`) : L("chosen by you", "由你指定");
    return `${L("Lens: ", "筛选条件：")}${lang === "zh" && lens.description_zh ? lens.description_zh : lens.description} (${who})`;
  })();

  // Step 2 -------------------------------------------------------------------
  const short = t.side === "short";
  const values = (a?.matches_outcomes ?? []).map((m) => m.outcomes[report.primary_horizon]?.ret_pct).filter((x): x is number => typeof x === "number");
  const tail = primary ? (short ? (primary.p95_adjusted ?? cohort?.p95) : (primary.p5_adjusted ?? cohort?.p5)) : null;
  const loss = primary?.loss_p5_pct ?? tail ?? null;
  const median = primary?.pnl_median_pct ?? (cohort?.median_pct != null ? (short ? -cohort.median_pct : cohort.median_pct) : null);
  const waySide = primary?.pnl_win_rate ?? (cohort?.win_rate != null ? (short ? 1 - cohort.win_rate : cohort.win_rate) : null);

  // Step 3 -------------------------------------------------------------------
  const rows = report.stress.presets
    .map((p, i) => ({ p, v: report.stress.impacts[i]?.total_pnl_quote }))
    .filter((r): r is { p: (typeof report.stress.presets)[number]; v: number } => typeof r.v === "number")
    .sort((x, y) => x.v - y.v);
  const worst = rows.slice(0, 3);
  const windows = Math.max(...report.stress.presets.map((p) => Number(p.calibration?.closed_windows ?? 1)), 1);

  return (
    <section aria-label={L("The three steps behind this verdict", "这个结论背后的三个步骤")} className="rounded-xl border border-border bg-card px-3 py-3 sm:px-4">
      <p className="mb-2 text-sm font-semibold">
        {L("How this verdict was built", "这个结论是怎么得出的")}
        <span className="ml-2 font-normal text-muted-foreground">{L("Step 1 → Step 2 → Step 3 → Verdict", "第 1 步 → 第 2 步 → 第 3 步 → 结论")}</span>
      </p>
      <ol className="grid gap-3 lg:grid-cols-3">
        <StepCard lang={lang} n={1} title={L("Similar past moments", "相似的历史时刻")} active={false}>
          <p>
            <span className="font-medium">{modelName ? L(`Read by ${modelName}: `, `由 ${modelName} 解读：`) : by === "rules" ? L("Read by rules (no model needed): ", "由规则解读（无需模型）：") : L("Read as: ", "解读为：")}</span>
            {said}
          </p>
          <p className="text-muted-foreground">{lensLine}</p>
          {matches.length ? (
            <>
              <p>
                <span className="tabular font-semibold">{matches.length}</span> {L("similar moments", "个相似时刻")}
                {earliest ? ` · ${L("from ", "自 ")}${fmtDateL(earliest, lang)} ${L("to", "至")} ${fmtDateL(latest, lang)} (${spanDays} ${L("days back", "天")}${a?.result.n_weeks ? `, ${a.result.n_weeks} ${L("separate weeks", "个不同的周")}` : ""})` : ""}
              </p>
              {wk?.applies && wk.k_weekend != null ? (
                <p className="text-muted-foreground">
                  {L(`${wk.k_weekend} of ${wk.n_matches} were weekend holds`, `${wk.n_matches} 个里有 ${wk.k_weekend} 个是周末持有`)}
                  {wk.restricted ? L(" (matched on purpose to holds that crossed a weekend)", "（有意只与跨周末的持有对比）") : L(" (too few past weekend holds to restrict to them)", "（跨周末的历史持有太少，未作限制）")}
                </p>
              ) : null}
              <ul className="space-y-1">
                {closest.map((m) => (
                  <li key={`${m.ticker}-${m.ts}`} className="flex flex-wrap items-baseline gap-x-2 border-t border-border/60 pt-1">
                    <span className="tabular font-medium">{fmtDateL(m.ts, lang)}</span>
                    {m.ticker !== t.ticker ? <span className="text-muted-foreground">{m.ticker}</span> : null}
                    <span className="tabular text-muted-foreground">{L("similarity ", "相似度 ")}{fmtRatio(m.similarity)}</span>
                    {m.alike_on?.length ? <span className="w-full text-muted-foreground">{L("shares ", "共同点：")}{words(lang, m.alike_on)}</span> : null}
                  </li>
                ))}
              </ul>
              {a?.result.broad_features?.length ? (
                <p className="text-xs text-muted-foreground">
                  {L(`Not counted as a reason: ${words(lang, a.result.broad_features)} barely move within a week.`, `不作为相似理由：${words(lang, a.result.broad_features)} 在一周内几乎不变。`)}
                </p>
              ) : null}
            </>
          ) : (
            <p className="text-muted-foreground">{L("Not enough separate past moments to rely on.", "互不相同的历史时刻太少，无法依赖。")}</p>
          )}
        </StepCard>

        <StepCard lang={lang} n={2} title={L("What happened after", "之后发生了什么")} active={decided.step === 2}>
          {cohort && !cohort.insufficient ? (
            <>
              <p>
                {L("Median ", "中位数 ")}
                <span className="tabular font-semibold">{fmtPct(median, 1)}</span> · {L("one in twenty ended worse than ", "二十次里有一次比 ")}
                <span className="tabular font-semibold">{fmtPct(loss, 1)}</span>
                {L("", " 更差")} · n = <span className="tabular">{cohort.n}</span>
              </p>
              <p>
                <span className="tabular font-semibold">{fmtRatio(waySide)}</span> {L(`went the way your ${t.side} wanted`, `朝你的${t.side === "short" ? "空" : "多"}头方向走`)}
              </p>
              {values.length ? (
                <Histogram
                  values={values}
                  markers={tail != null ? [{ value: tail, label: L("1 in 20", "二十分之一") }] : []}
                  binCount={12}
                  height={96}
                  lang={lang}
                  ariaLabel={L("How the similar past moments ended, with the one-in-twenty line", "相似历史时刻的结果及二十分之一线")}
                />
              ) : null}
            </>
          ) : (
            <p className="text-muted-foreground">{L("Too few matured past moments to draw a distribution.", "已有结果的历史时刻太少，无法画出分布。")}</p>
          )}
        </StepCard>

        <StepCard lang={lang} n={3} title={L("Stress tests", "压力测试")} active={decided.step === 3}>
          <p>
            <span className="tabular font-semibold">{report.stress.presets.length}</span> {L("presets run on your size", "个预设情景按你的仓位运行")}
            {windows > 1 ? L(`; gaps span the ${windows} closed windows in your hold`, `；跳空按持有期内的 ${windows} 个休市时段计算`) : ""}
          </p>
          <ul className="space-y-1">
            {worst.map((r) => (
              <li key={r.p.id} className="flex items-baseline justify-between gap-2 border-t border-border/60 pt-1">
                <span className="min-w-0 break-words">{presetName(lang, r.p.name, r.p.name_zh)}</span>
                <span className={`tabular shrink-0 font-semibold ${r.v < 0 ? "text-status-critical" : "text-status-good"}`}>{fmtUsd(r.v)}</span>
              </li>
            ))}
          </ul>
        </StepCard>
      </ol>
      <p className="mt-3 rounded-lg bg-muted/40 px-3 py-2 text-sm" data-testid="verdict-trace">
        <span className="font-semibold">→ {L("Verdict", "结论")}: {verdictName}</span>
        <span className="text-muted-foreground">
          {" "}
          {decided.step === 0
            ? L(`set by your account and plan rules, not by the three steps: ${decided.en}`, `由账户与计划规则决定，而非三个步骤：${decided.zh}`)
            : L(`set by Step ${decided.step}: ${decided.en}`, `由第 ${decided.step} 步决定：${decided.zh}`)}
        </span>
      </p>
    </section>
  );
}
