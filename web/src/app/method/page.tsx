"use client";

import Link from "next/link";
import { OpenSection as Section, PageHead, PROOF_STACK, PROOF_WIDTH, ScrollTable } from "@/components/proof-page";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useLang } from "@/lib/lang";

const REPO = "https://github.com/Ritik200238/nightwatch";

/** Measured 8 Oct 2026 with scripts/benchmark_stops.py against the public API: 3,457 scored
 *  long-side forecasts, 148 nights, 24 stocks. Percent of forecasts whose return went past the
 *  rule's line: overall, then by stock (lowest, median, highest; stocks with 30+ forecasts).
 *  The base-line row uses the 2,143 forecasts that stored it. */
const BENCH: { rule: [string, string]; overall: string; low: string; median: string; high: string; highName: string; bold?: boolean }[] = [
  { rule: ["Desk line: similar past moments, one in twenty", "交易台的线：相似历史时刻，二十分之一"], overall: "4.6", low: "1.7", median: "5.8", high: "11.7", highName: "INTC", bold: true },
  { rule: ["Same engine without the similar-moment filter", "同一引擎，不做相似时刻筛选"], overall: "9.6", low: "1.0", median: "9.4", high: "16.3", highName: "AVGO" },
  { rule: ["Flat 2% stop", "固定 2% 止损"], overall: "12.2", low: "0.0", median: "16.5", high: "37.7", highName: "CRCL" },
  { rule: ["Flat 3% stop", "固定 3% 止损"], overall: "6.9", low: "0.0", median: "7.8", high: "31.2", highName: "CRCL" },
  { rule: ["Flat 5% stop", "固定 5% 止损"], overall: "2.0", low: "0.0", median: "1.4", high: "15.6", highName: "CRCL" },
  { rule: ["Flat 3.8% stop, picked afterwards to match the desk overall", "固定 3.8% 止损，事后挑选以与交易台整体持平"], overall: "4.6", low: "0.0", median: "4.9", high: "26.0", highName: "CRCL" },
];

