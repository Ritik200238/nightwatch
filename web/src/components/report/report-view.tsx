"use client";

import { AccountLadder } from "@/components/report/account-ladder";
import { BookVisuals } from "@/components/report/book-visuals";
import { MarketClock } from "@/components/report/market-clock";
import { Group } from "@/components/report/group";
import { ThreeSteps } from "@/components/report/three-steps";
import { ThesisCheckCard } from "@/components/report/thesis-check";
import { CorporateEventsNote } from "@/components/report/corporate-events";
import { MarketContext } from "@/components/report/market-context";
import { sourceLine } from "@/components/report/source-ages";
import { AlertTriangle, CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { CostCurve } from "@/components/charts/cost-curve";
import { Histogram } from "@/components/charts/histogram";
import { Scenarios } from "@/components/charts/scenarios";
import { AgentPanel } from "@/components/report/agent-panel";
import { ActOnIt } from "@/components/report/act-on-it";
import { GuardNote } from "@/components/report/guard-note";
import { LeverageSafety } from "@/components/report/leverage-safety";
import { Feedback, WatchButton } from "@/components/report/feedback";
import { BookContrast } from "@/components/report/book-contrast";
import { PlanCard } from "@/components/report/plan-card";
import { BookStressView } from "@/components/report/book-stress";
import { TripwireButton } from "@/components/report/tripwire";
import { AnalogMini, BuildTrace, CredStrip, StressBars } from "@/components/report/decision-extras";
import { Permalink } from "@/components/report/permalink";
import { Pill, Section, SourceChip, SourceLegend, Stat } from "@/components/report/primitives";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type AnalystTake, api, type ClosedHoursLine, type Report, type TicketInput } from "@/lib/api";
import { fmtBps, fmtPct, fmtPrice, fmtRatio, fmtUsd, titleCase } from "@/lib/format";
import { breakerReason, capDetail, plainReason, plainText } from "@/lib/plain";
import { ordinal, presetName, regimeDescription, riskBasis, sourceName, stateWord } from "@/lib/i18n-terms";
import { fmtDateL, fmtHoursL, fmtTimeL, type Lang, STRINGS, t as tl, tr } from "@/lib/i18n";

/** The verdict word's colour in the headline: meaning carried by hue and by the word itself. */
const VERDICT_TEXT: Record<Report["verdict"]["verdict"], string> = {
  GO: "text-status-good",
  REDUCE_TO: "text-status-warning",
  HEDGE: "text-primary",
  NO_GO: "text-status-critical",
  REVIEW: "text-foreground",
};

/** What each verdict means, for someone seeing the badge for the first time. */
const VERDICT_ORDER: Report["verdict"]["verdict"][] = ["GO", "REDUCE_TO", "HEDGE", "REVIEW", "NO_GO"];

/** A verdict or gate decision as a badge label: "REDUCE TO" in English, the Chinese name otherwise. */
function verdictLabel(lang: Lang, d: string): string {
  if (lang === "en") return d.replace("_", " ");
  if (d === "REVIEW_REQUIRED") return "需要复核";
  return tl(lang, "verdictName", d);
}

/** The worst stress preset, in money, with the name of the scenario that caused it. */
function worstPreset(report: Report): { name: string; zh?: string; quote: number; pct: number | null } | null {
  const rows = report.stress.presets.map((p, i) => ({ p, imp: report.stress.impacts[i] })).filter((r) => r.imp?.total_pnl_quote != null);
  if (!rows.length) return null;
  const worst = rows.reduce((a, b) => ((a.imp.total_pnl_quote ?? 0) <= (b.imp.total_pnl_quote ?? 0) ? a : b));
  return { name: worst.p.name, zh: worst.p.name_zh, quote: worst.imp.total_pnl_quote as number, pct: worst.imp.total_pct_of_notional };
}

/** The cap that actually cuts the requested size, if one does. */
function bindingCap(report: Report) {
  const c = report.sizing.caps.find((x) => x.name === report.sizing.binding_cap);
  if (!c || c.notional == null || c.notional >= report.ticket.notional_quote - 1) return null;
  return c;
}

/** Everything a person needs in five seconds: what to do, what it costs to be wrong,
 *  what could go worse, whether you can get out, and the best argument against it.
 *  The twelve sections below are the evidence for this card, and they open on demand. */
const TAKE_HEADINGS = new Set<string>([...STRINGS.en.takeHeadings, ...STRINGS.zh.takeHeadings]);

/** The analyst's take: the model reads the finished report and says what matters.
 *
 *  The desk has already answered from its own numbers; this is asked for in the
 *  background and shown when it arrives, because the model takes 30-90 s to write and
 *  nobody should wait for it. It cannot change the verdict, and any sentence citing a
 *  number that is not in the report is removed before it is shown - the count is printed.
 */
/** The analyst's text without its [section] source markers; the citations travel as separate data. */
function withSourceTags(text: string, lang: Lang) {
  return plainText(text, lang);
}

