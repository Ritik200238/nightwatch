"use client";

import { Pill } from "@/components/report/primitives";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { BookStress, RebalancePlan } from "@/lib/api";
import { fmtLev, fmtUsd } from "@/lib/format";
import { type Lang, tr } from "@/lib/i18n";

const pct = (v: number) => `${v.toFixed(v >= 10 ? 0 : 1)}%`;
const loss = (v: number | null | undefined) => (v == null ? "—" : fmtUsd(Math.abs(v)));

function planTitle(p: RebalancePlan, L: (en: string, zh: string) => string): string {
  const f = p.fraction != null ? `${Math.round(p.fraction * 100)}%` : "";
  switch (p.lever) {
    case "smaller_trade":
      return L(`Take ${p.ticker} at ${fmtUsd(p.amount_quote)}`, `${p.ticker} 只做 ${fmtUsd(p.amount_quote)}`);
    case "skip_trade":
      return L(`Skip the ${p.ticker} trade`, `不做这笔 ${p.ticker}`);
    case "trim_holding":
      return L(`Trim ${p.ticker} by ${f} (${fmtUsd(p.amount_quote)})`, `把 ${p.ticker} 减仓 ${f}（${fmtUsd(p.amount_quote)}）`);
    default:
      return L(`Hedge ${f} of ${p.ticker} (${fmtUsd(p.amount_quote)}) with its Bitget perp`, `用 ${p.ticker} 的 Bitget 永续对冲 ${f}（${fmtUsd(p.amount_quote)}）`);
  }
}

