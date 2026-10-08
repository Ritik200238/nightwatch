"use client";

import { useEffect, useState } from "react";
import { Section } from "@/components/report/primitives";
import { api, type QuoteTrust, type Report } from "@/lib/api";
import { type Lang, tr } from "@/lib/i18n";

const bps = (v: number) => `${v.toFixed(0)} bps`;
const range = (a: number, b: number) => `${a}–${b} h`;

/** Can the token's quote be trusted as a guess at the open, hour by hour?
 *  Committed measurement (scripts/quote_trust_sweep.py): the token's quote at each hour of
 *  the night against the stock's real opening print, beside simply holding the last close. */
export function QuoteTrustPanel({ report, lang, openAll }: { report: Report; lang: Lang; openAll?: boolean }) {
  const L = tr(lang);
  const [d, setD] = useState<QuoteTrust | null>(null);
  const ticker = report.ticket.ticker;
  const next = report.timeline?.next_open;
  const asOf = report.timeline?.as_of;
  const shut = report.timeline ? !report.timeline.market_open_at_as_of : false;
  const hrs = shut && next && asOf ? (new Date(next).getTime() - new Date(asOf).getTime()) / 3.6e6 : null;
  useEffect(() => {
    let live = true;
    api.quoteTrust(ticker, hrs && hrs > 0 ? Math.min(hrs, 72) : null).then((r) => live && setD(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [ticker, hrs]);
  if (!d?.available || !d.pooled?.length) return null;
  const now = d.now;
  return (
    <Section
      tier="default"
      collapsible
      openAll={openAll}
      title={L("How far off is the overnight price from the real open?", "夜间价格离真实开盘价有多远？")}
      summary={
        now
          ? L(
              `At ${range(now.from_h, now.to_h)} before the open the token has been a median ${bps(now.token_bps)} from the real opening price; holding the last close would be ${bps(now.last_close_bps)}`,
              `距开盘 ${range(now.from_h, now.to_h)} 时，代币报价与真实开盘价的中位偏差为 ${bps(now.token_bps)}；直接沿用上次收盘价则偏差 ${bps(now.last_close_bps)}`,
            )
          : L(
              `Across ${d.nights?.toLocaleString()} nights the token's quote gets closer to the real open as the open approaches`,
              `在 ${d.nights?.toLocaleString()} 个夜晚中，越接近开盘，代币报价越接近真实开盘价`,
            )
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[30rem] text-left text-[13px]">
          <caption className="sr-only">{L("Median distance from the real opening price, by hours before the open", "按距开盘小时数划分的、与真实开盘价的中位距离")}</caption>
          <thead>
            <tr className="text-muted-foreground">
              <th scope="col" className="py-2 pr-3 font-medium">{L("Hours before the open", "距开盘")}</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">{L("Token quote", "代币报价")}</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">{L("Last close held", "沿用上次收盘")}</th>
              <th scope="col" className="py-2 text-right font-medium">{L("Token closer", "代币更近的占比")}</th>
            </tr>
          </thead>
          <tbody>
            {d.pooled.map((r) => {
              const here = now && r.from_h === now.from_h;
              return (
                <tr key={r.from_h} className={`border-t border-border ${here ? "font-medium" : ""}`}>
                  <th scope="row" className="py-2 pr-3 font-normal">
                    {range(r.from_h, r.to_h)}
                    {here ? <span className="ml-2 text-muted-foreground">{L("now", "当前")}</span> : null}
                  </th>
                  <td className="py-2 pr-3 text-right tabular-nums">{bps(r.token_bps)} <span className="text-muted-foreground">[{r.token_ci?.[0].toFixed(0)}–{r.token_ci?.[1].toFixed(0)}]</span></td>
                  <td className="py-2 pr-3 text-right tabular-nums">{bps(r.last_close_bps)} <span className="text-muted-foreground">[{r.last_close_ci?.[0].toFixed(0)}–{r.last_close_ci?.[1].toFixed(0)}]</span></td>
                  <td className="py-2 text-right tabular-nums">{(r.token_closer * 100).toFixed(0)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 max-w-prose text-[13px] text-muted-foreground">
        {L(
          `Across ${d.tickers} tokens and ${d.nights?.toLocaleString()} nights, measured afterwards against the stock's real 09:30 ET opening price. The range is a 95% interval that resamples whole nights. Over a weekend (48–72 h before the open) the token's quote has been no better a guess than the last close, so a weekend number is not a fair price. This is a measured past sample and does not change the verdict.`,
          `覆盖 ${d.tickers} 个代币、${d.nights?.toLocaleString()} 个夜晚，事后与该股票美东 09:30 的真实开盘价对比。区间为按整夜重采样的 95% 区间。跨周末（距开盘 48–72 小时）时，代币报价并不比上次收盘价更好，所以周末的价格不能当作公允价。这是对过去样本的测量，不影响结论。`,
        )}
      </p>
    </Section>
  );
}
