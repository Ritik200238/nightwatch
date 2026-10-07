"use client";

import { oiLine } from "@/components/report/market-context";
import { Pill } from "@/components/report/primitives";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { LadderRung, Report, TicketInput } from "@/lib/api";
import { fmtLev, fmtPrice, fmtUsd } from "@/lib/format";
import { type Lang, tr } from "@/lib/i18n";

/** Phone layout of a data cell: the column name sits above the value, from the cell's data-label. */
const CELL =
  "max-sm:flex max-sm:flex-col max-sm:items-start max-sm:p-0 max-sm:text-left max-sm:whitespace-normal max-sm:before:mb-0.5 max-sm:before:text-xs max-sm:before:font-normal max-sm:before:text-muted-foreground max-sm:before:content-[attr(data-label)]";

/** How a rung reads, in words as well as colour: a reader who cannot tell the hues apart
 *  still gets "too risky" or "clear" from the pill. */
function gateLook(gate: LadderRung["gate"], lang: Lang): { tone: "good" | "warning" | "critical"; label: string } {
  const L = tr(lang);
  if (gate === "GO") return { tone: "good", label: L("Liquidation risk: clear", "强平风险：低") };
  if (gate === "NO_GO") return { tone: "critical", label: L("Liquidation risk: too high", "强平风险：过高") };
  return { tone: "warning", label: L("Liquidation risk: review", "强平风险：需复核") };
}

/** The sentence under the table: the highest leverage history calls safe and what holding
 *  the same position at it costs in margin. Every figure comes from the server's ladder. */
function safestLine(l: NonNullable<Report["leverage"]>, rungs: LadderRung[], lang: Lang): string {
  const L = tr(lang);
  const safest = l.safest_leverage;
  const first = rungs[0].leverage;
  const last = rungs[rungs.length - 1].leverage;
  if (safest == null) {
    return L(`No level from ${fmtLev(first)}x to ${fmtLev(last)}x came through clean: each was reached by a past moment, the 1-in-20 loss, or a stress preset.`, `从 ${fmtLev(first)}x 到 ${fmtLev(last)}x，没有一档是安全的：每一档都被过去的某个时刻、二十分之一的亏损或某个压力情景触及。`);
  }
  const rung = rungs.find((r) => r.leverage === safest);
  const of = rung?.analog_of ?? 0;
  const extra = l.safest_extra_margin_quote;
  if (extra == null) {
    return L(
      `${fmtLev(l.leverage)}x has no liquidation risk: none of ${of} past moments like this reached liquidation. The highest level that stays clear is ${fmtLev(safest)}x.`,
      `${fmtLev(l.leverage)}x 没有强平风险：过去 ${of} 个类似时刻没有一个触及强平。仍然安全的最高杠杆是 ${fmtLev(safest)}x。`,
    );
  }
  return L(
    `Safer: at ${fmtLev(safest)}x (${fmtUsd(rung?.margin_quote)} USDT margin, ${fmtUsd(extra)} more than now) none of ${of} past moments like this reached liquidation.`,
    `更稳妥：${fmtLev(safest)}x（保证金 ${fmtUsd(rung?.margin_quote)} USDT，比现在多 ${fmtUsd(extra)}），过去 ${of} 个类似时刻没有一个触及强平。`,
  );
}

/** The same position at other leverage levels: where each liquidates, what it costs in
 *  margin, and how many past moments like this one would have been wiped out. Clicking a
 *  row re-runs the trade at that leverage, so "what would be fine" is one click away. */