export default function MethodPage() {
  const { tx, lang } = useLang();
  const zh = lang === "zh";

  return (
    <div className={`${PROOF_WIDTH} ${PROOF_STACK}`}>
      <PageHead
        title={tx("Method", "方法")}
        intro={tx(
          "How a verdict is built, what the AI may and may not do, how our line compares with the stops traders already use, and what did not work.",
          "结论是如何得出的，AI 能做什么、不能做什么，我们划的线与交易者常用止损相比如何，以及哪些做法没有奏效。",
        )}
      />

      <Section title={tx("The question", "要回答的问题")}>
        <p className="t-body max-w-prose text-muted-foreground">
          {tx(
            "A tokenized stock trades all week, but the stock behind it is open about a fifth of the week. The rest of the time the token's price is set by its own thin book, and the worst losses cluster in a few of those closed-market nights. So before a position is opened the useful question is: if this goes wrong while the market is shut, how wrong, and what size survives it?",
            "代币化美股全周交易，但背后的股票只有大约五分之一的时间开市。其余时间代币价格由它自己的薄订单簿决定，最大的亏损集中在少数几个休市夜晚。所以开仓之前真正有用的问题是：如果休市期间出了问题，会差到什么程度，什么仓位能扛得住？",
          )}
        </p>
      </Section>

      <Section title={tx("How a verdict is built", "结论是如何得出的")}>
        <ol className="t-body max-w-prose list-decimal space-y-2 pl-5 text-muted-foreground">
          <li>{tx("Retrieve the past moments most like now, matched on volatility state and the shape of the hold, with named dates and a similarity score.", "检索与现在最相似的历史时刻，按波动状态和持有期形态匹配，附带具体日期和相似度。")}</li>
          <li>{tx("Compute what followed them over the same hold: median, one-in-twenty, sample size, and the share that went the trader's way.", "计算它们在相同持有期内随后发生了什么：中位数、二十分之一线、样本量，以及朝交易者有利方向的占比。")}</li>
          <li>{tx("Run preset stress cases fitted to the token's own history, plus real crash replays, scaled to the closed windows the hold crosses.", "运行按该代币自身历史拟合的预设压力情景，加上真实崩盘重演，并按持有期跨越的休市时段缩放。")}</li>
          <li>{tx("Walk Bitget's live order book for the exact size to price the exit.", "按确切仓位走一遍 Bitget 实时订单簿，计算平仓成本。")}</li>
          <li>{tx("A rule gate sets the sized verdict. Tail widths use factors fitted only on earlier, already-scored forecasts, never on the forecast being judged.", "由规则关口给出带仓位的结论。尾部宽度所用的系数只来自更早、已评分的预测，绝不使用正在评判的这一条。")}</li>
        </ol>
        <p className="t-body mt-3 max-w-prose text-muted-foreground">
          {tx(
            "The AI reads the finished report and explains it. It computes no price, percentile, liquidation level or verdict, and every number it writes is checked against the report it was given; a sentence citing a number that is not there is removed and the removal is logged.",
            "AI 只读取已完成的报告并加以解释。它不计算任何价格、分位数、爆仓位或结论，它写的每个数字都会对照所给报告检查；引用了不存在的数字的句子会被删除，并记录在案。",
          )}
        </p>
      </Section>

      <Section
        title={tx("Our line against plain stop rules", "我们的线与常见止损规则的对比")}
        subtitle={tx(
          "Same scored history for every row: how often the return went past each rule's line.",
          "每一行都使用同一份已评分的历史：收益越过各规则划线的频率。",
        )}
      >
        <ScrollTable>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{tx("Rule", "规则")}</TableHead>
                <TableHead className="text-right">{tx("Past its line, overall", "越线占比（整体）")}</TableHead>
                <TableHead className="text-right">{tx("Lowest stock", "最低的股票")}</TableHead>
                <TableHead className="text-right">{tx("Median stock", "中位的股票")}</TableHead>
                <TableHead className="text-right">{tx("Highest stock", "最高的股票")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {BENCH.map((r) => (
                <TableRow key={r.rule[0]} className={r.bold ? "font-medium" : ""}>
                  <TableCell className="whitespace-normal">{zh ? r.rule[1] : r.rule[0]}</TableCell>
                  <TableCell className="tabular text-right">{r.overall}%</TableCell>
                  <TableCell className="tabular text-right">{r.low}%</TableCell>
                  <TableCell className="tabular text-right">{r.median}%</TableCell>
                  <TableCell className="tabular text-right">
                    {r.high}% <span className="text-muted-foreground">{r.highName}</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ScrollTable>
        <p className="t-caption mt-2 max-w-prose">
          {tx(
            "3,457 scored long-side forecasts across 148 nights and 24 stocks, measured 8 Oct 2026. Stock columns use the stocks with at least 30 scored forecasts. The base-line row covers the 2,143 forecasts that stored it.",
            "共 3,457 条已评分的做多预测，覆盖 148 个夜晚、24 只股票，测量日期 2026 年 10 月 8 日。按股票的列只统计至少有 30 条已评分预测的股票。“不做相似时刻筛选”一行覆盖保存了该数据的 2,143 条预测。",
          )}
        </p>
        <ul className="t-body mt-4 max-w-prose list-disc space-y-2 pl-5 text-muted-foreground">
          <li>
            {tx(
              "A one-in-twenty line should be crossed about one time in twenty on every stock. A flat stop cannot do that: in this sample the same 3% was never reached on an index fund and was reached nearly a third of the time on the most volatile name.",
              "二十分之一的线，在每只股票上都应该大约二十次里被越过一次。固定止损做不到：在这份样本里，同样的 3% 在指数基金上从未触及，在波动最大的股票上却有近三分之一的时间被触及。",
            )}
          </li>
          <li>
            {tx(
              "The last row is the best case for a flat rule: its level was chosen after the fact to match the desk's overall rate, so it was given the answer for free. It still ranges from 0% to 26% by stock; the desk line ranges from 1.7% to 11.7%.",
              "最后一行是固定止损最有利的情形：它的水平是事后挑选的，使整体越线率与交易台持平，等于白送了答案。按股票看，它仍然从 0% 到 26%，而交易台的线是 1.7% 到 11.7%。",
            )}
          </li>
          <li>
            {tx(
              "The desk line is not even either. Its busiest stock is crossed at more than twice the target, and the pattern is on the track-record page.",
              "交易台的线也不是处处均匀。越线最频繁的股票超过目标的两倍多，具体情况见战绩页面。",
            )}
          </li>
          <li>
            {tx(
              "Forecasts on the same night share that night's market move, so 3,457 is far fewer than 3,457 independent facts. The track-record page carries intervals that resample whole nights.",
              "同一夜的预测共享当晚的市场走势，所以 3,457 远不等于 3,457 个独立事实。战绩页面给出了按整夜重抽样的区间。",
            )}
          </li>
        </ul>
        <p className="t-body mt-3 text-muted-foreground">
          {tx("Rerun it: ", "自己重新运行：")}
          <code className="rounded bg-muted px-1.5 py-0.5 text-[13px]">python scripts/benchmark_stops.py</code>{" "}
          <a href={`${REPO}/blob/main/scripts/benchmark_stops.py`} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center underline underline-offset-2 hover:text-foreground">
            {tx("source", "源码")}
          </a>
        </p>
      </Section>

      <Section title={tx("What did not work, or is not proven", "哪些没有奏效，或尚未证明")}>
        <ul className="t-body max-w-prose list-disc space-y-2 pl-5 text-muted-foreground">
          <li>{tx("Weighting near-identical past moments more heavily made the forecast worse, so it is not in the shipped method. The closer half of the matches was wider, not calmer.", "给近乎相同的历史时刻更高权重反而让预测更差，所以没有放进上线的方法。更接近的那一半匹配并不更平静，反而更宽。")}</li>
          <li>{tx("Retrieval beating random hours of the same kind shows a narrow edge that does not survive correction for testing many questions at once. It is shown in amber, not claimed.", "检索优于同类随机时段只显示出很窄的优势，在校正了同时检验多个问题带来的偏差之后不再成立。页面用琥珀色标出，没有声称成立。")}</li>
          <li>{tx("A directional edge: measured, none. The desk sizes risk; it does not tell you which way to bet.", "方向性优势：已测量，没有。交易台做的是风险定仓，不告诉你该押哪个方向。")}</li>
          <li>{tx("Real-trader adoption and a real-money record are not claimed.", "我们不声称有真实交易者的采用，也没有真金白银的记录。")}</li>
        </ul>
        <p className="t-body mt-3 text-muted-foreground">
          <Link href="/studies" className="inline-flex min-h-10 items-center underline underline-offset-2 hover:text-foreground">
            {tx("All internal studies, failures included", "全部内部研究（含失败）")}
          </Link>
          {" · "}
          <Link href="/calibration" className="inline-flex min-h-10 items-center underline underline-offset-2 hover:text-foreground">
            {tx("Scored forecasts", "已评分的预测")}
          </Link>
          {" · "}
          <Link href="/judges" className="inline-flex min-h-10 items-center underline underline-offset-2 hover:text-foreground">
            {tx("For judges", "给评审")}
          </Link>
        </p>
      </Section>
    </div>
  );
}
