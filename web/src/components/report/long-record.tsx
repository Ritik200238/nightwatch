"use client";

import { useEffect, useState } from "react";
import { Section } from "@/components/report/primitives";
import { api, type DeepHistory, type Report } from "@/lib/api";
import { fmtPct } from "@/lib/format";
import { type Lang, tr } from "@/lib/i18n";

const ORDER = ["overnight_gap", "weekend_gap", "one_day", "weekend_close", "five_day"] as const;

function year(d: string | undefined): string {
  return d ? d.slice(0, 4) : "—";
}

/** The stock's own daily record back to listing, beside the desk's line.
 *
 *  The analog search runs on hourly bars from 2025; this is the other half, measured on
 *  every daily bar the provider holds, so a reader can see how big the stock's weekend,
 *  overnight and multi-day moves have been over twenty-odd years and where the desk's
 *  one-in-twenty line sits inside that. It is fetched on its own, read only, and never
 *  feeds the verdict, so the hashed report does not change when it is re-measured. */
export function LongRecord({ report, lang, openAll }: { report: Report; lang: Lang; openAll?: boolean }) {
  const L = tr(lang);
  const [d, setD] = useState<DeepHistory | null>(null);
  const ticker = report.ticket.ticker;
  const side = report.ticket.side === "short" ? "short" : "long";
  const hz = report.analog?.horizons?.[report.primary_horizon];
  const hours = hz?.hours ?? report.horizon_h ?? null;
  // loss_p5_pct is the position's P&L: for a short it is the stock's upper line turned over.
  const pnlLine = hz?.loss_p5_pct ?? null;
  const line = pnlLine == null ? null : side === "short" ? -pnlLine : pnlLine;

  useEffect(() => {
    let live = true;
    api
      .deepHistory(ticker, side, hours, line)
      .then((r) => live && setD(r))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [ticker, side, hours, line]);

  if (!d?.available || !d.windows || !d.chosen || !d.windows[d.chosen]) return null;
  const w = d.windows[d.chosen];
  const share = d.share_beyond;
  const first = year(d.first);
  const rows = ORDER.filter((k) => d.windows?.[k]);
  const worst = w.worst_events[0];
  const winLabel = L(w.label.toLowerCase(), w.label_zh);
  const tail = side === "short" ? L("up", "上涨") : L("down", "下跌");

  return (
    <Section
      tier="default"
      collapsible
      openAll={openAll}
      title={L("The longer record", "更长的历史记录")}
      summary={
        share != null
          ? L(
              `Since ${first}, ${ticker}'s ${winLabel} went past the desk's line in ${(share * 100).toFixed(1)}% of ${w.n.toLocaleString()} cases`,
              `自 ${first} 年以来，${ticker} 的${winLabel}在 ${w.n.toLocaleString()} 次中有 ${(share * 100).toFixed(1)}% 越过了本台的线`,
            )
          : L(`${ticker} daily bars since ${first}`, `${ticker} 自 ${first} 年以来的日线`)
      }
    >
      <p className="max-w-prose text-sm text-muted-foreground">
        {L(
          `The similar-moment search above uses hourly bars from 2025. This is the same stock on every daily bar the data provider holds, from ${d.first} (${d.sessions?.toLocaleString()} sessions). It does not know about tonight's setup, so it is a wider, all-weather view and does not feed the verdict.`,
          `上面的相似时刻检索使用 2025 年起的小时线。这里是同一只股票在数据商保存的全部日线上的表现，从 ${d.first} 起（${d.sessions?.toLocaleString()} 个交易日）。它不了解今晚的具体情况，所以是更宽泛的“全天候”视角，不参与结论。`,
        )}
      </p>
      {share != null && d.line_pct != null ? (
        <p className="mt-3 max-w-prose text-sm">
          {L(
            `The desk's one-in-twenty line for this position is the stock moving ${tail} ${fmtPct(Math.abs(d.line_pct), 1, false)}. Over ${w.n.toLocaleString()} past ${winLabel} windows the stock went past that in ${(share * 100).toFixed(1)}%. If the line were drawn on all-weather history that would be about 5%; the desk's line is set for tonight's conditions, so a gap here is context, not a fault. (Estimated from a percentile grid.)`,
            `本台对这个仓位的二十分之一线，是股票${tail} ${fmtPct(Math.abs(d.line_pct), 1, false)}。在过去 ${w.n.toLocaleString()} 个${winLabel}窗口里，股票越过这条线的比例是 ${(share * 100).toFixed(1)}%。如果这条线按全天候历史来画，比例约为 5%；本台的线针对今晚的情况设定，所以差异只是背景信息，并不是错误。（由百分位网格估算。）`,
          )}
        </p>
      ) : null}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[30rem] text-left text-[13px]">
          <caption className="sr-only">{L("Bad-side moves by window, whole record", "各窗口的不利方向涨跌，全部历史")}</caption>
          <thead>
            <tr className="text-muted-foreground">
              <th scope="col" className="py-2 pr-3 font-medium">{L("Window", "窗口")}</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">{L("Cases", "次数")}</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">{L("1 in 20", "二十分之一")}</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">{L("1 in 100", "百分之一")}</th>
              <th scope="col" className="py-2 text-right font-medium">{L("Worst", "最差")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((k) => {
              const r = d.windows![k];
              return (
                <tr key={k} className={`border-t border-border ${k === d.chosen ? "font-medium" : ""}`}>
                  <th scope="row" className="py-2 pr-3 font-normal">
                    {L(r.label, r.label_zh)}
                    {k === d.chosen ? <span className="ml-2 text-muted-foreground">{L("closest to this hold", "最接近本次持有期")}</span> : null}
                  </th>
                  <td className="py-2 pr-3 text-right tabular-nums">{r.n.toLocaleString()}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{fmtPct(r.p5, 1)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{fmtPct(r.p1, 1)}</td>
                  <td className="py-2 text-right tabular-nums">{fmtPct(r.worst, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {worst ? (
        <p className="mt-3 max-w-prose text-[13px] text-muted-foreground">
          {L(`Worst ${winLabel} on record: ${fmtPct(worst.pct, 1)} on ${worst.date}.`, `记录中最差的${winLabel}：${worst.date}，${fmtPct(worst.pct, 1)}。`)}
          {d.pooled
            ? L(
                ` Across ${d.pooled.tickers ?? "many"} stocks pooled (${d.pooled.n.toLocaleString()} cases), the same window's one-in-twenty is ${fmtPct(d.pooled.p5, 1)}.`,
                ` 汇总 ${d.pooled.tickers ?? "多只"} 只股票（${d.pooled.n.toLocaleString()} 次）后，同一窗口的二十分之一是 ${fmtPct(d.pooled.p5, 1)}。`,
              )
            : ""}
          {d.ran_at ? L(` Measured ${d.ran_at.slice(0, 10)} from ${d.source ?? "daily bars"}.`, ` 测量于 ${d.ran_at.slice(0, 10)}，来源：${d.source ?? "日线"}。`) : ""}
        </p>
      ) : null}
    </Section>
  );
}