export function LeverageSafety({ report, lang, onRerun }: { report: Report; lang: Lang; onRerun?: (patch: Partial<TicketInput>) => void }) {
  const L = tr(lang);
  const l = report.leverage;
  const rungs = l?.ladder ?? [];
  if (!l || !rungs.length) return null;
  return (
    <div className="mt-3 border-l-2 border-border pl-3 text-sm">
      <p className="font-medium text-foreground">{L("Leverage safety", "杠杆安全")}</p>
      <p className="text-[13px] text-muted-foreground">
        {L("The same position at each level, judged on the same past moments. This table judges liquidation risk only; the verdict above also weighs size, risk budget and exit cost.", "同一个仓位在各个杠杆下的情况，用同样的历史时刻来衡量。这张表只判断强平风险；上面的结论还要看仓位大小、风险预算和平仓成本。")}
        {onRerun ? L(" Click a row to re-run at that leverage.", " 点击一行，即可按该杠杆重新运行。") : ""}
      </p>
      {report.open_interest ? <p className="mt-1 text-[13px] text-foreground">{oiLine(report.open_interest, lang)}</p> : null}
      {l.open_interest_crowded_line ? <p className="text-[13px] font-medium text-status-warning">{L(`Crowded: OI ${(report.open_interest?.change_24h_pct ?? 0) >= 0 ? "+" : ""}${(report.open_interest?.change_24h_pct ?? 0).toFixed(0)}% in 24h, a bigger target for a liquidation cascade.`, `拥挤：未平仓量 24 小时 ${(report.open_interest?.change_24h_pct ?? 0) >= 0 ? "+" : ""}${(report.open_interest?.change_24h_pct ?? 0).toFixed(0)}%，更容易引发连环强平。`)}</p> : null}
      {/* On a phone each rung becomes a small card (label above value) so no column is cut off or
          hidden behind a sideways scroll; from sm up it is the plain table. */}
      <Table className="mt-1 max-sm:block" role="table">
        <TableHeader className="max-sm:sr-only">
          <TableRow>
            <TableHead>{L("Leverage", "杠杆")}</TableHead>
            <TableHead className="text-right">{L("Liquidation price", "强平价")}</TableHead>
            <TableHead className="text-right">{L("Distance", "距离")}</TableHead>
            <TableHead className="text-right">{L("Margin", "保证金")}</TableHead>
            <TableHead className="text-right">{L("Past moments liquidated", "曾被强平的历史时刻")}</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody className="max-sm:block">
          {rungs.map((r) => {
            const look = gateLook(r.gate, lang);
            const clickable = !!onRerun && !r.requested;
            return (
              <TableRow
                key={r.leverage}
                aria-current={r.requested ? "true" : undefined}
                onClick={clickable ? () => onRerun?.({ leverage: r.leverage }) : undefined}
                role="row"
                className={`max-sm:grid max-sm:grid-cols-2 max-sm:gap-x-3 max-sm:gap-y-1 max-sm:py-2 ${r.requested ? "bg-primary/10 font-medium" : ""} ${clickable ? "cursor-pointer" : ""}`}
              >
                <TableCell className="max-sm:col-span-2">
                  {clickable ? (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRerun?.({ leverage: r.leverage });
                      }}
                      className="rounded px-1 text-left font-medium underline decoration-dotted underline-offset-4 hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                      aria-label={L(`Re-run at ${fmtLev(r.leverage)}x`, `按 ${fmtLev(r.leverage)}x 重新运行`)}
                    >
                      {fmtLev(r.leverage)}x
                    </button>
                  ) : (
                    <span>
                      {fmtLev(r.leverage)}x <span className="text-xs text-muted-foreground">{L("(yours)", "（你的）")}</span>
                    </span>
                  )}
                </TableCell>
                <TableCell data-label={L("Liquidation price", "强平价")} className={`text-right tabular-nums ${CELL}`}>{fmtPrice(r.liquidation_price)}</TableCell>
                <TableCell data-label={L("Distance", "距离")} className={`text-right tabular-nums ${CELL}`}>{r.distance_pct == null ? "—" : `${r.distance_pct.toFixed(1)}%`}</TableCell>
                <TableCell data-label={L("Margin", "保证金")} className={`text-right tabular-nums ${CELL}`}>{fmtUsd(r.margin_quote)}</TableCell>
                <TableCell data-label={L("Past moments liquidated", "曾被强平的历史时刻")} className={`text-right tabular-nums ${CELL}`}>{r.analog_of ? L(`${r.analog_hits ?? 0} of ${r.analog_of}`, `${r.analog_hits ?? 0} / ${r.analog_of}`) : "—"}</TableCell>
                <TableCell className="text-right max-sm:col-span-2 max-sm:text-left">
                  <Pill tone={look.tone}>{look.label}</Pill>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <p className="mt-1 text-muted-foreground">{safestLine(l, rungs, lang)}</p>
    </div>
  );
}