/** The whole book through the crash weeks, a way back inside the limit, and how far it is from the limit. */
export function BookStressView({ stress, lang }: { stress: BookStress; lang: Lang }) {
  const L = tr(lang);
  const { plans, crashes, reverse } = stress;
  const limit = reverse.find((r) => r.key === "limit");
  const ten = reverse.find((r) => r.key === "ten_pct");
  const way = stress.direction === "down" ? L("fall", "下跌") : L("rise", "上涨");
  const hasCrash = crashes.some((c) => c.asked_quote != null);
  if (!plans.length && !hasCrash && !reverse.length) return null;
  const liq = stress.liquidation;
  return (
    <div className="mt-4 space-y-4">
      {stress.breached && stress.limit_quote != null ? (
        <div>
          <p className="mb-1 flex flex-wrap items-center gap-2 text-xs font-medium text-muted-foreground">
            <Pill tone="warning">{L("over the book limit", "超出组合上限")}</Pill>
            {L(
              `Ways back inside ${fmtUsd(stress.limit_quote)} (${stress.limit_pct_of_equity}% of equity), each re-scored on the same ${stress.windows.toLocaleString()} past windows and crash weeks`,
              `回到 ${fmtUsd(stress.limit_quote)}（权益的 ${stress.limit_pct_of_equity}%）以内的办法，每个都在同样的 ${stress.windows.toLocaleString()} 个历史窗口和暴跌周上重新评分`,
            )}
          </p>
          <div className="overflow-x-auto">
            <Table className="min-w-[620px]">
              <TableHeader>
                <TableRow>
                  <TableHead>{L("Plan", "方案")}</TableHead>
                  <TableHead className="text-right">{L("1-in-20 loss", "二十分之一亏损")}</TableHead>
                  <TableHead className="text-right">{L("Worst crash week", "最坏的暴跌周")}</TableHead>
                  <TableHead className="text-right">{L("Cost", "成本")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow>
                  <TableCell className="text-muted-foreground">{L("As asked", "按原计划")}</TableCell>
                  <TableCell className="tabular text-right text-status-critical">{loss(stress.asked_score?.tail_quote)}</TableCell>
                  <TableCell className="tabular text-right text-muted-foreground">{loss(stress.asked_score?.worst_crash_quote)}</TableCell>
                  <TableCell className="tabular text-right text-muted-foreground">—</TableCell>
                </TableRow>
                {plans.map((p) => (
                  <TableRow key={`${p.lever}-${p.ticker}`}>
                    <TableCell>
                      <span className="font-medium">{planTitle(p, L)}</span>
                      {!p.achieves_limit ? (
                        <span className="ml-2">
                          <Pill tone="warning">{L("not enough alone", "单独不够")}</Pill>
                        </span>
                      ) : null}
                      {p.notes.map((n, i) => (
                        <span key={n} className="block text-[13px] text-muted-foreground">
                          {(lang === "zh" && p.notes_zh?.[i]) || n}
                        </span>
                      ))}
                    </TableCell>
                    <TableCell className={`tabular text-right ${p.after.inside_limit ? "text-status-good" : ""}`}>{loss(p.after.tail_quote)}</TableCell>
                    <TableCell className="tabular text-right">{loss(p.after.worst_crash_quote)}</TableCell>
                    <TableCell className="tabular text-right text-muted-foreground">{p.cost_quote > 0 ? `${fmtUsd(p.cost_quote, 2)} ${L("fees", "手续费")}` : L("none", "无")}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="mt-1 text-[13px] text-muted-foreground">
            {L(
              "Had you held it this way instead, this is what the same past would have done. Funding on a perp and tax on a trim are not counted.",
              "如果当初按这种方式持有，同样的历史会带来这样的结果。永续的资金费率和减仓的税费没有计入。",
            )}
          </p>
        </div>
      ) : null}
      {hasCrash ? (
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">{L("The whole book on each crash week's worst market day", "整个组合在每次暴跌周最坏的一天")}</p>
          <div className="overflow-x-auto">
            <Table className="min-w-[520px]">
              <TableHeader>
                <TableRow>
                  <TableHead>{L("Crash", "事件")}</TableHead>
                  <TableHead className="text-right">{L("Book as held", "现有持仓")}</TableHead>
                  <TableHead className="text-right">{L("With this trade", "加上这笔")}</TableHead>
                  <TableHead className="text-right">{L("Hit hardest", "亏最多的")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {crashes.map((c) => (
                  <TableRow key={c.key}>
                    <TableCell>
                      {lang === "zh" && c.name_zh ? c.name_zh : c.name}
                      {c.date ? <span className="block text-[13px] text-muted-foreground">{c.date}</span> : null}
                    </TableCell>
                    <TableCell className="tabular text-right text-muted-foreground">{c.held_quote == null ? "—" : fmtUsd(c.held_quote)}</TableCell>
                    <TableCell className="tabular text-right">
                      {c.asked_quote == null ? "—" : fmtUsd(c.asked_quote)}
                      {c.missing.length ? (
                        <span className="block text-[13px] text-status-warning">{L(`no data: ${c.missing.join(", ")}`, `无数据：${c.missing.join("、")}`)}</span>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">{c.worst_ticker ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      ) : null}
      {limit && stress.direction && limit.shock_pct_after != null ? (
        <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          <p className="font-medium text-foreground">{L("How far from the limit", "离上限还有多远")}</p>
          <p>
            {L(
              `If every name moved together, a ${pct(limit.shock_pct_after)} ${way} costs the book ${fmtUsd(limit.loss_quote)}, the limit${
                limit.shock_pct_before != null ? ` (${pct(limit.shock_pct_before)} before this trade)` : ""
              }. Past windows lost at least that in ${limit.windows_hit_after.toLocaleString()} of ${stress.windows.toLocaleString()}${
                ten && ten.shock_pct_after != null ? `; a ${pct(ten.shock_pct_after)} ${way} costs 10% of equity (${ten.windows_hit_after.toLocaleString()} windows).` : "."
              }`,
              `如果所有标的同步${way}，${pct(limit.shock_pct_after)} 的${way}就会让组合亏掉 ${fmtUsd(limit.loss_quote)}，即上限${
                limit.shock_pct_before != null ? `（加这笔之前是 ${pct(limit.shock_pct_before)}）` : ""
              }。历史上有 ${limit.windows_hit_after.toLocaleString()} / ${stress.windows.toLocaleString()} 个窗口亏损至少这么多${
                ten && ten.shock_pct_after != null ? `；${pct(ten.shock_pct_after)} 的${way}会亏掉 10% 的权益（${ten.windows_hit_after.toLocaleString()} 个窗口）。` : "。"
              }`,
            )}
          </p>
          {liq ? (
            <p>
              {L(
                `The ${fmtLev(liq.leverage)}x ${liq.ticker} leg is liquidated ${pct(liq.distance_pct)} against you${
                  liq.comes_before_limit == null ? "" : liq.comes_before_limit ? ", before the book reaches its limit" : ", after the book has already reached its limit"
                }. At the end of the hold, history was past it in ${liq.windows_hit.toLocaleString()} of ${liq.windows.toLocaleString()} windows (touches along the way are counted in the leverage section).`,
                `${fmtLev(liq.leverage)} 倍的 ${liq.ticker} 仓位在不利方向 ${pct(liq.distance_pct)} 时被强平${
                  liq.comes_before_limit == null ? "" : liq.comes_before_limit ? "，早于组合触及上限" : "，晚于组合触及上限"
                }。持有期结束时，历史上有 ${liq.windows_hit.toLocaleString()} / ${liq.windows.toLocaleString()} 个窗口越过了这一点（途中触及的次数见杠杆部分）。`,
              )}
            </p>
          ) : null}
          <p className="text-[13px]">{L("Holdings are treated as unleveraged; only the new trade's leverage is known.", "已有持仓按无杠杆处理；只知道新交易的杠杆。")}</p>
        </div>
      ) : null}
      {stress.notes.length ? (
        <ul className="space-y-1 text-[13px] text-muted-foreground">
          {stress.notes.map((n, i) => (
            <li key={n}>– {(lang === "zh" && stress.notes_zh?.[i]) || n}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
