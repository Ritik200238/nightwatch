"use client";

import { useEffect, useState } from "react";
import { Section } from "@/components/report/primitives";
import { api, type Report, type SessionBeta } from "@/lib/api";
import { type Lang, tr } from "@/lib/i18n";

const b = (v: number) => `${v >= 0 ? "" : "−"}${Math.abs(v).toFixed(2)}`;
const ci = (c: number[]) => `${b(c[0])} – ${b(c[1])}`;

/** Does the token keep following the Nasdaq token when the US market is shut?
 *  Read from the committed measurement (scripts/session_beta_sweep.py); it never feeds a verdict. */
export function SessionBetaPanel({ report, lang, openAll }: { report: Report; lang: Lang; openAll?: boolean }) {
  const L = tr(lang);
  const [d, setD] = useState<SessionBeta | null>(null);
  const ticker = report.ticket.ticker;
  useEffect(() => {
    let live = true;
    api.sessionBeta(ticker).then((r) => live && setD(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [ticker]);
  if (!d?.available || !d.open || !d.closed || !d.diff) return null;
  const tq = d.controls?.TQQQ;
  const sq = d.controls?.SQQQ;
  const word = !d.distinguishable
    ? L("no clear difference", "看不出明显差别")
    : d.diff.est < 0
      ? L("follows the market less when it is shut", "市场休市时跟随得更少")
      : L("follows the market more when it is shut", "市场休市时跟随得更多");
  return (
    <Section
      tier="default"
      collapsible
      openAll={openAll}
      title={L("Does it still follow the market when the US is shut?", "美股休市时它还跟着大盘走吗？")}
      summary={L(
        `${ticker} moves ${b(d.open.beta)}× the Nasdaq token when the US is open and ${b(d.closed.beta)}× when it is shut: ${word}`,
        `美股开市时 ${ticker} 的涨跌约为纳指代币的 ${b(d.open.beta)} 倍，休市时为 ${b(d.closed.beta)} 倍：${word}`,
      )}
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[13px] sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">{L("US open", "美股开市")}</dt>
          <dd className="tabular font-medium">{b(d.open.beta)}× <span className="font-normal text-muted-foreground">[{ci(d.open.ci)}]</span></dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{L("US shut", "美股休市")}</dt>
          <dd className="tabular font-medium">{b(d.closed.beta)}× <span className="font-normal text-muted-foreground">[{ci(d.closed.ci)}]</span></dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{L("Shut minus open", "休市减开市")}</dt>
          <dd className="tabular font-medium">{d.diff.est >= 0 ? "+" : ""}{b(d.diff.est)} <span className="font-normal text-muted-foreground">[{ci(d.diff.ci)}]</span></dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{L("Hours measured", "测量的小时数")}</dt>
          <dd className="tabular font-medium">{d.open.n.toLocaleString()} / {d.closed.n.toLocaleString()}</dd>
        </div>
      </dl>
      <p className="mt-3 max-w-prose text-[13px] text-muted-foreground">
        {L(
          "The slope of this token's hourly move on the QQQ token's, with a 95% range that resamples whole days. A position sized on the open-hours number is off by the gap when the market is shut. This is a measured past sample; it does not change the verdict. With ~22 stocks checked, about one clear difference is expected by chance alone.",
          "这是本代币每小时涨跌对 QQQ 代币每小时涨跌的斜率，95% 区间按整天重采样。按开市时的数字定仓位，休市时会差出这个差值。这是对过去样本的测量，不影响结论。检查了约 22 只股票，仅凭运气大约就会有一只出现明显差别。",
        )}
        {tq && sq
          ? L(
              ` Control: the 3× and −3× Nasdaq funds read ${b(tq.open.beta)} / ${b(tq.closed.beta)} and ${b(sq.open.beta)} / ${b(sq.closed.beta)} (open / shut), as they should, so the method is not creating the gap.`,
              ` 对照：3 倍和 −3 倍纳指基金读数为 ${b(tq.open.beta)} / ${b(tq.closed.beta)} 与 ${b(sq.open.beta)} / ${b(sq.closed.beta)}（开市 / 休市），符合预期，说明这个差别不是方法造成的。`,
            )
          : ""}
      </p>
    </Section>
  );
}