function AnalystTakeCard({ report, langHint }: { report: Report; langHint: Lang }) {
  const id = report.forecast_id;
  const [take, setTake] = useState<AnalystTake | null>(null);
  const lang: "en" | "zh" = langHint;

  useEffect(() => {
    if (id == null) return;
    let live = true;
    let tries = 0;
    const poll = async () => {
      try {
        const t = tries === 0 ? await api.analystStart(id, lang) : await api.analystGet(id, lang);
        if (!live) return;
        setTake(t);
        tries += 1;
        if (t.status === "pending" && tries < 40) setTimeout(poll, 3000);
      } catch {
        if (live) setTake({ status: "failed" });
      }
    };
    void poll();
    return () => {
      live = false;
    };
  }, [id, lang]);

  if (id == null || take?.status === "unavailable" || take?.status === "none") return null;
  if (!take) {
    return (
      <div className="rounded-lg border border-border bg-card p-4" role="status">
        <p className="text-sm font-semibold">{lang === "zh" ? "分析师的看法" : "The analyst's take"}</p>
        <p className="mt-2 animate-pulse text-sm text-muted-foreground">{lang === "zh" ? "分析师撰写中…（约 10 秒）" : "Analyst writing… (about 10 s)"}</p>
        <div className="mt-2 space-y-1.5" aria-hidden>
          <div className="h-2.5 w-full animate-pulse rounded bg-foreground/10" />
          <div className="h-2.5 w-4/5 animate-pulse rounded bg-foreground/10" />
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-semibold">
          {lang === "zh" ? "分析师的看法" : "The analyst's take"}
          <SourceChip entry={report.provenance?.items.analyst ?? { kind: "ai" }} lang={lang} />
        </p>
        <p className="text-[13px] text-muted-foreground">
          {take.status === "done"
            ? `${take.model || "Qwen"} · ${take.seconds ?? "?"}s · ${lang === "zh" ? "数字已与报告核对；推理是模型自己的，可能出错" : "numbers checked against the report; the reasoning is the model's and can be wrong"}`
            : null}
        </p>
      </div>
      {take.status === "done" && take.removed ? <GuardNote n={take.removed} lang={lang} className="mt-1 text-[13px] text-muted-foreground" /> : null}
      {take.status === "pending" ? (
        <p className="mt-2 animate-pulse text-sm text-muted-foreground">
          {lang === "zh" ? "分析师撰写中…（约 10 秒）。上面的结论已经完整。" : "Analyst writing… (about 10 s). The verdict above is already complete."}
        </p>
      ) : take.status === "failed" || !take.text ? (
        <p className="mt-2 text-sm text-muted-foreground">{lang === "zh" ? "这次 AI 分析师没有写出看法；上面的结论不受影响。" : "The analyst could not write a take this time; the verdict above stands on its own."}</p>
      ) : (
        <div className="mt-2 space-y-1 text-sm">
          {take.for || take.against ? (
            <div className="space-y-2 pb-2">
              <div className="grid gap-2 sm:grid-cols-2">
                {take.for ? (
                  <div className="rounded-md border border-border p-2">
                    <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{tr(lang)("Case for", "支持的理由")}</p>
                    <p className="mt-1 leading-relaxed">{withSourceTags(take.for, lang)}</p>
                  </div>
                ) : null}
                {take.against ? (
                  <div className="rounded-md border border-border p-2">
                    <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{tr(lang)("Case against", "反对的理由")}</p>
                    <p className="mt-1 leading-relaxed">{withSourceTags(take.against, lang)}</p>
                  </div>
                ) : null}
              </div>
              {take.reconcile ? <p className="text-[13px] text-muted-foreground">{withSourceTags(take.reconcile, lang)}</p> : null}
            </div>
          ) : null}
          {take.text
            .split("\n")
            .filter((l) => l.trim())
            .map((l, i) => {
              const clean = l.replace(/^[#*\s]+|[*]+$/g, "").trim();
              return TAKE_HEADINGS.has(clean) ? (
                <p key={i} className="pt-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase first:pt-0">
                  {clean}
                </p>
              ) : (
                <p key={i} className="leading-relaxed">
                  {withSourceTags(l.replace(/^[-•*]\s*/, "• "), lang)}
                </p>
              );
            })}
        </div>
      )}
    </div>
  );
}

/** The trader's own plan, measured where it can be.
 *
 *  "Wrong if it closes below 350" is a level the desk can put a distance and a history
 *  on; "if the story changes" is not, and saying so is better than pretending. A reason
 *  that reads against the position is flagged, because that is usually a typo in the side.
 */
function PlanNote({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const c = report.plan_check;
  if (!c) return null;
  let line: string | null = null;
  if (c.kind === "untested" && c.invalidation) {
    line = L(`“${c.invalidation}” is not something the desk can test against data, so it stays as your note.`, `“${c.invalidation}”无法用数据检验，所以只作为你的备注保留。`);
  } else if ((c.kind === "level" || c.kind === "moving_average") && c.level != null && c.distance_pct != null) {
    const what = c.note ? `${c.note} (${fmtPrice(c.level)})` : fmtPrice(c.level);
    const dist = Math.abs(c.distance_pct).toFixed(1);
    line = c.already
      ? L(`Your invalidation, ${what}, is already crossed at the current price.`, `你的失效条件 ${what} 在当前价格下已经被突破。`)
      : L(
          `Your invalidation, ${what}, is ${dist}% away${c.crossed != null ? `; ${c.crossed} of ${c.of} past moments like this crossed it inside the hold` : ""}.`,
          `你的失效条件 ${what} 距当前价格 ${dist}%${c.crossed != null ? `；过去 ${c.of} 个类似时刻中有 ${c.crossed} 个在持有期内触及过它` : ""}。`,
        );
  } else if (c.kind === "move" && c.distance_pct != null) {
    const dist = Math.abs(c.distance_pct).toFixed(1);
    line = L(
      `Your invalidation is a ${dist}% adverse move${c.crossed != null ? `; ${c.crossed} of ${c.of} past moments like this saw one inside the hold` : ""}.`,
      `你的失效条件是 ${dist}% 的不利波动${c.crossed != null ? `；过去 ${c.of} 个类似时刻中有 ${c.crossed} 个在持有期内出现过这样的波动` : ""}。`,
    );
  } else if (c.kind === "wrong_side" && c.level != null) {
    const rel = lang === "zh" ? (c.note === "above" ? "高于" : c.note === "below" ? "低于" : c.note) : c.note;
    line = L(
      `Your invalidation, ${fmtPrice(c.level)}, is ${c.note} the current price - for this direction that reads like a target, not what would prove you wrong.`,
      `你的失效条件 ${fmtPrice(c.level)} ${rel}当前价格——对这个方向来说，它更像目标价，而不是能证明你判断错误的位置。`,
    );
  }
  if (!line && !c.thesis_mismatch) return null;
  return (
    <div className={`mt-3 rounded-lg border px-3 py-2 text-sm ${c.already || c.thesis_mismatch || c.kind === "wrong_side" ? "border-status-warning/40 bg-status-warning/5" : "border-border bg-muted/30"}`}>
      <span className="font-medium text-foreground">{L("Your plan, checked: ", "对你的计划的检查：")}</span>
      <span className="text-muted-foreground">
        {line}
        {c.thesis_mismatch ? L(` Note: ${c.thesis_mismatch}.`, ` 注意：${c.thesis_mismatch}。`) : ""}
      </span>
    </div>
  );
}

/** Where the exchange closes a leveraged position, and how often history got there.
 *
 *  A liquidation is not a bad night that can be ridden back: the margin is gone. So it
 *  sits next to the verdict, not in a panel further down.
 */
function LiquidationNote({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const l = report.leverage;
  if (!l) return null;
  let line: string;
  let bad = true;
  if (!l.perp_symbol) {
    line = L(
      `Bitget lists no perpetual for ${report.ticket.ticker}, so ${l.leverage}x is not available; everything below is the spot trade.`,
      `Bitget 没有上线 ${report.ticket.ticker} 的永续合约，所以无法使用 ${l.leverage}x 杠杆；下面的一切都按现货交易计算。`,
    );
  } else if (!l.allowed) {
    line = L(`${l.leverage}x is more than the ${l.max_leverage_at_size}x Bitget allows at this size.`, `${l.leverage}x 超过了 Bitget 在这个仓位下允许的 ${l.max_leverage_at_size}x。`);
  } else if (l.liquidation_price == null || l.liquidation_distance_pct == null) {
    line = L(`${l.leverage}x noted, but with no entry price the liquidation level is unknown.`, `已记录 ${l.leverage}x，但没有入场价，所以强平价格未知。`);
  } else {
    const seen: string[] = [];
    if (l.analog_of) seen.push(L(`${l.analog_hits} of ${l.analog_of} past moments like this reached it inside the hold`, `过去 ${l.analog_of} 个类似时刻中有 ${l.analog_hits} 个在持有期内触及强平价`));
    if (l.mc_share != null) seen.push(L(`${fmtRatio(l.mc_share)} of simulated paths do`, `${fmtRatio(l.mc_share)} 的模拟路径会触及强平价`));
    if (l.presets_hit.length) seen.push(L(`${l.presets_hit.length} stress preset${l.presets_hit.length > 1 ? "s" : ""} liquidate it`, `${l.presets_hit.length} 个压力情景会将其强平`));
    line = L(
      `${l.leverage}x: about ${fmtUsd(l.margin_quote)} USDT of margin, liquidated near ${fmtPrice(l.liquidation_price)} (${l.liquidation_distance_pct.toFixed(1)}% away). ${seen.join("; ")}.`,
      `${l.leverage}x：保证金约 ${fmtUsd(l.margin_quote)} USDT，价格接近 ${fmtPrice(l.liquidation_price)} 时强平（距当前 ${l.liquidation_distance_pct.toFixed(1)}%）。${seen.join("；")}。`,
    );
    bad = (l.analog_hits ?? 0) > 0 || l.presets_hit.length > 0 || (l.mc_share ?? 0) >= 0.05;
  }
  return (
    <div className={`mt-3 rounded-lg border px-3 py-2 text-sm ${bad ? "border-status-critical/40 bg-status-critical/5" : "border-border bg-muted/30"}`}>
      <span className="font-medium text-foreground">{L("Liquidation: ", "强平：")}</span>
      <SourceChip entry={report.provenance?.items.liquidation} lang={lang} className="mr-1.5" />
      <span className="text-muted-foreground">
        {line}
        {l.tiers_source === "assumed"
          ? L(` Bitget's margin tiers were unavailable, so ${(l.mmr * 100).toFixed(1)}% maintenance margin is assumed.`, ` Bitget 的保证金档位不可用，因此按 ${(l.mmr * 100).toFixed(1)}% 的维持保证金率估算。`)
          : L(` Maintenance margin ${(l.mmr * 100).toFixed(2)}% from Bitget's tier for this size.`, ` 维持保证金率 ${(l.mmr * 100).toFixed(2)}%，取自 Bitget 对这个仓位的档位。`)}
      </span>
    </div>
  );
}

/** The stated reason, checked against the calendar. */
/** "Over the weekend" asked on a weekday: say which weekend was measured, and what past
 *  Friday-to-Monday weekends did, so 150 hours does not read as broken clock maths. */
function WeekendNote({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const w = report.weekend_only;
  if (!w) return null;
  return (
    <div className="mt-3 rounded-lg border border-status-warning/40 bg-status-warning/5 px-3 py-2 text-sm">
      <span className="font-medium text-foreground">{L("Which weekend: ", "指的是哪个周末：")}</span>
      <span className="text-muted-foreground">
        {L(
          `today is ${w.today}, so holding from now is ${(w.hold_from_now_h / 24).toFixed(1)} days, to Monday's open - longer than any hold we have scored. Buying on Friday instead: over ${report.ticket.ticker}'s last ${w.n} weekends, 1 in 20 lost more than ${(-w.p5_pct).toFixed(1)}% from Friday's close to Monday's open, and the worst was ${w.worst_pct.toFixed(1)}% (raw history, not calibrated). Run it again on Friday for the full check.`,
          `今天是 ${w.today}，从现在持有到周一开盘约 ${(w.hold_from_now_h / 24).toFixed(1)} 天，比我们评估过的任何持有期都长。改成周五买入的话：${report.ticket.ticker} 过去 ${w.n} 个周末里，二十分之一的情况从周五收盘到周一开盘亏损超过 ${(-w.p5_pct).toFixed(1)}%，最差的一次是 ${w.worst_pct.toFixed(1)}%（原始历史数据，未经校准）。周五再运行一次，可以得到完整的检查。`,
        )}
      </span>
    </div>
  );
}

function PremiseNote({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  if (!report.premise?.length) return null;
  return (
    <div className="mt-3 rounded-lg border border-status-warning/40 bg-status-warning/5 px-3 py-2 text-sm">
      <span className="font-medium text-foreground">{L("Check your plan: ", "请检查你的计划：")}</span>
      <span className="text-muted-foreground">{report.premise.join(" ")}</span>
    </div>
  );
}

/** How this trade loses money: each way it fails, what sets it off, why it costs what it
 *  does, and how often it happened. Written by rules from the report's own numbers; a
 *  model is never asked to invent a causal story. */
/** A failure mode's title in the reader's language: the backend's Chinese name when it has one. */
function modeTitle(m: { title: string; title_zh?: string }, lang: Lang): string {
  return lang === "zh" && m.title_zh ? m.title_zh : m.title;
}

function FailureModes({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  // Largest loss first whatever order the server stored: old reports were ranked by chance
  // times loss, which put a small gap above a bigger crash under a "worst first" heading.
  const modes = [...(report.failure_modes ?? [])].sort((a, b) => (a.loss_quote ?? Infinity) - (b.loss_quote ?? Infinity));
  if (!modes.length) return null;
  const worst = modes[0];
  const worstLoss = worst.loss_quote != null ? ` ${fmtUsd(worst.loss_quote)} USDT` : "";
  return (
    <Section
      openAll={openAll}
      collapsible
      defaultOpen
      title={L("How this trade loses money", "这笔交易是怎么亏钱的")}
      subtitle={L(
        "Each way it fails, what sets it off, why it costs what it does, and how often it happened. Biggest loss first.",
        "每一种失败方式、由什么触发、为什么会亏这么多，以及历史上发生的频率。亏损最大的排在最前。",
      )}
      summary={L(`${modes.length} ways · worst: ${worst.title.toLowerCase()}${worstLoss}`, `${modes.length} 种方式 · 最坏：${modeTitle(worst, lang)}${worstLoss}`)}
    >
      <ol className="space-y-3">
        {modes.map((m) => (
          <li key={m.key} className="rounded-lg border border-border px-3 py-2">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <span className="font-medium">{modeTitle(m, lang)}</span>
              <span className="tabular text-sm font-medium text-status-critical">
                {m.loss_quote != null ? `${fmtUsd(m.loss_quote)} USDT` : "—"}
                {m.loss_pct != null ? <span className="text-muted-foreground"> · {fmtPct(m.loss_pct, 1)}</span> : null}
                {m.loss_quote_at_recommended != null ? <span className="text-xs font-normal text-muted-foreground"> {L(`(at the recommended ${fmtUsd(report.verdict.recommended_notional ?? 0)}: ${fmtUsd(m.loss_quote_at_recommended)})`, `（按建议仓位 ${fmtUsd(report.verdict.recommended_notional ?? 0)}：${fmtUsd(m.loss_quote_at_recommended)}）`)}</span> : null}
              </span>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              <span className="text-foreground">{L("If: ", "如果：")}</span>
              {m.trigger}. <span className="text-foreground">{L("Then: ", "那么：")}</span>
              {m.mechanism}.
            </p>
            <p className="mt-1 text-[13px] text-muted-foreground">{L(`How often: ${m.likelihood} · from ${m.source}`, `发生频率：${m.likelihood} · 来源：${sourceName(lang, m.source)}`)}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}

/** What the verdict assumes. Caveats are the ones that could make the numbers wrong. */
function Assumptions({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const items = report.assumptions ?? [];
  if (!items.length) return null;
  const caveats = items.filter((a) => a.kind === "caveat").length;
  return (
    <Section
      openAll={openAll}
      collapsible
      title={L("What this answer assumes", "这个结论的前提假设")}
      subtitle={L("Every input the verdict rests on. The flagged ones are where the numbers could be wrong.", "结论所依赖的每一项输入。带标记的那些，是数字可能出错的地方。")}
      summary={L(`${items.length} assumptions · ${caveats} could change the answer`, `${items.length} 项假设 · ${caveats} 项可能改变结论`)}
    >
      <ul className="space-y-1.5 text-sm">
        {items.map((a, i) => (
          <li key={`${a.topic}-${i}`} className="flex gap-2">
            <span className={`mt-0.5 shrink-0 text-xs font-medium ${a.kind === "caveat" ? "text-status-warning" : "text-muted-foreground"}`}>{a.kind === "caveat" ? "!" : "–"}</span>
            <span className={a.kind === "caveat" ? "text-foreground" : "text-muted-foreground"}>{a.text}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function DecisionCard({ report, lang, onRerun }: { report: Report; lang: Lang; onRerun?: (patch: Partial<TicketInput>) => void }) {
  const L = tr(lang);
  const v = report.verdict;
  const t = report.ticket;
  const worst = worstPreset(report);
  const cap = bindingCap(report);
  const exit = report.execution.exit_quote;
  const against = report.second_opinion?.against?.[0];
  // Both tiles are priced at the size asked for; say so when the verdict is a smaller one.
  const atRequested =
    v.recommended_notional != null && v.recommended_notional < t.notional_quote - 1 ? L(`at your ${fmtUsd(t.notional_quote)} USDT`, `按你要求的 ${fmtUsd(t.notional_quote)} USDT 计`) : "";

  const req = t.notional_quote;
  const rec = v.recommended_notional;
  const smaller = rec != null && rec < req - 1;
  let sizeText = "";
  if (v.verdict === "GO") sizeText = `${fmtUsd(rec ?? req)} USDT`;
  // A size under 5% of the request, or under 100 USDT, is not one anyone would trade: say no sensible size
  // passes rather than print "56 of 10,000 USDT" beside a verdict (the chat reply follows the same rule).
  else if ((v.verdict === "REDUCE_TO" || v.verdict === "REVIEW") && rec != null && smaller && rec < Math.max(100, 0.05 * req))
    sizeText = L("no sensible size passes right now", "目前没有合适的仓位能通过限制");
  else if ((v.verdict === "REDUCE_TO" || v.verdict === "REVIEW") && rec != null && smaller) sizeText = L(`${fmtUsd(rec)} of ${fmtUsd(req)} USDT`, `${fmtUsd(rec)} / ${fmtUsd(req)} USDT`);
  else if (v.verdict === "HEDGE") sizeText = L(`hedge ${fmtRatio(v.hedge_ratio)} of ${fmtUsd(req)} USDT`, `对冲 ${fmtRatio(v.hedge_ratio)} · ${fmtUsd(req)} USDT`);
  const prov = report.provenance?.items;
  const reasonLines = v.reasons.map((r) => plainReason(r, lang));
  // A REVIEW with no account size is the first answer most people see. One sentence: what to do,
  // and why, with the loss at the size they asked for. The verdict and the size are unchanged.
  const hz = report.analog?.horizons?.[report.primary_horizon];
  const badNightPct = hz?.loss_p5_pct ?? (t.side === "short" ? null : (hz?.p5_adjusted ?? hz?.cohort?.p5 ?? null));
  const badNight = badNightPct != null && badNightPct < 0 ? Math.abs((badNightPct / 100) * req) : null;
  const needsAccount = v.verdict === "REVIEW" && !t.account_equity_quote;
  const bookLimit = smaller && rec != null ? rec : null;
  const topLine = needsAccount
    ? L(
        `Tell the desk your account size${t.stop_price ? "" : " (and add a stop if you can)"} to finish the checks. At ${fmtUsd(req)} USDT a bad night, one in twenty, loses about ${badNight != null ? fmtUsd(badNight) : "—"} USDT${bookLimit != null ? `, and the live order book supports only ${fmtUsd(bookLimit)} USDT` : ""}.`,
        `请告诉系统你的账户规模${t.stop_price ? "" : "（有止损的话也请加上）"}，才能完成检查。按 ${fmtUsd(req)} USDT 计，二十分之一的坏夜晚约亏 ${badNight != null ? fmtUsd(badNight) : "—"} USDT${bookLimit != null ? `，而当前盘口只能承接 ${fmtUsd(bookLimit)} USDT` : ""}。`,
      )
    : "";
  const subhead = topLine || (reasonLines[0] ?? "");

  return (
    <Section
      title={`${t.ticker} ${lang === "zh" ? tl(lang, "side", t.side) : t.side.toUpperCase()} · ${fmtUsd(t.notional_quote)} USDT`}
      subtitle={L(
        `Held for ${fmtHoursL(report.horizon_h, lang)} · as of ${fmtTimeL(report.as_of, lang)} · market state: ${report.snapshot.labels.regime_label}`,
        `持有 ${fmtHoursL(report.horizon_h, lang)} · 截至 ${fmtTimeL(report.as_of, lang)} · 市场状态：${stateWord(lang, report.snapshot.labels.regime_label)}`,
      )}
    >
      {/* The answer first: the verdict word, coloured, with the size it applies to. The
          reason is one plain line under it; the rest sit in the list further down. */}
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 leading-tight tracking-tight">
        <span className={`text-4xl font-extrabold sm:text-5xl ${VERDICT_TEXT[v.verdict]}`}>{verdictLabel(lang, v.verdict)}</span>
        {sizeText ? <span className="tabular text-2xl font-semibold sm:text-3xl">· {sizeText}</span> : null}
      </p>
      {subhead ? <p className="mt-2 text-base text-muted-foreground sm:text-lg">{subhead}</p> : null}
      <CredStrip lang={lang} />
      {prov ? <SourceLegend lang={lang} /> : null}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <StressBars report={report} lang={lang} />
        <AnalogMini report={report} lang={lang} />
      </div>
      <BuildTrace report={report} lang={lang} />
      <details className="mt-3 text-[13px] text-muted-foreground">
        <summary className="cursor-pointer select-none hover:text-foreground">{L("What the verdicts mean", "各个结论是什么意思")}</summary>
        <ul className="mt-1 space-y-0.5">
          {VERDICT_ORDER.map((k) => (
            <li key={k} className={k === v.verdict ? "text-foreground" : undefined}>
              <span className="font-medium">{verdictLabel(lang, k)}</span>
              {L(": ", "：")}
              {tl(lang, "verdictMeaning", k)}
            </li>
          ))}
        </ul>
        <p className="mt-1">{L("The desk sizes and warns; it never places the trade. You decide.", "系统只负责给出仓位和风险提示，从不替你下单。决定权在你。")}</p>
      </details>
      <ul className="mt-3 space-y-1 text-sm text-muted-foreground empty:hidden">
        {reasonLines.slice(1).map((r) => (
          <li key={r} className="flex gap-2">
            <span aria-hidden>–</span>
            <span>{r}</span>
          </li>
        ))}
      </ul>

      <BookNote report={report} lang={lang} />

      {/* The four numbers, in money, because a percentage of a position is not a feeling. */}
      <div className="mt-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Stat
          label={report.gate.risk_basis === "distance to stop" ? L("If your stop is hit", "如果触及你的止损") : L("One-in-twenty loss", "二十分之一的亏损")}
          value={report.gate.risk_quote != null ? `−${fmtUsd(report.gate.risk_quote)}` : "—"}
          hint={[riskBasis(lang, report.gate.risk_basis), atRequested].filter(Boolean).join(" · ")}
          tone="warning"
          chip={<SourceChip entry={prov?.loss_line} lang={lang} />}
        />
        <Stat
          label={L("Worst stress scenario", "最坏的压力情景")}
          value={worst ? fmtUsd(worst.quote) : "—"}
          hint={worst ? `${L(`${worst.name} · ${fmtPct(worst.pct, 1)} of the position`, `${presetName(lang, worst.name, worst.zh)} · 占仓位的 ${fmtPct(worst.pct, 1)}`)}${atRequested ? ` · ${atRequested}` : ""}` : L("no priced scenario", "没有可定价的情景")}
          tone="critical"
          chip={<SourceChip entry={prov?.worst_stress} lang={lang} />}
        />
        <Stat
          label={L("Getting out costs", "平仓成本")}
          value={exit?.total_cost_quote != null ? `−${fmtUsd(exit.total_cost_quote)}` : "—"}
          hint={exit?.total_cost_bps != null ? L(`${fmtBps(exit.total_cost_bps)} on the ${report.execution.book_source} book`, `按${stateWord(lang, report.execution.book_source)}盘口计 ${fmtBps(exit.total_cost_bps)}`) : L("no order book", "没有盘口数据")}
          chip={<SourceChip entry={prov?.exit_cost} lang={lang} />}
        />
        <Stat
          label={cap ? L("Size held down by", "仓位被压低的原因") : L("Size", "仓位")}
          value={cap ? fmtUsd(cap.notional as number) : fmtUsd(t.notional_quote)}
          hint={cap ? `${tl(lang, "cap", cap.name)} — ${capDetail(cap.detail, lang)}` : L("inside every cap", "在所有上限之内")}
          tone={cap ? "warning" : "good"}
          chip={<SourceChip entry={prov?.size} lang={lang} />}
        />
      </div>

      {against ? (
        <p className="mt-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{L("The best case against it: ", "反对它的最有力理由：")}</span>
          {against.text}
        </p>
      ) : null}

      <LiquidationNote report={report} lang={lang} />
      <LeverageSafety report={report} lang={lang} onRerun={onRerun} />
      <WeekendNote report={report} lang={lang} />
      <PremiseNote report={report} lang={lang} />
      <CorporateEventsNote report={report} lang={lang} />
      {report.forecast_id != null && report.ticket.thesis ? <ThesisCheckCard forecastId={report.forecast_id} thesis={report.ticket.thesis} lang={lang} /> : null}
      <PlanNote report={report} lang={lang} />
      <ActOnIt report={report} lang={lang} />
      {/* A what-if was never journalled, so there is no forecast to mark taken and
          nothing to score it against later. Offering the button would put a trade the
          trader never made into the circuit breaker's count. */}
      {report.forecast_id != null && report.forecast_id > 0 ? <TakenButton forecastId={report.forecast_id} lang={lang} noGo={v.verdict === "NO_GO"} /> : null}
      {report.warnings.length ? (
        <div className="mt-4 rounded-lg border border-status-warning/40 bg-status-warning/5 p-3 text-sm">
          <p className="mb-1 flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4 text-status-warning" aria-hidden /> {L("Caveats", "注意事项")}
          </p>
          <ul className="space-y-1 text-muted-foreground">
            {report.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </Section>
  );
}

const MOVING_TONE: Record<string, "critical" | "warning" | "muted"> = { high: "critical", medium: "warning", low: "muted", none: "muted" };

/** A filing the market has not opened since.
 *
 *  This is the one place on the report where a model's judgement is shown, and it is
 *  split down the middle on purpose. The headline and the flag are the model's, from
 *  the filing's own words. The percentile beside them is not: it is what this desk's
 *  own bars did after every other filing the model flagged the same way, which is the
 *  only reason the flag is allowed on the page — see the Studies page, where the
 *  flagged filings were followed by a 1.62× larger move on 18 of 20 tokens.
 *
 *  No direction is shown. The model offers one and it was measured at 49.5% against a
 *  coin, so it does not travel.
 */
/** Bitget's signal-skill RSI next to the one the desk computes from Bitget candles.
 *  Shown only when the two agree (the API withholds it otherwise), and never an input to the size. */
function SignalLine({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const g = report.signal;
  if (!g) return null;
  const word = g.reading === "oversold" ? L("oversold", "超卖") : g.reading === "overbought" ? L("overbought", "超买") : L("neutral", "中性");
  return (
    <p className="px-1 text-[13px] text-muted-foreground">
      {L(
        `Bitget signal skill: RSI ${g.rsi.toFixed(1)} on ${g.timeframe} (${word}); our own from Bitget candles ${g.own_rsi.toFixed(1)}, which agrees.`,
        `Bitget 信号技能：${g.timeframe} RSI ${g.rsi.toFixed(1)}（${word}）；我们用 Bitget K 线自算 ${g.own_rsi.toFixed(1)}，一致。`,
      )}
      {g.macd ? L(` MACD ${g.macd.macd.toFixed(2)} vs signal ${g.macd.signal.toFixed(2)}.`, ` MACD ${g.macd.macd.toFixed(2)}，信号线 ${g.macd.signal.toFixed(2)}。`) : null}{" "}
      {L("Context only; it did not move the size.", "仅供参考，没有影响仓位。")}
    </p>
  );
}

/** What the street and the insiders are doing, from Bitget's own US-stock data.
 *
 *  Shown next to the verdict and said to be context, because none of it has been
 *  measured to predict an overnight move and so none of it reaches the size. The part
 *  that does work is the first line: while the US market is shut, Bitget's quote keeps
 *  moving with the stock's overnight trading, which makes it a live fair value where the
 *  desk otherwise only has yesterday's close.
 */
function StreetSection({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const s = report.street;
  if (!s) return null;
  const live = s.token_vs_live_bps;
  const close = s.token_vs_close_bps;
  const mood = s.mood_score != null ? `${Math.round(s.mood_score)} (${s.mood_rating ?? ""})` : null;
  const summary = [
    live != null ? L(`token ${fmtBps(live, 0)} from the live stock price`, `代币较股票实时价格 ${fmtBps(live, 0)}`) : null,
    s.n_firms ? L(`${s.n_firms} analysts, median target ${fmtUsd(s.median_target, 0)}`, `${s.n_firms} 位分析师，目标价中位数 ${fmtUsd(s.median_target, 0)}`) : null,
    s.insider_sells || s.insider_buys ? L(`insiders ${s.insider_sells} sells / ${s.insider_buys} buys`, `内部人士 ${s.insider_sells} 笔卖出 / ${s.insider_buys} 笔买入`) : null,
    mood ? L(`market mood ${mood}`, `市场情绪 ${mood}`) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Section
      openAll={openAll}
      collapsible
      title={L("The stock right now, and what the street thinks", "这只股票现在的情况，以及华尔街怎么看")}
      subtitle={
        s.stale
          ? L(
              `From Bitget's US-stock data, but not live: ${s.age_label ?? "last good, age unknown"}. Context beside the verdict, not an input to it.`,
              `来自 Bitget 的美股数据，但不是实时的：${s.age_s != null ? `${fmtHoursL(s.age_s / 3600, lang)}前的最近一次有效数据` : "最近一次有效数据，时间未知"}。只是结论旁边的背景信息，不参与结论的计算。`,
            )
          : L("From Bitget's US-stock data. Context beside the verdict, not an input to it.", "来自 Bitget 的美股数据。只是结论旁边的背景信息，不参与结论的计算。")
      }
      summary={summary}
    >
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label={L("Token vs the stock, live", "代币对比股票（实时）")}
          value={live != null ? fmtBps(live, 0) : "—"}
          hint={close != null ? L(`against yesterday's close it is ${fmtBps(close, 0)}`, `相对昨日收盘价为 ${fmtBps(close, 0)}`) : undefined}
        />
        <Stat
          label={L(`Analysts, last 90 days (${s.n_firms} firms)`, `分析师，近 90 天（${s.n_firms} 家机构）`)}
          value={s.n_firms ? L(`${s.bullish} buy · ${s.neutral} hold · ${s.bearish} sell`, `${s.bullish} 买入 · ${s.neutral} 持有 · ${s.bearish} 卖出`) : L("no coverage", "无覆盖")}
          hint={
            s.median_target != null
              ? L(
                  `median target ${fmtUsd(s.median_target, 0)}${s.target_gap_pct != null ? `, ${fmtPct(s.target_gap_pct, 1)} from here` : ""}`,
                  `目标价中位数 ${fmtUsd(s.median_target, 0)}${s.target_gap_pct != null ? `，较现价 ${fmtPct(s.target_gap_pct, 1)}` : ""}`,
                )
              : undefined
          }
        />
        <Stat
          label={L("Insiders, last 90 days", "内部人士，近 90 天")}
          value={s.insider_sells || s.insider_buys ? L(`${s.insider_sells} sells · ${s.insider_buys} buys`, `${s.insider_sells} 笔卖出 · ${s.insider_buys} 笔买入`) : L("none on the open market", "公开市场上没有交易")}
          hint={s.insider_sold_value || s.insider_bought_value ? L(`sold ${fmtUsd(s.insider_sold_value, 0)}, bought ${fmtUsd(s.insider_bought_value, 0)}`, `卖出 ${fmtUsd(s.insider_sold_value, 0)}，买入 ${fmtUsd(s.insider_bought_value, 0)}`) : undefined}
        />
        <Stat
          label={L("Market mood (fear & greed)", "市场情绪（恐惧与贪婪）")}
          value={mood ?? "—"}
          hint={s.mood_week_ago != null ? L(`a week ago ${Math.round(s.mood_week_ago)}, a month ago ${Math.round(s.mood_month_ago ?? 0)}`, `一周前 ${Math.round(s.mood_week_ago)}，一个月前 ${Math.round(s.mood_month_ago ?? 0)}`) : undefined}
        />
      </div>
      {s.recent_changes.length ? (
        <ul className="mt-3 space-y-1 text-sm">
          {s.recent_changes.map((c) => (
            <li key={`${c.date}-${c.firm}`}>
              <span className="tabular text-muted-foreground">{fmtDateL(c.date, lang)}</span> · {c.firm} {c.action} {c.rating}
              {c.target != null ? <> · {L("target", "目标价")} {fmtUsd(c.target, 0)}</> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {s.insider_latest.length ? (
        <p className="mt-2 text-[13px] text-muted-foreground">
          {L("Latest insider trade: ", "最近一笔内部人士交易：")}
          {s.insider_latest[0].name}
          {s.insider_latest[0].title ? ` (${s.insider_latest[0].title})` : ""}{" "}
          {L(
            `${s.insider_latest[0].side === "sell" ? "sold" : "bought"} ${Math.round(s.insider_latest[0].shares).toLocaleString()} shares on ${fmtDateL(s.insider_latest[0].date, lang)}.`,
            `于 ${fmtDateL(s.insider_latest[0].date, lang)} ${s.insider_latest[0].side === "sell" ? "卖出" : "买入"}了 ${Math.round(s.insider_latest[0].shares).toLocaleString()} 股。`,
          )}
        </p>
      ) : null}
      <p className="mt-3 text-[13px] text-muted-foreground">
        {L(
          "Nothing in this section moved the size: none of it has been tested against what the token did overnight. The live price does change what the basis means, and a disagreement between the two sources over the last close is raised as a caveat above.",
          "这一节的内容都没有影响仓位：其中没有任何一项经过代币隔夜实际表现的检验。不过实时价格确实会改变基差的含义；如果两个数据源对上一次收盘价有分歧，会在上方作为注意事项提出。",
        )}
      </p>
    </Section>
  );
}

/** The rest of what Bitget's US-stock catalogue knows about the company: its own earnings date
 *  (set against Nasdaq's), valuation, dividends and the analysts' consensus target.
 *
 *  Read from the desk's cache and labelled as Bitget's. Context beside the verdict: none of it
 *  has been tested against what the token did overnight, so none of it reaches the size. The one
 *  line that can matter is the earnings dates disagreeing, which is also raised as a caveat. */
function BitgetSection({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const b = report.bitget;
  if (!b) return null;
  const cal = b.entries.equity_calendar;
  const val = b.entries.equity_fundamental_ratios;
  const div = b.entries.equity_fundamental_dividends;
  const con = b.entries.equity_estimates_consensus;
  const prof = b.entries.equity_profile;
  const chk = b.earnings_check;
  const next = cal?.next_report;
  const earningsHint =
    chk?.status === "agree"
      ? L("Nasdaq's calendar gives the same date", "纳斯达克日历给出相同日期")
      : chk?.status === "differ"
        ? L(`Nasdaq says ${chk.nasdaq}: ${Math.abs(chk.gap_days ?? 0)} day(s) apart, so one is an estimate`, `纳斯达克为 ${chk.nasdaq}：相差 ${Math.abs(chk.gap_days ?? 0)} 天，其中一个是预估日期`)
        : chk?.status === "nasdaq_only"
          ? L(`Bitget has no date; Nasdaq says ${chk.nasdaq}`, `Bitget 没有日期；纳斯达克为 ${chk.nasdaq}`)
          : cal?.confirmed === false
            ? L("expected, not confirmed", "预计日期，尚未确认")
            : undefined;
  const earningsValue = next
    ? `${fmtDateL(next, lang)}${cal?.timing ? ` · ${cal.timing}` : ""}`
    : chk?.status === "nasdaq_only" && chk.nasdaq
      ? L("not in Bitget's calendar", "Bitget 日历中没有")
      : cal?.last_report
        ? L(`none ahead; last ${fmtDateL(cal.last_report, lang)}`, `暂无后续；上次 ${fmtDateL(cal.last_report, lang)}`)
        : "—";
  const stats = [
    cal || chk ? { key: "earn", label: L("Next earnings (Bitget calendar)", "下次财报（Bitget 日历）"), value: earningsValue, hint: earningsHint } : null,
    val
      ? {
          key: "val",
          label: L("Valuation (Bitget)", "估值（Bitget）"),
          value: [val.pe != null ? `P/E ${val.pe.toFixed(1)}` : null, val.pb != null ? `P/B ${val.pb.toFixed(1)}` : null, val.ps != null ? `P/S ${val.ps.toFixed(1)}` : null].filter(Boolean).join(" · ") || "—",
          hint:
            [
              val.market_cap_usd != null ? L(`market cap ${fmtUsd(val.market_cap_usd, 0)}`, `市值 ${fmtUsd(val.market_cap_usd, 0)}`) : null,
              val.period_ending ? L(`as of ${fmtDateL(val.period_ending, lang)}`, `截至 ${fmtDateL(val.period_ending, lang)}`) : null,
            ]
              .filter(Boolean)
              .join(", ") || undefined,
        }
      : null,
    div
      ? {
          key: "div",
          label: L("Dividends (Bitget)", "分红（Bitget）"),
          value: div.next_ex_date
            ? L(`ex-date ${fmtDateL(div.next_ex_date, lang)}`, `除息日 ${fmtDateL(div.next_ex_date, lang)}`)
            : div.last_ex_date
              ? L(`last ex-date ${fmtDateL(div.last_ex_date, lang)}`, `上次除息日 ${fmtDateL(div.last_ex_date, lang)}`)
              : "—",
          hint:
            div.next_amount != null
              ? L(`${div.next_amount.toFixed(2)} per share`, `每股 ${div.next_amount.toFixed(2)}`)
              : div.last_amount != null
                ? L(`${div.last_amount.toFixed(2)} per share, ${div.paid_last_12m} paid in 12 months`, `每股 ${div.last_amount.toFixed(2)}，12 个月内派发 ${div.paid_last_12m} 次`)
                : undefined,
        }
      : null,
    con
      ? {
          key: "con",
          label: L("Analyst consensus target (Bitget)", "分析师一致目标价（Bitget）"),
          value: con.target_consensus != null ? fmtUsd(con.target_consensus, 0) : con.target_median != null ? fmtUsd(con.target_median, 0) : "—",
          hint: con.target_low != null && con.target_high != null ? L(`range ${fmtUsd(con.target_low, 0)} to ${fmtUsd(con.target_high, 0)}`, `区间 ${fmtUsd(con.target_low, 0)} 至 ${fmtUsd(con.target_high, 0)}`) : undefined,
        }
      : null,
  ].filter((x): x is { key: string; label: string; value: string; hint: string | undefined } => x != null);
  if (!stats.length) return null;
  const sector = prof?.sector ? `${prof.sector}${prof.industry ? `, ${prof.industry}` : ""}` : "";
  return (
    <Section
      openAll={openAll}
      collapsible
      title={L("More from Bitget's data: earnings date, valuation, dividends", "Bitget 数据补充：财报日期、估值、分红")}
      subtitle={L(
        `From Bitget's US-stock catalogue${sector ? ` (${sector})` : ""}. Context beside the verdict, not an input to it.`,
        `来自 Bitget 美股数据目录${sector ? `（${sector}）` : ""}。只是结论旁边的背景信息，不参与结论的计算。`,
      )}
      summary={stats.map((x) => x.value).join(" · ")}
    >
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((x) => (
          <Stat key={x.key} label={x.label} value={x.value} hint={x.hint} />
        ))}
      </div>
    </Section>
  );
}

/** hours_to_earnings is capped at 720 h: at the cap it means none in 30 days, and null means not known. */
function earningsAhead(h: number | null | undefined, lang: Lang): string {
  const L = tr(lang);
  if (h == null || Number.isNaN(h)) return L("not known", "未知");
  if (h >= 720) return L("none in 30 d", "30 天内无");
  return fmtHoursL(h, lang);
}

function FreshFilings({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const notes = report.filings ?? [];
  if (!notes.length) return null;
  const worst = notes.reduce((a, b) => (["high", "medium"].includes(b.market_moving) && !["high", "medium"].includes(a.market_moving) ? b : a));
  const flagged = notes.some((n) => n.market_moving === "high" || n.market_moving === "medium");
  const impactOf = (m: string) => (lang === "zh" ? tl(lang, "impact", m) : m);

  return (
    <Section
      title={
        notes.length === 1
          ? L("A filing landed in the last 72 hours", "过去 72 小时内有一份文件披露")
          : L(`${notes.length} filings landed in the last 72 hours`, `过去 72 小时内有 ${notes.length} 份文件披露`)
      }
      subtitle={L(
        "Read from the filing's own text. The model says what it is; the history beside it says what followed the ones it flagged the same way.",
        "根据文件原文解读。模型说明这份文件是什么；旁边的历史数据则显示，以同样方式标记的文件之后发生了什么。",
      )}
      action={<Pill tone={flagged ? MOVING_TONE[worst.market_moving] : "muted"}>{flagged ? L(`${worst.market_moving} impact`, `${impactOf(worst.market_moving)}影响`) : notes.every((n) => n.market_moving === "unread") ? L("not yet read", "尚未解读") : L("routine", "例行")}</Pill>}
    >
      <div className="space-y-3">
        {notes.map((n) => (
          <div key={`${n.accepted_at}-${n.form}`} className="rounded-lg border border-border bg-muted/20 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <p className="text-sm font-medium">{n.headline}</p>
              <Pill tone={MOVING_TONE[n.market_moving] ?? "muted"}>{impactOf(n.market_moving)}</Pill>
            </div>
            <p className="mt-1 text-[13px] text-muted-foreground">
              {n.form}
              {n.items ? L(` item ${n.items}`, ` 第 ${n.items} 项`) : ""} · {titleCase(n.category)} ·{" "}
              {L(`filed ${fmtHoursL(n.hours_ago, lang)} ago`, `${fmtHoursL(n.hours_ago, lang)}前披露`)}
              {n.market_was_shut ? L(", while the US market was shut", "，当时美股休市") : L(", during the US session", "，在美股交易时段内")}
              {n.inside_window ? L(" · inside your holding window", " · 在你的持有期内") : ""}
            </p>
            {n.label_n != null && n.label_p5_pct != null ? (
              <p className="mt-2 text-sm">
                <span className="text-muted-foreground">{L("What followed the others: ", "其他同类文件之后的表现：")}</span>
                {lang === "zh" ? (
                  <>
                    模型标为“<span className="font-medium">{impactOf(n.market_moving)}</span>”的 {n.label_n} 份文件，到下一次开盘前的中位数变动为{" "}
                    <span className="tabular">{fmtPct(n.label_median_pct, 2)}</span>，二十分之一的情况比{" "}
                    <span className="tabular font-medium text-status-critical">{fmtPct(n.label_p5_pct, 2)}</span> 更差。
                  </>
                ) : (
                  <>
                    the {n.label_n} filings it called <span className="font-medium">{n.market_moving}</span> were followed by a median of{" "}
                    <span className="tabular">{fmtPct(n.label_median_pct, 2)}</span> before the next open, and one in twenty was worse than{" "}
                    <span className="tabular font-medium text-status-critical">{fmtPct(n.label_p5_pct, 2)}</span>.
                  </>
                )}
              </p>
            ) : n.market_moving === "unread" ? (
              <p className="mt-2 text-[13px] text-muted-foreground">{L("The model has not read this filing yet, so its impact is unknown and no history is quoted.", "模型还没有解读这份文件，所以影响未知，也不引用历史数据。")}</p>
            ) : (
              <p className="mt-2 text-[13px] text-muted-foreground">{L("Too few scored filings carry this label to quote a distribution, so none is shown.", "带这个标签且已评分的文件太少，无法给出分布，所以不显示。")}</p>
            )}
          </div>
        ))}
      </div>
      <p className="mt-3 text-[13px] text-muted-foreground">
        {L(
          "The model reads the text and nothing else — no price, and no knowledge of what happened next. It also offers a direction, which measured 49.5% against a coin, so it is not shown and reaches nothing. None of this moved the verdict above.",
          "模型只读文本，别的什么都不看——没有价格，也不知道之后发生了什么。它还会给出一个方向判断，但实测准确率只有 49.5%，和抛硬币没有区别，所以不显示，也不参与任何计算。以上内容都没有影响上面的结论。",
        )}
      </p>
    </Section>
  );
}

/** A report the desk ran because it was asked to, not because a trade was proposed.
 *
 *  Every forecast this desk produces is journalled and scored later, and the calibration
 *  that sizes real trades is fitted on those scores. A what-if is a forecast nobody took,
 *  and a cohort narrowed by a lens is a different estimator from the one being calibrated,
 *  so neither is recorded. That exemption is worth saying on the page rather than leaving
 *  a reader to assume this one counts like the others.
 */
function Hypothetical({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  if (report.forecast_id == null || report.forecast_id >= 0) return null;
  return (
    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
      <span className="font-medium text-foreground">{L("A what-if.", "假设情景。")}</span>{" "}
      {L(
        "The desk ran this against the same moment as the report you asked about. It is not journaled and will not be scored, because nobody proposed it as a trade.",
        "系统是在你所询问的那份报告的同一时刻上运行的。它不会记入日志，也不会被评分，因为没有人把它当作一笔交易提出来。",
      )}
    </div>
  );
}

export function ReportView({ report, onRerun, lang = "en", hideTake = false }: { report: Report; onRerun?: (patch: Partial<TicketInput>) => void; lang?: "en" | "zh"; hideTake?: boolean }) {
  const L = tr(lang);
  const t = report.ticket;
  const primary = report.analog?.horizons[report.primary_horizon];
  const budget = 25;
  // undefined = every section minds itself; true/false = the reader pressed one of the buttons.
  const [openAll, setOpenAll] = useState<boolean | undefined>(undefined);
  const f = report.snapshot.features;
  const H = (h: number | null | undefined) => fmtHoursL(h, lang);
  const flags = report.snapshot.quality_flags.length;

  return (
    <div className="space-y-4">
      {/* Everything the page builds itself is translated. The few sentences the server
          writes (failure-mode titles, some caveats, lens definitions) are shown as sent; one
          short note says so rather than an apology for the whole page. */}
      {lang === "zh" ? (
        <p className="text-[13px] text-muted-foreground" lang="zh">
          个别由服务器按规则生成的说明（如失败方式、注意事项）仍为英文，数字与含义不变。
        </p>
      ) : null}
      <Hypothetical report={report} lang={lang} />
      <DecisionCard report={report} lang={lang} onRerun={onRerun} />
      <ThreeSteps report={report} lang={lang} />
      <AccountLadder report={report} lang={lang} onRerun={onRerun} />
      <MarketClock report={report} lang={lang} />
      <BookVisuals report={report} lang={lang} />
      {/* A report that came out of the chat already has the take in the conversation. */}
      {hideTake ? null : <AnalystTakeCard report={report} langHint={lang} />}
      {report.forecast_id != null && report.forecast_id > 0 ? <AgentPanel forecastId={report.forecast_id} lang={lang} /> : null}
      {/* Above the disclosures on purpose. Narrowing the search changes what every
          number below it means, so it cannot sit behind a section a reader has to
          open before the summary stops being misleading. */}
      <LensNote report={report} lang={lang} onUnfiltered={onRerun ? () => onRerun({ lenses: [], auto_lens: false }) : undefined} />
      <FreshFilings report={report} lang={lang} />
      <FailureModes report={report} openAll={openAll} lang={lang} />

      <div className="flex items-center justify-between gap-3 px-1">
        <p className="text-[13px] text-muted-foreground">{L("The evidence behind that answer. Open what you want to argue with.", "这个结论背后的证据。想质疑哪一块，就展开哪一块。")}</p>
        <button
          type="button"
          onClick={() => setOpenAll((o) => !o)}
          aria-pressed={Boolean(openAll)}
          className="rounded text-[13px] text-muted-foreground underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {openAll ? L("Collapse all", "全部收起") : L("Expand all", "全部展开")}
        </button>
      </div>

      {/* Key evidence stays open on the page: the similar moments and the stress tests are
          what the verdict is built from. Everything else is filed under a heading. */}
      {/* Analogs */}
      <AnalogSection report={report} openAll={openAll} lang={lang} />

      {/* Stress */}
      <StressSection report={report} openAll={openAll} lang={lang} />
      <MarketContext report={report} lang={lang} />

      <Group title={L("Evidence", "证据")} hint={L("Assumptions, today's inputs, exit cost, discipline gate, size caps, the case against, regime, what would change it", "假设、当前输入、平仓成本、纪律闸门、仓位上限、反面意见、市场状态、什么会改变结论")} openAll={openAll}>
        <Assumptions report={report} openAll={openAll} lang={lang} />
      {/* Now */}
      <Section
        openAll={openAll}
        collapsible
        summary={L(
          `${fmtPrice(report.snapshot.prices.spot_close)} · vs fair value ${fmtBps(f.basis_index_bps, 0, true)} · volatility ${f.vol_pctl_90d != null ? ordinal(Math.round(f.vol_pctl_90d)) : "—"} percentile of 90 days · ${flags ? `${flags} data flag${flags > 1 ? "s" : ""}` : "inputs complete"}`,
          `${fmtPrice(report.snapshot.prices.spot_close)} · 相对公允价值 ${fmtBps(f.basis_index_bps, 0, true)} · 波动率处于近 90 天的第 ${f.vol_pctl_90d?.toFixed(0) ?? "—"} 百分位 · ${flags ? `${flags} 项数据标记` : "输入完整"}`,
        )}
        title={L("Right now", "当前状况")}
        subtitle={L(`Last completed bar ${fmtTimeL(report.snapshot.bar_ts, lang)} · inputs hash ${report.snapshot.content_hash}`, `最近一根已完成的 K 线 ${fmtTimeL(report.snapshot.bar_ts, lang)} · 输入哈希 ${report.snapshot.content_hash}`)}
      >
        {/* Seven tiles across a 820px column truncates every label: "Fair value (in…".
            Four columns and two rows keeps them readable at every width. */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          <Stat label={L("Token price", "代币价格")} value={fmtPrice(report.snapshot.prices.spot_close)} />
          <Stat
            label={L("Fair value (index)", "公允价值（指数）")}
            value={fmtPrice(report.snapshot.prices.index_close)}
            hint={L(`native close ${fmtPrice(report.snapshot.prices.native_close)} · ${H(report.snapshot.features.native_close_age_h)} old`, `原生收盘价 ${fmtPrice(report.snapshot.prices.native_close)} · 已过去 ${H(report.snapshot.features.native_close_age_h)}`)}
          />
          <Stat label={L("Token vs fair value", "代币相对公允价值")} value={fmtBps(report.snapshot.features.basis_index_bps, 1, true)} hint={`z ${report.snapshot.features.basis_index_z?.toFixed(2) ?? "—"}`} />
          <Stat
            label={L("Realised vol (24h)", "已实现波动率（24 小时）")}
            value={report.snapshot.features.rv_24h != null ? `${(report.snapshot.features.rv_24h * 100).toFixed(0)}%` : "—"}
            hint={L(`pctl ${report.snapshot.features.vol_pctl_90d?.toFixed(0) ?? "—"} · ${report.snapshot.labels.vol_state}`, `百分位 ${report.snapshot.features.vol_pctl_90d?.toFixed(0) ?? "—"} · ${stateWord(lang, report.snapshot.labels.vol_state)}`)}
          />
          <Stat label={L("Trend vs 30d avg", "相对 30 日均线的趋势")} value={fmtPct(report.snapshot.features.trend_sma_pct, 1)} hint={stateWord(lang, report.snapshot.labels.trend_state)} />
          <Stat label={L("Next earnings", "下次财报")} value={earningsAhead(report.snapshot.features.hours_to_earnings, lang)} hint={L(`FOMC in ${H(report.snapshot.features.hours_to_fomc)}`, `距 FOMC ${H(report.snapshot.features.hours_to_fomc)}`)} />
          <Stat
            label={L("Last SEC filing", "最近一份 SEC 文件")}
            // 720 h is the cap the feature carries, not a measurement: say "over 30 d", not "30 d".
            value={
              report.snapshot.features.hours_since_filing != null
                ? report.snapshot.features.hours_since_filing >= 720
                  ? L("over 30 d ago", "超过 30 天前")
                  : L(`${H(report.snapshot.features.hours_since_filing)} ago`, `${H(report.snapshot.features.hours_since_filing)}前`)
                : "—"
            }
            hint={
              report.snapshot.features.filings_72h
                ? L(`${report.snapshot.features.filings_72h} in the last 72h`, `近 72 小时内 ${report.snapshot.features.filings_72h} 份`)
                : L("none in the last 72h", "近 72 小时内没有")
            }
            tone={report.snapshot.features.filings_72h ? "warning" : undefined}
          />
        </div>
        {flags ? <p className="mt-3 text-[13px] text-muted-foreground">{L("Flags: ", "数据标记：")}{report.snapshot.quality_flags.join(", ")}</p> : null}
      </Section>

      {/* Exit & hedge */}
      <Section
        openAll={openAll}
        collapsible
        summary={
          report.execution.exit_quote?.total_cost_bps != null
            ? L(
                `${fmtBps(report.execution.exit_quote.total_cost_bps)} to exit ${fmtUsd(t.notional_quote)} · ${report.execution.exit_quote.fully_filled ? "fills" : "does not fill"} · largest inside budget ${fmtUsd(report.execution.max_notional_within_budget)}`,
                `平仓 ${fmtUsd(t.notional_quote)} 需 ${fmtBps(report.execution.exit_quote.total_cost_bps)} · ${report.execution.exit_quote.fully_filled ? "可全部成交" : "无法全部成交"} · 预算内最大平仓量 ${fmtUsd(report.execution.max_notional_within_budget)}`,
              )
            : L("no order book available to cost the exit", "没有盘口数据，无法估算平仓成本")
        }
        title={L("Getting out", "平仓")}
        subtitle={L(
          `${report.execution.book_source} order book${report.execution.book_ts ? ` · ${fmtTimeL(report.execution.book_ts, lang)}` : ""}`,
          `${stateWord(lang, report.execution.book_source)}盘口${report.execution.book_ts ? ` · ${fmtTimeL(report.execution.book_ts, lang)}` : ""}`,
        )}
      >
        {report.execution.exit_quote ? (
          <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
            <div className="grid grid-cols-2 gap-2">
              <Stat
                label={L(`Exit ${fmtUsd(report.execution.exit_quote.notional_quote)} USDT`, `平仓 ${fmtUsd(report.execution.exit_quote.notional_quote)} USDT`)}
                value={fmtBps(report.execution.exit_quote.total_cost_bps)}
                hint={L(
                  `${fmtBps(report.execution.exit_quote.walk_cost_bps)} walk + ${report.execution.exit_quote.fee_bps.toFixed(0)} bps fee`,
                  `${fmtBps(report.execution.exit_quote.walk_cost_bps)} 盘口冲击 + ${report.execution.exit_quote.fee_bps.toFixed(0)} bps 手续费`,
                )}
                tone={report.execution.exit_quote.fully_filled ? undefined : "critical"}
              />
              <Stat
                label={L("Fills", "能否成交")}
                value={report.execution.exit_quote.fully_filled ? L("Yes", "是") : L("No", "否")}
                hint={L(`${report.execution.exit_quote.levels_consumed} levels`, `吃掉 ${report.execution.exit_quote.levels_consumed} 档`)}
                tone={report.execution.exit_quote.fully_filled ? "good" : "critical"}
              />
              <Stat
                label={L("Largest exit inside budget", "预算内最大平仓量")}
                value={fmtUsd(report.execution.max_notional_within_budget)}
                hint={L(`USDT that still exits under ${budget} bps`, `平仓成本仍低于 ${budget} bps 的 USDT 数量`)}
              />
              {report.execution.hedge_quote ? (
                <Stat
                  label={L(`Hedge 100% via ${report.execution.hedge_quote.perp_symbol}`, `通过 ${report.execution.hedge_quote.perp_symbol} 100% 对冲`)}
                  value={fmtBps(report.execution.hedge_quote.total_cost_bps_of_position)}
                  hint={L(
                    `fees ${fmtUsd(report.execution.hedge_quote.entry_fee_quote + report.execution.hedge_quote.exit_fee_quote, 2)} USDT · funding ${fmtUsd(report.execution.hedge_quote.funding_quote, 2)} USDT · residual basis p95 ${fmtBps(report.execution.hedge_quote.residual_basis_p95_bps, 0)}`,
                    `手续费 ${fmtUsd(report.execution.hedge_quote.entry_fee_quote + report.execution.hedge_quote.exit_fee_quote, 2)} USDT · 资金费 ${fmtUsd(report.execution.hedge_quote.funding_quote, 2)} USDT · 残余基差 p95 ${fmtBps(report.execution.hedge_quote.residual_basis_p95_bps, 0)}`,
                  )}
                />
              ) : null}
            </div>
            {report.execution.cost_curve ? <CostCurve points={report.execution.cost_curve} requested={t.notional_quote} budgetBps={budget} lang={lang} /> : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{L("No order book was available, so exit cost is unknown. Start the recorder or allow live book fetches.", "没有可用的盘口数据，所以平仓成本未知。请启动记录器，或允许实时获取盘口。")}</p>
        )}
        <LiquidityByTimeOfWeek report={report} lang={lang} />
        <ClosedHoursNote report={report} lang={lang} />
      </Section>

      {/* Gate + caps */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Section
          openAll={openAll}
          collapsible
          summary={L(
            `${report.gate.rules.filter((r) => r.decision === "GO").length} of ${report.gate.rules.length} checks passed`,
            `${report.gate.rules.length} 项检查中有 ${report.gate.rules.filter((r) => r.decision === "GO").length} 项通过`,
          )}
          title={L(`Discipline gate · ${verdictLabel(lang, report.gate.decision)}`, `纪律闸门 · ${verdictLabel(lang, report.gate.decision)}`)}
          subtitle={
            report.gate.risk_quote != null ? L(`Risk at stake ${fmtUsd(report.gate.risk_quote)} (${report.gate.risk_basis})`, `面临的风险 ${fmtUsd(report.gate.risk_quote)}（${riskBasis(lang, report.gate.risk_basis)}）`) : undefined
          }
        >
          {report.gate.decision === "GO" && (report.verdict.verdict === "REDUCE_TO" || report.verdict.verdict === "HEDGE") ? (
            <p className="mb-2 text-[13px] text-muted-foreground">
              {L("The gate passed every check; the size cap, not the gate, is what reduced the answer.", "闸门的每项检查都通过了；改变结论的是仓位上限，而不是闸门。")}
            </p>
          ) : null}
          <ul className="space-y-2">
            {report.gate.rules.map((r) => (
              <li key={r.rule} className="flex items-start gap-2 text-sm">
                {r.decision === "GO" ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-status-good" aria-label={L("passed", "通过")} />
                ) : r.decision === "REVIEW_REQUIRED" ? (
                  <CircleHelp className="mt-0.5 h-4 w-4 shrink-0 text-status-warning" aria-label={L("needs review", "需要复核")} />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-status-critical" aria-label={L("failed", "未通过")} />
                )}
                <span>
                  <span className="font-medium">{tl(lang, "rule", r.rule)}</span>
                  <span className="text-muted-foreground"> — {r.reason}</span>
                </span>
              </li>
            ))}
          </ul>
        </Section>
        <Section
          openAll={openAll}
          collapsible
          summary={
            bindingCap(report)
              ? L(
                  `${tl(lang, "cap", bindingCap(report)!.name)} binds at ${fmtUsd(bindingCap(report)!.notional as number)}`,
                  `${tl(lang, "cap", bindingCap(report)!.name)}是限制项，上限 ${fmtUsd(bindingCap(report)!.notional as number)}`,
                )
              : L(`${report.sizing.caps.length} caps, none cuts the request`, `${report.sizing.caps.length} 项上限，没有一项削减你的请求`)
          }
          title={L("Sizing caps", "仓位上限")}
          subtitle={
            report.verdict.recommended_notional != null && report.verdict.recommended_notional < t.notional_quote - 1
              ? L("The smallest cap binds. Each one is independent and named.", "取最小的那个上限。每一项都是独立的，并且有名称。")
              : L("Each one is independent and named. None of them cuts the requested size.", "每一项都是独立的，并且有名称。没有一项削减所请求的仓位。")
          }
        >
          <ul className="space-y-2">
            {report.sizing.caps.map((c) => {
              // A cap only binds if it actually cuts the request. The smallest cap is often
              // the regime one at a multiplier of 1.00, and labelling that "binds" reads as
              // though the desk is limiting you to exactly the size you asked for.
              const binding = c.name === report.sizing.binding_cap && c.notional != null && c.notional < t.notional_quote - 1;
              const max = Math.max(t.notional_quote, ...report.sizing.caps.map((x) => x.notional ?? 0));
              const width = c.notional == null ? 0 : Math.min(100, (c.notional / max) * 100);
              return (
                <li key={c.name} className="space-y-1">
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className={binding ? "font-semibold" : ""}>
                      {tl(lang, "cap", c.name)}
                      {binding ? <Pill tone="warning">{L("binds", "限制项")}</Pill> : null}
                    </span>
                    <span className="tabular text-muted-foreground">{c.notional == null ? L("n/a", "不适用") : fmtUsd(c.notional)}</span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-muted" aria-hidden>
                    <div className={`h-1.5 rounded-full ${binding ? "bg-status-warning" : "bg-chart-1"}`} style={{ width: `${width}%` }} />
                  </div>
                  <p className="text-[13px] text-muted-foreground">{capDetail(c.detail, lang)}</p>
                </li>
              );
            })}
          </ul>
        </Section>
      </div>

      {/* The case against */}
      <SecondOpinionSection report={report} openAll={openAll} lang={lang} />

      {/* The coarse map */}
      <RegimeSection report={report} openAll={openAll} lang={lang} />

      {/* What would change it */}
      <SensitivitySection report={report} openAll={openAll} lang={lang} />

      </Group>

      <Group title={L("Your book", "你的组合")} hint={L("How this trade sits next to what you already hold, your own record, what happened last time", "这笔交易与你已有持仓的关系、你自己的记录、上次发生了什么")} openAll={openAll}>
      {/* The whole book */}
      <PortfolioSection report={report} openAll={openAll} lang={lang} />

      {/* The trader's own record */}
      <BreakerStrip report={report} openAll={openAll} lang={lang} />

      {/* What happened last time */}
      <LessonsSection report={report} openAll={openAll} lang={lang} />

      </Group>

      <Group title={L("Alerts & plan", "提醒与计划")} hint={L("The plan to follow, a tripwire, watching this verdict, your feedback", "要遵守的计划、触发提醒、关注这个结论、你的反馈")} openAll={openAll}>
        {report.forecast_id != null && report.forecast_id > 0 ? <PlanCard forecastId={report.forecast_id} lang={lang} openAll={openAll} /> : null}
        {report.forecast_id != null && report.forecast_id > 0 ? (
          <div className="space-y-3">
            <Feedback forecastId={report.forecast_id} lang={lang} />
            <WatchButton forecastId={report.forecast_id} lang={lang} />
            <TripwireButton forecastId={report.forecast_id} ticker={report.ticket.ticker} lang={lang} />
          </div>
        ) : null}
      </Group>

      <Group title={L("Research", "研究")} hint={L("What the street says, Bitget signal, the book contrast", "市场观点、Bitget 信号、组合对比")} openAll={openAll}>
        <StreetSection report={report} openAll={openAll} lang={lang} />
        <BitgetSection report={report} openAll={openAll} lang={lang} />
        <SignalLine report={report} lang={lang} />
        <BookContrast ticket={report.ticket} lang={lang} />
      </Group>

      <p className="flex flex-wrap items-center gap-x-2 text-[13px] text-muted-foreground">
        <span>
          {L(`Computed in ${report.timings_ms.total} ms · sources: `, `计算耗时 ${report.timings_ms.total} 毫秒 · 数据来源：`)}
          {report.sources
            .map((s) => sourceLine(s, report.as_of, lang))
            .join(lang === "zh" ? "、" : ", ")}
          {report.forecast_id != null && report.forecast_id > 0 ? L(` · journaled as forecast #${report.forecast_id}`, ` · 已记入日志，预测编号 #${report.forecast_id}`) : ""}
          {report.forecast_id != null && report.forecast_id < 0 ? L(" · a what-if: not journaled, never scored", " · 假设情景：不记入日志，也不评分") : ""}
        </span>
        {report.receipt && report.forecast_id != null && report.forecast_id > 0 ? (
          <a
            href={`/api/verify/${report.forecast_id}`}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-muted-foreground underline underline-offset-2 hover:text-foreground"
            title={L(`Receipt ${report.receipt}: chained to every verdict before it`, `回执 ${report.receipt}：与此前的每一条结论链接在一起`)}
          >
            {L("Receipt ✓", "回执 ✓")}
          </a>
        ) : null}
        {report.forecast_id != null && report.forecast_id > 0 ? <Permalink forecastId={report.forecast_id} lang={lang} /> : null}
      </p>
      {primary ? null : null}
    </div>
  );
}

/** What the search was narrowed to, said plainly, with the cost in evidence.
 *
 *  A narrowed cohort answers a different question from the unfiltered one, so it can
 *  never be invisible: the page names the conditions, prints the definition each one
 *  resolved to, and says how much history is left. When the request could not be
 *  honoured it says that instead of quietly answering the wider question.
 */
function LensNote({ report, onUnfiltered, lang }: { report: Report; onUnfiltered?: () => void; lang: Lang }) {
  const L = tr(lang);
  const l = report.analog?.lens;
  if (!l || !l.lenses.length) return null;
  const share = l.n_before > 0 ? l.n_after / l.n_before : 0;
  return (
    <div className={`mb-4 rounded-lg border p-3 text-sm ${l.applied ? "border-primary/40 bg-primary/5" : "border-status-warning/40 bg-status-warning/5"}`}>
      <p className="font-medium">
        {l.applied ? <>{L("Narrowed to ", "已缩小范围至：")}{l.description}</> : <>{L("Could not narrow to ", "无法缩小范围至：")}{l.description}</>}
        {l.auto ? <span className="ml-2 rounded bg-primary/15 px-1.5 py-0.5 text-xs font-normal">{L("automatic", "自动")}</span> : null}
      </p>
      {l.auto ? (
        <p className="mt-1 text-[13px] text-muted-foreground">
          {L(`The desk ${l.auto.replace(/^narrowed/, "narrowed this")}. The evidence is on the`, `系统自动缩小了检索范围：${l.auto}。证据见`)}{" "}
          <Link href="/studies" className="underline underline-offset-2 hover:text-foreground">
            {L("studies page", "研究页面")}
          </Link>
          {L(".", "。")}
          {onUnfiltered ? (
            <>
              {" "}
              <button
                type="button"
                onClick={onUnfiltered}
                className="rounded underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                {L("Show the unfiltered answer instead", "改为查看未筛选的结果")}
              </button>
            </>
          ) : null}
        </p>
      ) : null}
      {l.applied ? (
        <p className="mt-1 text-[13px] text-muted-foreground">
          {L(
            `${l.n_after.toLocaleString()} of ${l.n_before.toLocaleString()} past hours qualify (${(share * 100).toFixed(1)}%). Everything below is that cohort, not the general one — the distance ranking happened inside it.`,
            `${l.n_before.toLocaleString()} 个历史小时中有 ${l.n_after.toLocaleString()} 个符合条件（${(share * 100).toFixed(1)}%）。下面的一切都基于这个子集，而不是全部历史——相似度排序也是在这个子集内部进行的。`,
          )}
        </p>
      ) : (
        <p className="mt-1 text-[13px] text-muted-foreground">{l.refused || L("the filter left too little history to search", "筛选之后剩下的历史太少，无法检索")}</p>
      )}
      <ul className="mt-2 space-y-0.5 text-[13px] text-muted-foreground">
        {l.lenses.map((x) => (
          <li key={x.name}>
            <span className="text-foreground">{x.label}</span> — {x.definition}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AnalogSection({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const H = (h: number | null | undefined) => fmtHoursL(h, lang);
  const a = report.analog;
  if (!a || !a.result.ok) {
    return (
      <Section title={L("What history says", "历史怎么说")} subtitle={L("Nearest past moments to now", "与当下最接近的历史时刻")}>
        <p className="text-sm text-muted-foreground">
          {L(`No analog cohort: ${a?.result.reason ?? "search did not run"}. The verdict uses the stop for risk.`, `没有可比的历史样本：${a?.result.reason ?? "检索没有运行"}。结论改用止损来衡量风险。`)}
        </p>
      </Section>
    );
  }
  const primary = a.horizons[report.primary_horizon];
  const values = a.matches_outcomes.map((m) => m.outcomes[report.primary_horizon]?.ret_pct).filter((x): x is number => typeof x === "number");
  const c = primary?.cohort;
  const markers =
    c && !c.insufficient
      ? [
          { value: (primary?.p5_adjusted ?? c.p5) as number, label: primary?.p5_adjusted != null ? L("p5 cal.", "p5 校准") : "p5" },
          { value: c.median_pct as number, label: L("median", "中位数") },
          { value: (primary?.p95_adjusted ?? c.p95) as number, label: primary?.p95_adjusted != null ? L("p95 cal.", "p95 校准") : "p95" },
        ]
      : [];
  // The histogram and the tiles are the token's move; a short loses when it rises, so its
  // one-in-twenty loss is the upper tail and the tiles say which way hurts.
  const short = report.ticket.side === "short";
  const p5shown = primary?.loss_p5_pct ?? primary?.p5_adjusted ?? c?.p5 ?? null;
  const wins = primary?.pnl_win_rate ?? c?.win_rate ?? null;
  const nMatches = a.result.matches.length;
  return (
    <Section
      openAll={openAll}
      collapsible
      summary={
        c && !c.insufficient
          ? L(
              `${nMatches} past moments · median ${fmtPct(c.median_pct, 1)} · ${short ? "the position's " : ""}one in twenty worse than ${fmtPct(p5shown, 1)} · went this position's way ${wins != null ? `${(wins * 100).toFixed(0)}%` : "—"} of the time`,
              `${nMatches} 个历史时刻 · 中位数 ${fmtPct(c.median_pct, 1)} · ${short ? "该仓位" : ""}二十分之一的坏情况比 ${fmtPct(p5shown, 1)} 更差 · 有 ${wins != null ? `${(wins * 100).toFixed(0)}%` : "—"} 的时间朝这个仓位的方向走`,
            )
          : L("not enough distinct matches to answer", "互不相同的匹配样本太少，无法回答")
      }
      title={L("What history says", "历史怎么说")}
      subtitle={L(
        `${nMatches} distinct past moments most like now (${a.scope === "pooled" ? "pooled across tokens" : "same token"}; ${a.result.n_candidates.toLocaleString()} candidate hours, ${a.result.n_distinct_available.toLocaleString()} distinct)`,
        `与当下最像的 ${nMatches} 个互不相同的历史时刻（${a.scope === "pooled" ? "跨代币汇总" : "同一代币"}；${a.result.n_candidates.toLocaleString()} 个候选小时，其中 ${a.result.n_distinct_available.toLocaleString()} 个互不相同）`,
      )}
    >
      {c && !c.insufficient ? (
        <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
          <div>
            <Histogram
              values={values}
              markers={markers}
              lang={lang}
              ariaLabel={L(
                `Distribution of token returns over ${report.primary_horizon} after the ${nMatches} most similar past moments`,
                `最相似的 ${nMatches} 个历史时刻之后 ${report.primary_horizon} 内的代币收益分布`,
              )}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Stat
              label={L(`Typical outcome over ${report.primary_horizon}`, `${report.primary_horizon} 内的典型结果`)}
              value={fmtPct(c.median_pct)}
              chip={<SourceChip entry={report.provenance?.items.analog} lang={lang} />}
              hint={L(`mean ${fmtPct(c.mean_pct)} [${fmtPct(c.ci_mean?.low)}, ${fmtPct(c.ci_mean?.high)}]`, `均值 ${fmtPct(c.mean_pct)} [${fmtPct(c.ci_mean?.low)}, ${fmtPct(c.ci_mean?.high)}]`)}
            />
            <Stat
              label={L("Ended up", "最终收涨")}
              value={fmtRatio(c.win_rate)}
              hint={L(`of ${c.n} similar past moments${c.n_pending ? `, ${c.n_pending} still open` : ""}`, `共 ${c.n} 个类似的历史时刻${c.n_pending ? `，其中 ${c.n_pending} 个尚未结束` : ""}`)}
            />
            {primary?.p5_adjusted != null ? (
              <Stat
                label={short ? L("Stock falls, 1 in 20 (your gain)", "股票下跌，二十分之一（你的收益）") : L("Bad night, 1 in 20", "二十分之一的坏情况")}
                value={fmtPct(primary.p5_adjusted)}
                hint={L(
                  `before the safety margin ${fmtPct(c.p5)} · widened ×${primary.adjustment?.k_lo?.toFixed(2) ?? "—"}${primary.adjustment?.c_lo ? ` and a ${primary.adjustment.c_lo.toFixed(1)}-point floor` : ""} from ${primary.adjustment?.n_fit} scored replays`,
                  `加安全边际之前 ${fmtPct(c.p5)} · 放宽 ×${primary.adjustment?.k_lo?.toFixed(2) ?? "—"}${primary.adjustment?.c_lo ? `，并设 ${primary.adjustment.c_lo.toFixed(1)} 个百分点的下限` : ""}，依据 ${primary.adjustment?.n_fit} 次已评分的回放`,
                )}
                tone={short ? "good" : "critical"}
                chip={<SourceChip entry={report.provenance?.items.loss_line} lang={lang} />}
              />
            ) : (
              <Stat
                label={short ? L("Stock falls, 1 in 20 (your gain)", "股票下跌，二十分之一（你的收益）") : L("Bad night, 1 in 20", "二十分之一的坏情况")}
                value={fmtPct(c.p5)}
                hint={L(`likely range [${fmtPct(c.ci_p5?.low)}, ${fmtPct(c.ci_p5?.high)}]`, `可能的区间 [${fmtPct(c.ci_p5?.low)}, ${fmtPct(c.ci_p5?.high)}]`)}
                tone={short ? "good" : "critical"}
              />
            )}
            <Stat
              label={short ? L("Stock's worst 5%, on average", "股票最差 5% 情况的平均值") : L("Average of the worst 5%", "最差 5% 情况的平均值")}
              value={fmtPct(c.es5_pct)}
              hint={c.es5_n ? L(`${c.es5_n} episode${c.es5_n === 1 ? "" : "s"} below p5`, `${c.es5_n} 次低于 p5`) : undefined}
              tone={short ? undefined : "critical"}
            />
            <Stat
              label={short ? L("Stock's deepest dip during the hold, 1 in 20", "持有期内股票的最深回撤，二十分之一") : L("Deepest dip during the hold, 1 in 20", "持有期内的最深回撤，二十分之一")}
              value={fmtPct(c.mae_p5_pct)}
              hint={L(`median worst ${fmtPct(c.mae_median_pct)}`, `最差情况的中位数 ${fmtPct(c.mae_median_pct)}`)}
            />
            {primary?.p95_adjusted != null ? (
              <Stat
                label={short ? L("Stock rises, 1 in 20 (your loss)", "股票上涨，二十分之一（你的亏损）") : L("Good night, 1 in 20", "二十分之一的好情况")}
                value={fmtPct(primary.p95_adjusted)}
                hint={L(`before the safety margin ${fmtPct(c.p95)} · ×${primary.adjustment?.k_hi?.toFixed(2) ?? "—"}`, `加安全边际之前 ${fmtPct(c.p95)} · ×${primary.adjustment?.k_hi?.toFixed(2) ?? "—"}`)}
                tone={short ? "critical" : "good"}
              />
            ) : (
              <Stat
                label={short ? L("Stock rises, 1 in 20 (your loss)", "股票上涨，二十分之一（你的亏损）") : L("Good night, 1 in 20", "二十分之一的好情况")}
                value={fmtPct(c.p95)}
                tone={short ? "critical" : "good"}
              />
            )}
            <Stat label={L("Widest gap to fair value, 1 in 20", "与公允价值的最大差距，二十分之一")} value={fmtBps(c.max_abs_basis_p95_bps, 0)} hint={L("inside the window", "在窗口之内")} />
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {L(
            `Cohort for ${report.primary_horizon} is below the minimum sample (n = ${c?.n ?? 0}). No distribution is shown.`,
            `${report.primary_horizon} 的样本数低于最低要求（n = ${c?.n ?? 0}），不显示分布。`,
          )}
        </p>
      )}

      {a.paths?.paths.length ? (
        <div className="mt-6">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="text-sm font-medium">{L("The scenarios themselves", "情景本身")}</p>
            <p className="text-[13px] text-muted-foreground">
              {a.paths.stop_pct != null ? (
                <>
                  <span className={a.paths.stopped ? "text-status-warning" : "text-status-good"}>
                    {L(`${a.paths.stopped} of ${a.paths.paths.length}`, `${a.paths.paths.length} 条中有 ${a.paths.stopped} 条`)}
                  </span>{" "}
                  {L("would have taken out your stop before the horizon", "会在期限之前触发你的止损")}
                </>
              ) : (
                L("no stop given, so none is drawn", "没有设置止损，所以没有画出止损线")
              )}
            </p>
          </div>
          <Scenarios paths={a.paths} horizonLabel={report.primary_horizon} lang={lang} />
          <p className="mt-2 text-[13px] text-muted-foreground">
            {L(
              `Each line is one of the retrieved moments, replayed from its own entry over the same ${H(report.horizon_h)} you are holding for. The histogram above is where these lines end up; this is how they got there — which is the difference between a slow bleed and a round trip that takes out a stop on the way to an unremarkable close.`,
              `每条线是检索到的一个历史时刻，从它自己的入场点开始，按你计划持有的同样 ${H(report.horizon_h)} 重放。上面的直方图是这些线最终落在哪里；这张图则是它们怎么走到那里的——这正是缓慢阴跌，与中途打掉止损、最后却收在平平无奇位置的一去一回之间的区别。`,
            )}
          </p>
        </div>
      ) : null}

      <div className="mt-4 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{L("Horizon", "周期")}</TableHead>
              <TableHead className="text-right">n</TableHead>
              <TableHead className="text-right">{L("Median", "中位数")}</TableHead>
              <TableHead className="text-right">p5</TableHead>
              <TableHead className="text-right">p95</TableHead>
              <TableHead className="text-right">{L("Win", "胜率")}</TableHead>
              <TableHead className="text-right">{L("vs random hours", "对比随机时段")}</TableHead>
              <TableHead>{L("Outcomes", "结果类型")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Object.values(a.horizons).map((h) => (
              <TableRow key={h.horizon} className={h.horizon === report.primary_horizon ? "bg-accent/40" : ""}>
                <TableCell className="font-medium">
                  {titleCase(h.horizon)} <span className="text-muted-foreground">({H(h.hours)})</span>
                </TableCell>
                <TableCell className="tabular text-right">{h.cohort.n}</TableCell>
                <TableCell className="tabular text-right">{h.cohort.insufficient ? "—" : fmtPct(h.cohort.median_pct)}</TableCell>
                <TableCell className="tabular text-right">{h.cohort.insufficient ? "—" : fmtPct(h.cohort.p5)}</TableCell>
                <TableCell className="tabular text-right">{h.cohort.insufficient ? "—" : fmtPct(h.cohort.p95)}</TableCell>
                <TableCell className="tabular text-right">{h.cohort.insufficient ? "—" : fmtRatio(h.cohort.win_rate)}</TableCell>
                <TableCell className="tabular text-right">
                  {h.baseline?.mean_diff_pct != null ? (
                    <span>
                      {fmtPct(h.baseline.mean_diff_pct)} <span className="text-muted-foreground">(p = {h.baseline.permutation_p_value?.toFixed(2)})</span>
                    </span>
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell className="text-[13px] text-muted-foreground">
                  {Object.entries(h.cohort.tag_counts)
                    .sort((x, y) => y[1] - x[1])
                    .map(([k, n]) => `${titleCase(k.toLowerCase())} ${n}`)
                    .join(" · ")}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ClosestMoments report={report} lang={lang} />
    </Section>
  );
}

/** The retrieved scenarios themselves: when they were, why they matched, what followed. */
// The search features in plain words, for saying why a past moment counts as similar.
const words = (lang: Lang, fs?: string[]) => (fs ?? []).map((f) => STRINGS[lang].feature[f] ?? STRINGS.en.feature[f] ?? f.replace(/_/g, " ")).join(lang === "zh" ? "、" : ", ");

function ClosestMoments({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const a = report.analog;
  const [open, setOpen] = useState(false);
  if (!a || !a.result.ok || a.result.matches.length === 0) return null;
  const byTs = new Map(a.matches_outcomes.map((m) => [m.ts, m]));
  const shown = open ? a.result.matches : a.result.matches.slice(0, 6);
  const f = (v: number | undefined, digits = 2) => (v == null || Number.isNaN(v) ? "—" : v.toFixed(digits));
  return (
    <div className="mt-4">
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <p className="text-xs font-medium text-muted-foreground">
          {L(
            `The moments themselves · matched on ${a.result.features_used.length} features${a.result.features_dropped.length ? `, ${a.result.features_dropped.length} dropped as constant` : ""}`,
            `这些时刻本身 · 按 ${a.result.features_used.length} 个特征匹配${a.result.features_dropped.length ? `，另有 ${a.result.features_dropped.length} 个因恒定不变而剔除` : ""}`,
          )}
        </p>
        <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)}>
          {open ? L("Show fewer", "收起") : L(`Show all ${a.result.matches.length}`, `显示全部 ${a.result.matches.length} 个`)}
        </Button>
      </div>
      <div className="overflow-x-auto">
        <Table className="min-w-[720px]">
          <TableHeader>
            <TableRow>
              <TableHead>{L("When", "时间")}</TableHead>
              <TableHead>{L("Session", "时段")}</TableHead>
              <TableHead className="text-right">{L("Similarity", "相似度")}</TableHead>
              <TableHead className="text-right">{L("Vol pctl", "波动率分位")}</TableHead>
              <TableHead className="text-right">{L("Basis z", "基差 z")}</TableHead>
              <TableHead className="text-right">{L("Trend", "趋势")}</TableHead>
              <TableHead className="text-right">{L("To earnings", "距财报")}</TableHead>
              <TableHead className="text-right">{L("What followed", "之后的结果")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {a.result.query ? (
              <TableRow className="bg-muted/40">
                <TableCell className="font-medium">{L("Now", "现在")}</TableCell>
                <TableCell className="text-[13px] text-muted-foreground">{tl(lang, "bucket", report.snapshot.labels.bucket)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">—</TableCell>
                <TableCell className="tabular text-right font-medium">{f(a.result.query.vol_pctl_90d, 0)}</TableCell>
                <TableCell className="tabular text-right font-medium">{f(a.result.query.basis_index_z)}</TableCell>
                <TableCell className="tabular text-right font-medium">{fmtPct(a.result.query.trend_sma_pct, 1)}</TableCell>
                <TableCell className="tabular text-right font-medium">
                  {a.result.query.hours_to_earnings == null ? "—" : a.result.query.hours_to_earnings >= 720 ? L("none in 30 d", "30 天内无") : `${a.result.query.hours_to_earnings.toFixed(0)} ${L("h", "小时")}`}
                </TableCell>
                <TableCell className="text-right text-[13px] text-muted-foreground">{L("what we're asking about", "我们正在询问的这一刻")}</TableCell>
              </TableRow>
            ) : null}
            {shown.map((m) => {
              const o = byTs.get(m.ts)?.outcomes[report.primary_horizon];
              const hte = m.features.hours_to_earnings;
              return (
                <TableRow key={`${m.ticker}-${m.ts}`}>
                  <TableCell className="whitespace-nowrap">
                    {fmtTimeL(m.ts, lang)}
                    {m.ticker !== report.ticket.ticker ? <span className="block text-[13px] text-muted-foreground">{m.ticker}</span> : null}
                    {m.alike_on?.length ? <span className="block max-w-[14rem] whitespace-normal text-[13px] text-muted-foreground">{L("alike on ", "相似之处：")}{words(lang, m.alike_on)}</span> : null}
                    {m.differs_on?.length ? <span className="block max-w-[14rem] whitespace-normal text-xs text-status-warning">{L("differs on ", "不同之处：")}{words(lang, m.differs_on)}</span> : null}
                  </TableCell>
                  <TableCell className="text-[13px] text-muted-foreground">{tl(lang, "bucket", m.bucket)}</TableCell>
                  <TableCell className="tabular text-right">{fmtRatio(m.similarity)}</TableCell>
                  <TableCell className="tabular text-right">{f(m.features.vol_pctl_90d, 0)}</TableCell>
                  <TableCell className="tabular text-right">{f(m.features.basis_index_z)}</TableCell>
                  <TableCell className="tabular text-right">{fmtPct(m.features.trend_sma_pct, 1)}</TableCell>
                  <TableCell className="tabular text-right">{hte == null ? "—" : hte >= 720 ? L("none in 30 d", "30 天内无") : `${hte.toFixed(0)} ${L("h", "小时")}`}</TableCell>
                  <TableCell className="tabular text-right">
                    {o?.status === "MATURED" ? (
                      <>
                        <span className={o.ret_pct != null && o.ret_pct < 0 ? "text-status-critical" : "text-status-good"}>{fmtPct(o.ret_pct)}</span>
                        <span className="block text-[13px] text-muted-foreground">{L("worst", "最差")} {fmtPct(o.mae_pct)}</span>
                      </>
                    ) : (
                      <span className="text-muted-foreground">{L("still open", "尚未结束")}</span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

const SIZE_TONE: Record<string, "good" | "warning" | "critical" | "info" | "muted"> = { GO: "good", REDUCE_TO: "warning", HEDGE: "info", NO_GO: "critical", REVIEW: "muted" };

const LESSON_TONE: Record<string, "good" | "warning" | "critical" | "info" | "muted"> = {
  worse_than_stress: "critical",
  bad_tail: "warning",
  as_expected: "muted",
  good_tail: "info",
  better_than_forecast: "good",
  no_distribution: "muted",
};

function SecondOpinionSection({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const so = report.second_opinion;
  if (!so || (so.against.length === 0 && so.supporting.length === 0)) return null;
  const largest = so.against[0]?.magnitude_quote != null ? fmtUsd(Math.abs(so.against[0].magnitude_quote)) : null;
  return (
    <Section
      openAll={openAll}
      collapsible
      summary={L(
        `${so.against.length} point${so.against.length === 1 ? "" : "s"} against${largest != null ? `, the largest worth ${largest}` : ""}${so.supporting.length ? ` · ${so.supporting.length} for` : ""}`,
        `${so.against.length} 条反对${largest != null ? `，最大的一条价值 ${largest}` : ""}${so.supporting.length ? ` · ${so.supporting.length} 条支持` : ""}`,
      )}
      title={L("The case against this", "反对这笔交易的理由")}
      subtitle={so.summary}
    >
      <ul className="space-y-2">
        {so.against.map((c) => (
          <li key={c.text} className="flex gap-2 text-sm">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-status-critical" aria-hidden />
            <span>
              {c.text} <span className="text-[13px] text-muted-foreground">{sourceName(lang, c.source)}</span>
            </span>
          </li>
        ))}
        {so.supporting.map((c) => (
          <li key={c.text} className="flex gap-2 text-sm">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-status-good" aria-hidden />
            <span>
              {c.text} <span className="text-[13px] text-muted-foreground">{sourceName(lang, c.source)}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[13px] text-muted-foreground">
        {L(
          "Every point quotes a number from this report. Ranked by what it is worth in money, with one point from each source before any source repeats.",
          "每一条都引用了本报告里的数字。按折算成金额的大小排序，每个来源先各取一条，然后才轮到重复的来源。",
        )}
      </p>
    </Section>
  );
}

/** The recorded archive: is the book always this good, or only right now? */
/** One measured line about the hours the US market is shut, from the committed closed-hours
 *  study (/studies). Fetched on its own so the report, which is hashed and journaled, is not
 *  changed by a number that is re-measured; absent if the study has nothing for this token. */
function ClosedHoursNote({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const [d, setD] = useState<ClosedHoursLine | null>(null);
  const ticker = report.ticket.ticker;
  useEffect(() => {
    let live = true;
    api
      .closedHours(ticker)
      .then((r) => live && setD(r))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [ticker]);
  const n = d?.numbers;
  if (!n) return null;
  const kept = n.weekend_slope_open;
  const band = n.closed_share_lo != null && n.closed_share_hi != null ? ` (${n.closed_share_lo.toFixed(0)}–${n.closed_share_hi.toFixed(0)}%)` : "";
  const keptBand = n.weekend_slope_lo != null && n.weekend_slope_hi != null ? ` (${(100 * n.weekend_slope_lo).toFixed(0)}–${(100 * n.weekend_slope_hi).toFixed(0)}%)` : "";
  return (
    <p className="mt-4 text-[13px] text-muted-foreground">
      {L(
        `This token made ${n.closed_share_pct.toFixed(0)}%${band} of its price movement (by variance) while the US market was shut, which is ${n.time_share_pct.toFixed(0)}% of the clock (n=${n.n_windows.toLocaleString()} windows).${
          kept != null && n.n_weekends ? ` Across ${n.n_weekends} weekends, Monday's stock open kept ${(100 * kept).toFixed(0)}%${keptBand} of the token's Friday-to-Monday-04:00 move on average; a figure under 100% is partly noise in the token's price.` : ""
        } `,
        `该代币在美国市场休市期间完成了其价格波动（按方差）的 ${n.closed_share_pct.toFixed(0)}%${band}，而休市占时间的 ${n.time_share_pct.toFixed(0)}%（n=${n.n_windows.toLocaleString()} 个窗口）。${
          kept != null && n.n_weekends ? `在 ${n.n_weekends} 个周末里，周一股票开盘平均保留了代币从周五到周一 04:00 涨跌的 ${(100 * kept).toFixed(0)}%${keptBand}；低于 100% 的部分原因是代币价格本身的噪声。` : ""
        }`,
      )}
      <Link href="/studies" className="underline underline-offset-2">
        {L("How this was measured", "测量方法")}
      </Link>
    </p>
  );
}

function LiquidityByTimeOfWeek({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const h = report.execution.liquidity_history;
  if (!h || h.buckets.length === 0) return null;
  const usable = h.buckets.filter((b) => !b.thin);
  if (usable.length === 0) {
    return (
      <p className="mt-4 text-[13px] text-muted-foreground">
        {L(
          `The book archive has ${h.n_snapshots.toLocaleString()} snapshots so far, not yet enough in any one part of the week to compare. It fills in as the recorder runs.`,
          `盘口存档目前有 ${h.n_snapshots.toLocaleString()} 份快照，在一周中的任何一段时间内都还不够用来比较。记录器运行之后会逐渐补齐。`,
        )}
      </p>
    );
  }
  return (
    <div className="mt-4">
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        {L(
          `The same book at other times of the week · ${h.n_snapshots.toLocaleString()} recorded snapshots${h.since ? ` since ${fmtTimeL(h.since, lang)}` : ""}`,
          `同一盘口在一周其他时段的情况 · 共 ${h.n_snapshots.toLocaleString()} 份记录的快照${h.since ? `，自 ${fmtTimeL(h.since, lang)} 起` : ""}`,
        )}
      </p>
      <div className="overflow-x-auto">
        <Table className="min-w-[520px]">
          <TableHeader>
            <TableRow>
              <TableHead>{L("When", "时间")}</TableHead>
              <TableHead className="text-right">{L("Spread", "买卖价差")}</TableHead>
              <TableHead className="text-right">{L("Sellable inside 25 bps", "25 bps 以内可卖出的量")}</TableHead>
              <TableHead className="text-right">{L("Bad case", "坏情况")}</TableHead>
              <TableHead className="text-right">{L(`Too thin for ${fmtUsd(h.reference_notional)}`, `不足以承接 ${fmtUsd(h.reference_notional)} 的占比`)}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {h.buckets.map((b) => (
              <TableRow key={b.bucket}>
                <TableCell>
                  {tl(lang, "bucket", b.bucket)}
                  {b.thin ? <span className="ml-2 text-[13px] text-muted-foreground">{L("thin", "偏薄")}</span> : null}
                </TableCell>
                <TableCell className="tabular text-right">{fmtBps(b.spread_median_bps, 1)}</TableCell>
                <TableCell className="tabular text-right">{fmtUsd(b.depth_25bps_median)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">{fmtUsd(b.depth_25bps_p5)}</TableCell>
                <TableCell className={`tabular text-right ${(b.share_below_reference ?? 0) > 0.25 ? "text-status-warning" : ""}`}>
                  {b.share_below_reference == null ? "—" : fmtPct(b.share_below_reference * 100, 0, false)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {h.note ? <p className="mt-1 text-[13px] text-muted-foreground">{h.note}</p> : null}
    </div>
  );
}

function RegimeSection({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const H = (x: number | null | undefined) => fmtHoursL(x, lang);
  const m = report.regimes;
  if (!m || m.regimes.length === 0) return null;
  const current = m.regimes.find((r) => r.id === m.current) ?? null;
  const nextLikely = m.current != null ? m.transitions[m.current].map((p, j) => ({ j, p })).filter((x) => x.j !== m.current).sort((a, b) => b.p - a.p).slice(0, 2) : [];
  return (
    <Section
      openAll={openAll}
      collapsible
      summary={
        current
          ? L(
              `now: ${current.description} · ${fmtPct(current.share * 100, 0, false)} of the last ${m.n_fitted.toLocaleString()} hours · stays put ${current.persistence != null ? fmtPct(current.persistence * 100, 0, false) : "—"}`,
              `当前：${regimeDescription(lang, current.description)} · 占最近 ${m.n_fitted.toLocaleString()} 小时的 ${fmtPct(current.share * 100, 0, false)} · 保持不变的概率 ${current.persistence != null ? fmtPct(current.persistence * 100, 0, false) : "—"}`,
            )
          : L(`${m.regimes.length} states over ${m.n_fitted.toLocaleString()} hours`, `${m.n_fitted.toLocaleString()} 小时内共 ${m.regimes.length} 个状态`)
      }
      title={L("What kind of market this is", "这是一个什么样的市场")}
      subtitle={L(
        `${m.n_fitted.toLocaleString()} past hours grouped into ${m.regimes.length} states by volatility, gap to fair value, trend and liquidity. Fitted only on hours before this moment, sorted calmest first.`,
        `把过去 ${m.n_fitted.toLocaleString()} 小时按波动率、与公允价值的差距、趋势和流动性分成 ${m.regimes.length} 个状态。只用此刻之前的数据拟合，按从最平静到最动荡排序。`,
      )}
    >
      <div className="overflow-x-auto">
        <Table className="min-w-[720px]">
          <TableHeader>
            <TableRow>
              <TableHead>{L("State", "状态")}</TableHead>
              <TableHead className="text-right">{L("Share of hours", "占比（小时）")}</TableHead>
              <TableHead className="text-right">{L("Stays put", "保持不变")}</TableHead>
              <TableHead className="text-right">{L(`Next ${H(m.horizon_h)}, median`, `未来 ${H(m.horizon_h)}，中位数`)}</TableHead>
              <TableHead className="text-right">{L("Never moved", "从未变动")}</TableHead>
              <TableHead className="text-right">{L(`Next ${H(m.horizon_h)}, p5`, `未来 ${H(m.horizon_h)}，p5`)}</TableHead>
              <TableHead className="text-right">{L("Episodes", "样本数")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {m.regimes.map((r) => (
              <TableRow key={r.id} className={r.id === m.current ? "bg-accent/40" : ""}>
                <TableCell>
                  <span className={r.id === m.current ? "font-semibold" : ""}>{regimeDescription(lang, r.description)}</span>
                  {r.id === m.current ? <span className="ml-2 text-[13px] text-muted-foreground">{L("now", "当前")}</span> : null}
                </TableCell>
                <TableCell className="tabular text-right">{fmtPct(r.share * 100, 0, false)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">{r.persistence == null ? "—" : fmtPct(r.persistence * 100, 0, false)}</TableCell>
                <TableCell className="tabular text-right">{r.next_ret_median_pct == null ? "—" : fmtPct(r.next_ret_median_pct)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">{r.flat_share == null ? "—" : fmtPct(r.flat_share * 100, 0, false)}</TableCell>
                <TableCell className="tabular text-right text-status-critical">{r.next_ret_p5_pct == null ? "—" : fmtPct(r.next_ret_p5_pct)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">{r.n_outcomes.toLocaleString()}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {nextLikely.length ? (
        <p className="mt-2 text-sm text-muted-foreground">
          {L("If it changes, the usual next states are", "如果状态发生变化，通常接下来会转向")}{" "}
          {nextLikely.map((x, i) => (
            <span key={x.j}>
              {i > 0 ? L(" and ", "和") : ""}
              <span className="text-foreground">{regimeDescription(lang, m.regimes.find((r) => r.id === x.j)?.description)}</span> {L("(", "（")}
              {fmtPct(x.p * 100, 0, false)}
              {L(")", "）")}
            </span>
          ))}
          {L(".", "。")}
        </p>
      ) : null}
      <p className="mt-2 text-[13px] text-muted-foreground">
        {lang === "zh"
          ? "中位数接近零，是因为这些代币并不是每个小时都有成交：在“从未变动”占比的那些窗口里，价格结束时停在的，仍是它开始时的最后一笔成交价。仓位计算用的是 p5 这一列。"
          : <>The medians sit on zero because these tokens do not trade every hour: in the &ldquo;never moved&rdquo; share of windows the price ends on the same
        last trade it started on. The p5 column is the one the sizing uses.</>}
      </p>
    </Section>
  );
}

/** What the holdings do to this verdict: the book's bad-case loss before and after, and the book cap when it is the one holding the size down. */
function BookNote({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const p = report.portfolio;
  if (!p) return null;
  const before = p.before.tail_loss_quote;
  const after = p.after.tail_loss_quote;
  const delta = before != null && after != null ? after - before : null;
  return (
    <div className="mt-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
      <p className="font-medium text-foreground">{L("Your book", "你的组合")}</p>
      {before != null && after != null && delta != null ? (
        <p className="text-muted-foreground">
          {L("One-in-twenty loss", "二十分之一的亏损")}{" "}
          <span className="tabular font-medium text-foreground">
            {fmtUsd(Math.abs(before))} → {fmtUsd(Math.abs(after))} USDT
          </span>
          {L(
            `; this trade ${delta < 0 ? "adds" : "removes"} ${fmtUsd(Math.abs(delta))} at the size you asked.`,
            `；这笔交易在你要求的仓位下会${delta < 0 ? "增加" : "减少"} ${fmtUsd(Math.abs(delta))}。`,
          )}
          {p.book_cap_binds && p.book_cap_quote != null ? (
            <>
              {" "}
              <Pill tone="warning">{L("book cap binds", "组合上限生效")}</Pill> {L("The book cap holds it to ", "组合上限把它限制在 ")}
              <span className="tabular font-medium text-foreground">{fmtUsd(p.book_cap_quote)} USDT</span>
              {p.book_cap_pct_of_equity != null ? L(` (${p.book_cap_pct_of_equity}% of equity for the whole book)`, `（整个组合占权益的 ${p.book_cap_pct_of_equity}%）`) : ""}
              {p.tail_after_recommended_quote != null ? L(`, which leaves the book at ${fmtUsd(Math.abs(p.tail_after_recommended_quote))}`, `，此时组合的坏情况亏损为 ${fmtUsd(Math.abs(p.tail_after_recommended_quote))}`) : ""}
              {L(".", "。")}
            </>
          ) : p.book_cap_quote != null ? (
            <> {L(`The book cap (${fmtUsd(p.book_cap_quote)} USDT) does not bind.`, `组合上限（${fmtUsd(p.book_cap_quote)} USDT）没有生效。`)}</>
          ) : null}
        </p>
      ) : (
        <p className="text-muted-foreground">{L("There is not enough stored history to measure the whole book, so no book limit was applied.", "已存的历史数据不足以衡量整个组合，所以没有应用组合限制。")}</p>
      )}
      {p.same_name ? (
        <p className="text-muted-foreground">
          {L(
            `You already hold ${fmtUsd(Math.abs(p.same_name.held_signed_quote))} of ${p.same_name.ticker}; with this trade that name is ${fmtUsd(Math.abs(p.same_name.combined_signed_quote))}${p.same_name.combined_pct_of_equity != null ? ` (${p.same_name.combined_pct_of_equity.toFixed(0)}% of equity)` : ""}.`,
            `你已持有 ${fmtUsd(Math.abs(p.same_name.held_signed_quote))} 的 ${p.same_name.ticker}；加上这笔交易后，该标的为 ${fmtUsd(Math.abs(p.same_name.combined_signed_quote))}${p.same_name.combined_pct_of_equity != null ? `（占权益的 ${p.same_name.combined_pct_of_equity.toFixed(0)}%）` : ""}。`,
          )}
        </p>
      ) : null}
      {p.unknown.length ? (
        <p className="text-status-warning">{L(`No stored history for ${p.unknown.join(", ")}: left out of the tail, not counted as zero.`, `没有 ${p.unknown.join("、")} 的历史数据：已排除在尾部风险计算之外，没有按零处理。`)}</p>
      ) : null}
    </div>
  );
}

function PortfolioSection({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const p = report.portfolio;
  if (!p) return null;
  const added = p.before.tail_loss_quote != null && p.after.tail_loss_quote != null ? p.after.tail_loss_quote - p.before.tail_loss_quote : null;
  const div = p.after.diversification_ratio;
  const n = p.positions.length;
  return (
    <Section
      openAll={openAll}
      collapsible
      summary={L(
        `${n} position${n === 1 ? "" : "s"} · gross ${fmtUsd(p.after.gross_quote)}${added != null ? ` · this trade adds ${fmtUsd(Math.abs(added))} to the bad case` : ""}`,
        `${n} 个持仓 · 总敞口 ${fmtUsd(p.after.gross_quote)}${added != null ? ` · 这笔交易使坏情况亏损增加 ${fmtUsd(Math.abs(added))}` : ""}`,
      )}
      title={L("What it does to the book", "对整个组合的影响")}
      subtitle={L(
        `Your ${n} position${n === 1 ? "" : "s"} together, over ${fmtHoursL(p.horizon_h, lang)}. Correlations are measured on the tokens' own hourly history, not assumed.`,
        `你的 ${n} 个持仓合在一起，持有 ${fmtHoursL(p.horizon_h, lang)}。相关性是根据各代币自己的小时级历史测得的，不是假设出来的。`,
      )}
      action={
        div != null ? (
          <Pill tone={div > 0.9 ? "critical" : div > 0.75 ? "warning" : "good"}>
            {div > 0.9 ? L("one bet", "等于押同一注") : div > 0.75 ? L("thin diversification", "分散度不足") : L("diversified", "分散良好")}
          </Pill>
        ) : null
      }
    >
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="grid grid-cols-2 gap-2">
          <Stat
            label={L("Gross exposure", "总敞口")}
            value={fmtUsd(p.after.gross_quote)}
            hint={
              p.after.gross_pct_of_equity != null
                ? L(`${p.after.gross_pct_of_equity.toFixed(0)}% of equity · was ${fmtUsd(p.before.gross_quote)}`, `占权益的 ${p.after.gross_pct_of_equity.toFixed(0)}% · 之前 ${fmtUsd(p.before.gross_quote)}`)
                : L(`was ${fmtUsd(p.before.gross_quote)}`, `之前 ${fmtUsd(p.before.gross_quote)}`)
            }
          />
          <Stat
            label={L("Net exposure", "净敞口")}
            value={fmtUsd(p.after.net_quote)}
            hint={p.after.net_pct_of_equity != null ? L(`${p.after.net_pct_of_equity.toFixed(0)}% of equity`, `占权益的 ${p.after.net_pct_of_equity.toFixed(0)}%`) : undefined}
          />
          <Stat
            label={L("Largest name", "最大持仓标的")}
            value={p.after.largest_name ?? "—"}
            hint={
              p.after.largest_pct_of_gross != null
                ? L(`${p.after.largest_pct_of_gross.toFixed(0)}% of gross · top three ${p.after.top3_pct_of_gross?.toFixed(0)}%`, `占总敞口的 ${p.after.largest_pct_of_gross.toFixed(0)}% · 前三大合计 ${p.after.top3_pct_of_gross?.toFixed(0)}%`)
                : undefined
            }
            tone={p.after.largest_pct_of_gross != null && p.after.largest_pct_of_gross > 60 ? "warning" : undefined}
          />
          <Stat
            label={L("Whole book, bad night (1 in 20)", "整个组合的坏情况（二十分之一）")}
            value={fmtUsd(p.after.tail_loss_quote)}
            hint={added != null ? L(`this trade adds ${fmtUsd(Math.abs(added))}`, `这笔交易增加 ${fmtUsd(Math.abs(added))}`) : L("needs history for every name", "需要每个标的的历史数据")}
            tone="critical"
          />
          {p.after.standalone_tail_sum_quote != null ? (
            <Stat
              label={L("If the names were independent", "如果各标的互相独立")}
              value={fmtUsd(p.after.standalone_tail_sum_quote)}
              hint={div != null ? L(`the book keeps ${fmtPct(div * 100, 0, false)} of that`, `组合保留其中的 ${fmtPct(div * 100, 0, false)}`) : undefined}
            />
          ) : null}
          {p.mean_correlation_to_book != null ? (
            <Stat
              label={L(`${report.ticket.ticker} vs the book`, `${report.ticket.ticker} 与组合的相关性`)}
              value={p.mean_correlation_to_book.toFixed(2)}
              hint={L("mean measured correlation", "平均实测相关性")}
              tone={p.mean_correlation_to_book > 0.7 ? "warning" : undefined}
            />
          ) : null}
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">{L("Measured correlation", "实测相关性")}</p>
          <div className="overflow-x-auto">
            <Table className="min-w-[320px]">
              <TableHeader>
                <TableRow>
                  <TableHead>{L("Pair", "配对")}</TableHead>
                  <TableHead className="text-right">{L("Correlation", "相关性")}</TableHead>
                  <TableHead className="text-right">{L("Hours", "小时数")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {p.correlations.slice(0, 6).map((c) => (
                  <TableRow key={`${c.a}-${c.b}`}>
                    <TableCell>
                      {c.a} · {c.b}
                    </TableCell>
                    <TableCell className={`tabular text-right ${c.correlation != null && c.correlation > 0.7 ? "text-status-warning" : ""}`}>
                      {c.correlation == null ? L("not enough overlap", "重叠数据不足") : c.correlation.toFixed(2)}
                    </TableCell>
                    <TableCell className="tabular text-right text-muted-foreground">{c.overlap_hours.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
      {p.attribution && p.attribution.book_tail_quote != null ? (
        <div className="mt-4 overflow-x-auto">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            {L(
              `Who carries the bad case · measured in the ${p.attribution.n_windows.toLocaleString()} historical windows where this book was at its worst`,
              `谁承担了坏情况的亏损 · 取自这个组合表现最差的 ${p.attribution.n_windows.toLocaleString()} 个历史窗口`,
            )}
          </p>
          <Table className="min-w-[560px]">
            <TableHeader>
              <TableRow>
                <TableHead>{L("Position", "持仓")}</TableHead>
                <TableHead className="text-right">{L("Weight", "权重")}</TableHead>
                <TableHead className="text-right">{L("Share of the loss", "亏损占比")}</TableHead>
                <TableHead className="text-right">{L("Loss in the bad case", "坏情况下的亏损")}</TableHead>
                <TableHead className="text-right">{L("If you dropped it", "如果把它平掉")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {p.attribution.contributions.map((c) => (
                <TableRow key={`${c.ticker}-${c.side}-${c.notional_quote}`}>
                  <TableCell>
                    <span className="font-medium">{c.ticker}</span> <span className="text-muted-foreground">{lang === "zh" ? tl(lang, "side", c.side) : c.side}</span>
                    <span className="block text-[13px] text-muted-foreground">{fmtUsd(c.notional_quote)}</span>
                  </TableCell>
                  <TableCell className="tabular text-right text-muted-foreground">{fmtPct(c.share_of_gross * 100, 0, false)}</TableCell>
                  <TableCell className={`tabular text-right ${c.component_share != null && c.component_share > c.share_of_gross * 1.25 ? "text-status-warning" : ""}`}>
                    {c.component_share == null ? c.note || L("unknown", "未知") : fmtPct(c.component_share * 100, 0, false)}
                  </TableCell>
                  <TableCell className="tabular text-right">{c.component_quote == null ? "—" : fmtUsd(c.component_quote)}</TableCell>
                  <TableCell className="tabular text-right text-muted-foreground">
                    {c.marginal_quote == null
                      ? "—"
                      : c.marginal_quote < 0
                        ? L(`tail improves ${fmtUsd(Math.abs(c.marginal_quote))}`, `尾部风险改善 ${fmtUsd(Math.abs(c.marginal_quote))}`)
                        : L(`tail worsens ${fmtUsd(Math.abs(c.marginal_quote))}`, `尾部风险恶化 ${fmtUsd(Math.abs(c.marginal_quote))}`)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-1 text-[13px] text-muted-foreground">
            {L(
              "A share of the loss well above the weight means that position is doing more damage than its size suggests.",
              "亏损占比远高于权重，说明这个持仓造成的伤害，比它的仓位大小所显示的更大。",
            )}
          </p>
        </div>
      ) : null}
      {p.stress ? <BookStressView stress={p.stress} lang={lang} /> : null}
      {p.notes.length ? (
        <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
          {p.notes.map((n) => (
            <li key={n}>– {n}</li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}

/** Marking a trade taken is what turns an analysis into part of the loss record. */
function TakenButton({ forecastId, lang, noGo }: { forecastId: number; lang: Lang; noGo?: boolean }) {
  const L = tr(lang);
  const [state, setState] = useState<"idle" | "saving" | "taken" | "error">("idle");
  if (state === "taken") {
    return (
      <p className="mt-4 text-sm text-status-good">
        {L("Logged as taken. It now counts towards your loss limits, and will be scored when the horizon passes.", "已记为已成交。它现在计入你的亏损限额，持有期结束后会被评分。")}{" "}
        <button type="button" className="underline underline-offset-2" onClick={() => { setState("saving"); api.markTaken(forecastId, false).then(() => setState("idle")).catch(() => setState("error")); }}>
          {L("Undo", "撤销")}
        </button>
      </p>
    );
  }
  return (
    <div className="mt-4 flex items-center gap-3">
      <Button
        variant="secondary"
        size="sm"
        disabled={state === "saving"}
        onClick={() => { setState("saving"); api.markTaken(forecastId, true).then(() => setState("taken")).catch(() => setState("error")); }}
      >
        {noGo ? L("I took it anyway", "我还是做了") : L("I took this trade", "我做了这笔交易")}
      </Button>
      <span className="text-[13px] text-muted-foreground">
        {state === "error" ? L("Could not save that. Try again.", "保存失败，请重试。") : L("Only trades you mark are counted by the circuit breaker.", "熔断机制只统计你标记过的交易。")}
      </span>
    </div>
  );
}

function BreakerStrip({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const b = report.breaker;
  if (!b) return null;
  // Nothing to say to someone who has not logged a trade yet.
  if (b.state === "NORMAL" && b.n_taken === 0) return null;
  const tone = b.state === "HALTED" ? "critical" : b.state === "COOLDOWN" ? "warning" : "good";
  const stateName = lang === "en" ? b.state.toLowerCase() : tl(lang, "breaker", b.state);
  return (
    <Section
      openAll={openAll}
      collapsible
      summary={L(
        `${stateName} · ${b.n_taken} trade${b.n_taken === 1 ? "" : "s"} taken${b.losing_streak ? ` · ${b.losing_streak} losing in a row` : ""}`,
        `${stateName} · 已做 ${b.n_taken} 笔交易${b.losing_streak ? ` · 连续亏损 ${b.losing_streak} 笔` : ""}`,
      )}
      title={L("Your recent record", "你最近的交易记录")}
      subtitle={L(
        `${b.n_taken} trade${b.n_taken === 1 ? "" : "s"} marked as taken. Only these count; analyses you did not act on are ignored.`,
        `已标记 ${b.n_taken} 笔交易为已成交。只统计这些；你没有实际操作的分析不计入。`,
      )}
      action={<Pill tone={tone}>{stateName}</Pill>}
    >
      <ul className="mb-3 space-y-1 text-sm text-muted-foreground">
        {b.reasons.map((r) => (
          <li key={r}>– {breakerReason(r, lang)}</li>
        ))}
      </ul>
      <div className="grid grid-cols-3 gap-2">
        {b.windows.map((w) => (
          <Stat
            key={w.name}
            label={L(`Last ${w.name}`, `最近 ${w.name}`)}
            value={fmtUsd(w.realised_quote)}
            hint={
              w.limit_quote != null
                ? L(`${fmtPct((w.used_fraction ?? 0) * 100, 0, false)} of the ${fmtUsd(w.limit_quote)} limit · ${w.n_trades} trades`, `已用 ${fmtUsd(w.limit_quote)} 限额的 ${fmtPct((w.used_fraction ?? 0) * 100, 0, false)} · ${w.n_trades} 笔交易`)
                : L(`${w.n_trades} trades · no limit without equity`, `${w.n_trades} 笔交易 · 没有账户权益，所以没有限额`)
            }
            tone={w.used_fraction != null && w.used_fraction >= 1 ? "critical" : w.used_fraction != null && w.used_fraction >= 0.75 ? "warning" : undefined}
          />
        ))}
      </div>
    </Section>
  );
}

function LessonsSection({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const lessons = report.lessons ?? [];
  if (lessons.length === 0) return null;
  const bad = lessons.filter((l) => l.classification === "worse_than_stress" || l.classification === "bad_tail").length;
  return (
    <Section
      openAll={openAll}
      collapsible
      summary={L(
        `${lessons.length} past call${lessons.length === 1 ? "" : "s"} recalled${bad ? ` · ${bad} finished below the level they were sized against` : " · none breached the level they were sized against"}`,
        `回顾了 ${lessons.length} 次过往判断${bad ? ` · 其中 ${bad} 次的结果低于当时定仓所依据的水平` : " · 没有一次突破当时定仓所依据的水平"}`,
      )}
      title={L("What happened last time", "上一次发生了什么")}
      subtitle={L(
        "Past calls in conditions like these, scored after the fact. Each is one episode, not evidence: the distribution above is what you size against.",
        "在类似条件下的过往判断，事后已评分。每一条只是一个个案，不算证据：定仓依据的是上面的分布。",
      )}
    >
      <ul className="space-y-2">
        {lessons.map((l) => (
          <li key={l.forecast_id} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
            <Pill tone={LESSON_TONE[l.classification] ?? "muted"}>{tl(lang, "lesson", l.classification)}</Pill>
            <span className="flex-1 text-muted-foreground">{l.text}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function SensitivitySection({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const sen = report.sensitivity;
  if (!sen || sen.sizes.length === 0) return null;
  const requested = sen.requested_notional;
  const maxNotional = Math.max(...sen.sizes.map((p) => p.notional));
  return (
    <Section
      openAll={openAll}
      collapsible
      summary={L(
        `${sen.sizes.length} sizes and ${sen.stops.length} stop distances, each re-run through the whole gate${sen.max_go_notional != null ? ` · a GO up to ${fmtUsd(sen.max_go_notional)}` : ""}`,
        `${sen.sizes.length} 档仓位和 ${sen.stops.length} 档止损距离，每一档都完整重跑了一遍闸门${sen.max_go_notional != null ? ` · 最高 ${fmtUsd(sen.max_go_notional)} 仍然可以做` : ""}`,
      )}
      title={L("What would change it", "什么会改变结论")}
      subtitle={L(
        "The same gate, caps and verdict, re-run at other sizes and stops. Nothing here is an estimate of the verdict; it is the verdict.",
        "同样的闸门、上限和结论，在其他仓位和止损下重新运行。这里没有任何一项是对结论的估算，它们就是结论本身。",
      )}
      action={
        sen.max_go_notional != null ? (
          <Pill tone="good">{L(`GO up to ${fmtUsd(sen.max_go_notional)}`, `最高 ${fmtUsd(sen.max_go_notional)} 可以做`)}</Pill>
        ) : (
          <Pill tone="critical">{L("no size is a GO", "没有任何仓位可以做")}</Pill>
        )
      }
    >
      <div className="space-y-4">
        <ul className="space-y-1 text-sm">
          {sen.notes.map((n) => (
            <li key={n} className="text-muted-foreground">
              – {n}
            </li>
          ))}
        </ul>
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">{L("Verdict by size", "不同仓位下的结论")}</p>
          <ul className="space-y-1">
            {sen.sizes.map((p) => {
              const isRequest = Math.abs(p.notional - requested) < 1;
              return (
                <li key={p.notional} className="grid grid-cols-[5.5rem_1fr] items-center gap-x-2 gap-y-0.5 text-xs sm:grid-cols-[5.5rem_8rem_6rem_1fr]">
                  <span className={`tabular text-right ${isRequest ? "font-semibold" : "text-muted-foreground"}`}>
                    {fmtUsd(p.notional)}
                    {isRequest ? <span className="block text-[10px] font-normal text-muted-foreground">{L("requested", "所请求")}</span> : null}
                  </span>
                  <span className="hidden h-2 w-full rounded-full bg-muted sm:block" aria-hidden>
                    <span className="block h-2 rounded-full" style={{ width: `${Math.max(3, (p.notional / maxNotional) * 100)}%`, background: `var(--${p.verdict === "GO" ? "status-good" : p.verdict === "NO_GO" ? "status-critical" : p.verdict === "HEDGE" ? "chart-1" : "status-warning"})` }} />
                  </span>
                  <span className="justify-self-start">
                    <Pill tone={SIZE_TONE[p.verdict] ?? "muted"}>{verdictLabel(lang, p.verdict)}</Pill>
                  </span>
                  <span className="col-span-2 text-muted-foreground sm:col-span-1">
                    {p.binding_cap ? L(`${tl(lang, "cap", p.binding_cap)} binds`, `${tl(lang, "cap", p.binding_cap)}是限制项`) : ""}
                    {p.exit_cost_bps != null ? L(` · exit ${fmtBps(p.exit_cost_bps, 0)}`, ` · 平仓 ${fmtBps(p.exit_cost_bps, 0)}`) : ""}
                    {p.risk_pct_of_equity != null ? L(` · risk ${p.risk_pct_of_equity.toFixed(2)}% of equity`, ` · 风险占权益 ${p.risk_pct_of_equity.toFixed(2)}%`) : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
        {sen.stops.length ? (
          <div className="overflow-x-auto">
            <p className="mb-1 text-xs font-medium text-muted-foreground">{L("Risk by stop distance, at the requested size", "所请求仓位下，不同止损距离的风险")}</p>
            <Table className="min-w-[420px]">
              <TableHeader>
                <TableRow>
                  <TableHead>{L("Stop distance", "止损距离")}</TableHead>
                  <TableHead className="text-right">{L("Stop price", "止损价")}</TableHead>
                  <TableHead className="text-right">{L("Risk, % of equity", "风险，占权益 %")}</TableHead>
                  <TableHead className="text-right">{L("Risk-budget cap", "风险预算上限")}</TableHead>
                  <TableHead className="text-right">{L("Verdict", "结论")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sen.stops.map((p) => (
                  <TableRow key={p.stop_distance_pct}>
                    <TableCell className="tabular">{p.stop_distance_pct.toFixed(2)}%</TableCell>
                    <TableCell className="tabular text-right">{fmtPrice(p.stop_price)}</TableCell>
                    <TableCell className="tabular text-right">{p.risk_pct_of_equity != null ? `${p.risk_pct_of_equity.toFixed(2)}%` : "—"}</TableCell>
                    <TableCell className="tabular text-right">{fmtUsd(p.risk_budget_notional)}</TableCell>
                    <TableCell className="text-right">
                      <Pill tone={SIZE_TONE[p.verdict] ?? "muted"}>{verdictLabel(lang, p.verdict)}</Pill>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </div>
    </Section>
  );
}

function StressSection({ report, openAll, lang }: { report: Report; openAll?: boolean; lang: Lang }) {
  const L = tr(lang);
  const s = report.stress;
  const mc = s.monte_carlo;
  const rows = s.presets.map((p, i) => ({ p, imp: s.impacts[i] }));
  const sevTone = (sev: string): "good" | "warning" | "critical" | "muted" => (sev === "extreme" ? "critical" : sev === "severe" ? "warning" : "muted");
  const w = worstPreset(report);
  const inp = s.inputs_summary;
  const earningsDays = typeof inp.hours_to_earnings === "number" && inp.hours_to_earnings < 700 ? Math.round(inp.hours_to_earnings / 24) : null;
  return (
    <Section
      openAll={openAll}
      collapsible
      summary={L(
        `${s.presets.length} presets from this token's own history${w ? ` · worst ${fmtUsd(w.quote)} (${w.name})` : ""}${mc ? ` · simulated tail ${fmtPct(mc.p5, 1)}` : ""}`,
        `基于该代币自身历史的 ${s.presets.length} 个预设情景${w ? ` · 最坏 ${fmtUsd(w.quote)}（${presetName(lang, w.name, w.zh)}）` : ""}${mc ? ` · 模拟的尾部亏损 ${fmtPct(mc.p5, 1)}` : ""}`,
      )}
      title={L("What could go wrong", "可能会出什么问题")}
      subtitle={L(
        `Presets calibrated from this token's own history: ${inp.closed_windows_n} closed windows, ${inp.earnings_gaps_n} earnings gaps, ${inp.closed_basis_obs_n} closed-hour fair-value gaps${
          inp.earnings_in_window === false ? `. Earnings presets left out: no report falls inside this hold${earningsDays != null ? ` (next in about ${earningsDays} days)` : ""}` : ""
        }`,
        `预设情景根据该代币自身的历史校准：${inp.closed_windows_n} 个休市窗口、${inp.earnings_gaps_n} 次财报跳空、${inp.closed_basis_obs_n} 个休市时段的公允价值差距${
          inp.earnings_in_window === false ? `。已省略财报情景：这次持有期内没有财报${earningsDays != null ? `（下一次约在 ${earningsDays} 天后）` : ""}` : ""
        }`,
      )}
    >
      <div className="space-y-4">
        <div className="overflow-x-auto">
          <Table className="min-w-[560px]">
            <TableHeader>
              <TableRow>
                <TableHead>{L("Scenario", "情景")}</TableHead>
                <TableHead>{L("Severity", "严重程度")}</TableHead>
                <TableHead className="text-right">{L("Shock", "冲击")}</TableHead>
                <TableHead className="text-right">{L("P&L", "盈亏")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ p, imp }) => {
                const breach = Object.entries(imp.breaches).filter(([, v]) => v).map(([k]) => titleCase(k));
                const shock = p.price_move_pct ? fmtPct(p.price_move_pct, 1) : p.basis_shock_bps ? fmtBps(p.basis_shock_bps, 0) : p.depth_multiplier !== 1 ? L(`depth ×${p.depth_multiplier}`, `深度 ×${p.depth_multiplier}`) : p.funding_rate ? `${(p.funding_rate * 1e4).toFixed(1)} bps / 8h` : "—";
                return (
                  <TableRow key={p.id}>
                    <TableCell>
                      <span className="font-medium">{presetName(lang, p.name, p.name_zh)}</span>
                      <span className="block text-[13px] text-muted-foreground">{p.probability_note}</span>
                    </TableCell>
                    <TableCell>
                      <Pill tone={sevTone(p.severity)}>{lang === "zh" ? (STRINGS.zh.severity[p.severity] ?? p.severity) : p.severity}</Pill>
                    </TableCell>
                    <TableCell className="tabular text-right">
                      {shock}
                      <span className="mt-0.5 block">
                        <SourceChip entry={report.provenance?.items.stress?.[p.id]} lang={lang} />
                      </span>
                    </TableCell>
                    <TableCell className="tabular text-right">
                      <span className={imp.total_pct_of_notional != null && imp.total_pct_of_notional < -5 ? "text-status-critical" : ""}>{fmtPct(imp.total_pct_of_notional)}</span>
                      <span className="block text-[13px] text-muted-foreground">
                        {fmtUsd(imp.total_pnl_quote)} {breach.length ? `· ${breach.join(", ")}` : ""}
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {mc ? (
            <>
              <Histogram
                values={mc.terminal_ret_pct}
                bins={mc.terminal_hist}
                markers={[{ value: mc.p5, label: "p5" }, { value: mc.p50, label: "p50" }, { value: mc.p95, label: "p95" }]}
                binCount={40}
                height={180}
                lang={lang}
                ariaLabel={L(`Monte Carlo terminal return distribution over ${mc.horizon_h} hours`, `${mc.horizon_h} 小时内蒙特卡洛模拟的期末收益分布`)}
              />
              <div className="grid grid-cols-2 gap-2 content-start">
                <Stat
                  label={L(`Simulated bad night, 1 in 20 (${mc.horizon_h}h)`, `模拟的二十分之一坏情况（${mc.horizon_h} 小时）`)}
                  value={fmtPct(mc.p5)}
                  hint={L(`${mc.n_paths.toLocaleString()} paths · block bootstrap of ${mc.source_hours.toLocaleString()} hours`, `${mc.n_paths.toLocaleString()} 条路径 · 对 ${mc.source_hours.toLocaleString()} 小时数据做分块自助抽样`)}
                  tone="critical"
                  chip={<SourceChip entry={report.provenance?.items.monte_carlo} lang={lang} />}
                />
                <Stat
                  label={L("Expected shortfall (5%)", "预期缺口（最差 5%）")}
                  value={fmtPct(mc.expected_shortfall_5_pct)}
                  hint={L(`P(loss > 5%) ${fmtRatio(mc.prob_loss_gt["5.0"])}`, `亏损超过 5% 的概率 ${fmtRatio(mc.prob_loss_gt["5.0"])}`)}
                />
                <Stat label={L("Deepest simulated dip, 1 in 20", "模拟的最深回撤，二十分之一")} value={fmtPct(mc.drawdown_p5)} />
                <Stat label={L("Move that loses 5% after costs", "扣除成本后亏损 5% 所需的价格变动")} value={fmtPct(s.reverse_move_pct_for_5pct_loss)} />
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{L("Not enough hourly history for a Monte Carlo over this horizon.", "小时级历史数据不足，无法在这个持有期上做蒙特卡洛模拟。")}</p>
          )}
        </div>
      </div>
    </Section>
  );
}
