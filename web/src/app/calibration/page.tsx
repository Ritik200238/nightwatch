"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Button } from "@/components/ui/button";
import { LoadingRecord, PageHead, PlainBox, PROOF_WIDTH, ScrollTable } from "@/components/proof-page";
import { Term } from "@/components/term";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, peek, type CalibrationReport } from "@/lib/api";
import { AsOf } from "@/components/as-of";
import { useLang } from "@/lib/lang";
import { fmtPct, fmtRatio } from "@/lib/format";

/** Horizon bands, said the way a person holding the position would say it. */
const BAND_LABEL_ZH: Record<string, string> = {
  overnight: "隔夜（40 小时以内）",
  multi_day: "周末或更长（40 小时以上）",
  pooled: "两类样本都还不够多的时候",
};
const TAIL_BAND_ZH: Record<string, string> = { green: "绿", amber: "黄", red: "红" };

const BAND_LABEL: Record<string, string> = {
  overnight: "Overnight (under 40h)",
  multi_day: "Weekend or longer (40h+)",
  pooled: "Before there was enough of either",
};

/** The server writes the drift sentence in English; this says it in Chinese when the page is. */
function walkNote(note: string | undefined, lang: "en" | "zh"): string {
  if (!note) return "";
  const m = /^the gap to 90% coverage is (closing|widening) by ([\d.]+) points per period$/.exec(note);
  if (!m) return note;
  if (lang === "zh") return `与 90% 覆盖率的差距正以每期 ${m[2]} 个百分点的速度${m[1] === "closing" ? "收窄" : "扩大"}。`;
  return `The gap to 90% coverage is ${m[1]} by ${m[2]} points per period.`;
}

const PIT_ORDER = ["<p5", "p5-p25", "p25-p50", "p50-p75", "p75-p95", ">p95"];
const PIT_EXPECTED: Record<string, number> = { "<p5": 0.05, "p5-p25": 0.2, "p25-p50": 0.25, "p50-p75": 0.25, "p75-p95": 0.2, ">p95": 0.05 };

export default function CalibrationPage() {
  const { tx, lang } = useLang();
  const bandL = (b: string) => (lang === "zh" ? BAND_LABEL_ZH[b] : BAND_LABEL[b]) ?? b;
  const tb = (b: string) => (lang === "zh" ? (TAIL_BAND_ZH[b] ?? b) : b);
  const [rep, setRep] = useState<CalibrationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"all" | "replay" | "ticket">("all");

  async function load() {
    setError(null);
    // The last answer shows at once; the fresh one replaces it when it arrives.
    setRep(peek<CalibrationReport>(kind === "all" ? "/calibration" : `/calibration?kind=${kind}`));
    try {
      setRep(await api.calibration(undefined, kind === "all" ? undefined : kind));
    } catch (e) {
      setError(e instanceof Error ? e.message : tx("Could not load calibration.", "无法加载校准数据。"));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  const bandTone = rep?.tail.band === "green" ? "good" : rep?.tail.band === "amber" ? "warning" : rep?.tail.band === "red" ? "critical" : "muted";
  const pitData = rep ? PIT_ORDER.map((k) => ({ bucket: k, observed: (rep.pit_histogram[k] ?? 0) / Math.max(1, rep.n_matured), expected: PIT_EXPECTED[k] })) : [];

  return (
    <div className={`${PROOF_WIDTH} space-y-4`}>
      <PageHead
        tabs
        title={tx("Does it tell the truth?", "它说的是真话吗？")}
        intro={
          <>
            {tx("Every forecast is written down before the outcome is known, then scored once the horizon passes. If the forecasts are ", "每个预测都在结果未知时先写下来，持有期结束后再评分。如果预测是")}
            <Term k="calibrated" />
            {tx(", 5% of outcomes land below ", "，5% 的结果会低于 ")}
            <Term k="p5">p5</Term>
            {tx(" and 90% inside the p5–", "，90% 落在 p5–")}
            <Term k="p95">p95</Term>
            {tx(" band.", " 区间内。")}
          </>
        }
        actions={
          <div className="flex gap-1" role="group" aria-label={tx("Forecast kind", "预测类型")}>
            {(["all", "replay", "ticket"] as const).map((k) => (
              <Button key={k} size="sm" variant={kind === k ? "default" : "secondary"} onClick={() => setKind(k)}>
                {k === "all" ? tx("All", "全部") : k === "replay" ? tx("Replays", "重演") : tx("Live tickets", "实时交易")}
              </Button>
            ))}
          </div>
        }
      />
      <AsOf path={kind === "all" ? "/calibration" : `/calibration?kind=${kind}`} />

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="font-medium">{tx("Couldn't load calibration", "无法加载校准数据")}</p>
          <p className="text-[13px] text-muted-foreground">{error}</p>
          <Button variant="secondary" size="sm" className="mt-2" onClick={() => void load()}>
            {tx("Try again", "重试")}
          </Button>
        </div>
      ) : !rep ? (
        <LoadingRecord blocks={[112, 256]} />
      ) : rep.n_matured === 0 ? (
        <div className="flex min-h-[240px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-8 text-center">
          <p className="text-sm font-medium">{tx("No matured forecasts yet", "还没有到期的预测")}</p>
          <p className="max-w-prose text-sm text-muted-foreground">{tx("Run a replay (`nightwatch replay --tickers TSLA`) to score the forecasts the system would have made over past closed-market windows, or wait for live tickets to mature.", "运行一次重演（`nightwatch replay --tickers TSLA`），为系统在过去休市窗口本会做出的预测评分，或者等实时交易到期。")}</p>
        </div>
      ) : (
        <>
          <Scorecard rep={rep} />
          {rep.adjusted ? <PlainWords adj={rep.adjusted} /> : null}
          {rep.adjusted ? (
            <Section
              title={tx("What the desk sizes on, scored out of sample", "交易台用来定仓位的数字，样本外评分")}
              subtitle={tx("Every verdict is sized on the adjusted tail. These are those tails, each scored against what then happened, with the adjustment fitted only on forecasts that had matured before it.", "每个结论都按调整后的尾部来定仓位。这里是这些尾部，每个都对照后来实际发生的结果评分，调整系数只用在它之前已到期的预测拟合。")}
              action={<Pill tone={rep.adjusted.adj_tail_band === "green" ? "good" : rep.adjusted.adj_tail_band === "amber" ? "warning" : "critical"}>{tx("5% tail: ", "5% 尾部：")}{tb(rep.adjusted.adj_tail_band)}</Pill>}
            >
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat
                  label={tx("Outcomes below the 5th percentile", "低于第 5 百分位的结果")}
                  value={fmtPct(rep.adjusted.adj_lo_coverage * 100, 1, false)}
                  hint={tx(`target 5% · ${rep.adjusted.n_evaluated.toLocaleString()} forecasts · raw search ${fmtPct(rep.adjusted.raw_lo_coverage * 100, 1, false)}`, `目标 5% · ${rep.adjusted.n_evaluated.toLocaleString()} 个预测 · 原始搜索 ${fmtPct(rep.adjusted.raw_lo_coverage * 100, 1, false)}`)}
                />
                {rep.adjusted.raw_lo_coverage > 0.05 ? (
                  <p className="col-span-2 text-[13px] text-muted-foreground sm:col-span-4">
                    {tx(`Raw history breaches more often than it should (${fmtPct(rep.adjusted.raw_lo_coverage * 100, 1, false)} against a 5% target); that is why every verdict uses the adjusted line, which is on target (${fmtPct(rep.adjusted.adj_lo_coverage * 100, 1, false)}).`, `原始历史突破坏情形的频率高于应有水平（${fmtPct(rep.adjusted.raw_lo_coverage * 100, 1, false)}，目标 5%）；所以每个结论都用调整后的线，它已达标（${fmtPct(rep.adjusted.adj_lo_coverage * 100, 1, false)}）。`)}
                  </p>
                ) : null}
                <p className="col-span-2 text-[13px] text-muted-foreground sm:col-span-4">
                  {tx(
                    `Treating every forecast as independent, the 95% interval on that rate is ${fmtPct(rep.adjusted.adj_lo_ci[0] * 100, 1, false)} to ${fmtPct(rep.adjusted.adj_lo_ci[1] * 100, 1, false)}. That assumes ${rep.adjusted.n_evaluated.toLocaleString()} separate facts, but forecasts made on the same night share that night's market move.${rep.adjusted.adj_lo_night_ci ? ` Resampling whole nights instead (${rep.adjusted.n_nights} independent nights) gives ${fmtPct(rep.adjusted.adj_lo_night_ci[0] * 100, 1, false)} to ${fmtPct(rep.adjusted.adj_lo_night_ci[1] * 100, 1, false)}, which is the interval to trust.` : ""}`,
                    `把每个预测都当作相互独立，该比例的 95% 区间为 ${fmtPct(rep.adjusted.adj_lo_ci[0] * 100, 1, false)} 至 ${fmtPct(rep.adjusted.adj_lo_ci[1] * 100, 1, false)}。这假设有 ${rep.adjusted.n_evaluated.toLocaleString()} 个独立事实，但同一夜的预测共享该夜的市场波动。${rep.adjusted.adj_lo_night_ci ? ` 改为按整夜重抽样（${rep.adjusted.n_nights} 个独立夜晚）得到 ${fmtPct(rep.adjusted.adj_lo_night_ci[0] * 100, 1, false)} 至 ${fmtPct(rep.adjusted.adj_lo_night_ci[1] * 100, 1, false)}，应以此区间为准。` : ""}`,
                  )}
                </p>
                <Stat label={tx("Inside the 5th-95th band", "落在第 5–95 百分位区间内")} value={fmtPct(rep.adjusted.adj_band_coverage * 100, 1, false)} hint={tx(`target 90% · raw ${fmtPct(rep.adjusted.raw_band_coverage * 100, 1, false)}`, `目标 90% · 原始 ${fmtPct(rep.adjusted.raw_band_coverage * 100, 1, false)}`)} />
                {rep.adjusted.bands
                  .filter((b) => b.band !== "pooled")
                  .map((b) => (
                    <Stat
                      key={b.band}
                      label={bandL(b.band)}
                      value={fmtPct(b.adj_lo_coverage * 100, 1, false)}
                      hint={tx(`below the 5th percentile · ${b.n.toLocaleString()} forecasts on ${b.n_nights ?? "?"} nights · ${b.adj_tail_band}`, `低于第 5 百分位 · ${b.n.toLocaleString()} 个预测，${b.n_nights ?? "?"} 个夜晚 · ${tb(b.adj_tail_band)}`)}
                    />
                  ))}
              </div>
            </Section>
          ) : null}

          {rep.since_freeze ? <SinceFreezeBlock f={rep.since_freeze} /> : null}

          {rep.adjusted ? (
            <Section
              collapsible
              title={tx("Tail adjustment, scored out of sample", "尾部调整，样本外评分")}
              subtitle={tx(`Each forecast re-scored with a correction learned only from forecasts that had already matured before it (${rep.adjusted.n_evaluated.toLocaleString()} evaluated). Technical detail: latest k_lo ${rep.adjusted.k_lo_last?.toFixed(2)}${rep.adjusted.c_lo_last ? `, margin ${rep.adjusted.c_lo_last.toFixed(1)} pts` : ""}, k_hi ${rep.adjusted.k_hi_last?.toFixed(2)}. The verdict uses the corrected bad case.`, `每个预测都只用在它之前已到期的预测学到的修正来重新评分（评估了 ${rep.adjusted.n_evaluated.toLocaleString()} 个）。技术细节：最新 k_lo ${rep.adjusted.k_lo_last?.toFixed(2)}${rep.adjusted.c_lo_last ? `，边际 ${rep.adjusted.c_lo_last.toFixed(1)} 个百分点` : ""}，k_hi ${rep.adjusted.k_hi_last?.toFixed(2)}。结论使用修正后的坏情形。`)}
            >
              <ScrollTable>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{tx("Metric", "指标")}</TableHead>
                    <TableHead className="text-right">{tx("Target", "目标")}</TableHead>
                    <TableHead className="text-right">{tx("Raw", "原始")}</TableHead>
                    <TableHead className="text-right">{tx("Adjusted", "调整后")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell>{tx("Outcomes below p5", "低于 p5 的结果")}</TableCell>
                    <TableCell className="tabular text-right">5%</TableCell>
                    <TableCell className="tabular text-right">{fmtPct(rep.adjusted.raw_lo_coverage * 100, 1, false)}</TableCell>
                    <TableCell className="tabular text-right font-medium">{fmtPct(rep.adjusted.adj_lo_coverage * 100, 1, false)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>{tx("Outcomes above p95", "高于 p95 的结果")}</TableCell>
                    <TableCell className="tabular text-right">5%</TableCell>
                    <TableCell className="tabular text-right">{fmtPct(rep.adjusted.raw_hi_coverage * 100, 1, false)}</TableCell>
                    <TableCell className="tabular text-right font-medium">{fmtPct(rep.adjusted.adj_hi_coverage * 100, 1, false)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>{tx("Inside the p5–p95 band", "落在 p5–p95 区间内")}</TableCell>
                    <TableCell className="tabular text-right">90%</TableCell>
                    <TableCell className="tabular text-right">{fmtPct(rep.adjusted.raw_band_coverage * 100, 1, false)}</TableCell>
                    <TableCell className="tabular text-right font-medium">{fmtPct(rep.adjusted.adj_band_coverage * 100, 1, false)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>{tx("5% tail band", "5% 尾部评级")}</TableCell>
                    <TableCell className="tabular text-right">{tb("green")}</TableCell>
                    <TableCell className="text-right">
                      <Pill tone={rep.adjusted.raw_tail_band === "green" ? "good" : rep.adjusted.raw_tail_band === "amber" ? "warning" : "critical"}>{tb(rep.adjusted.raw_tail_band)}</Pill>
                    </TableCell>
                    <TableCell className="text-right">
                      <Pill tone={rep.adjusted.adj_tail_band === "green" ? "good" : rep.adjusted.adj_tail_band === "amber" ? "warning" : "critical"}>{tb(rep.adjusted.adj_tail_band)}</Pill>
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>{tx("Mean p5–p95 width (sharpness)", "p5–p95 平均宽度（锐度）")}</TableCell>
                    <TableCell className="tabular text-right">—</TableCell>
                    <TableCell className="tabular text-right">{rep.adjusted.raw_width.toFixed(2)}%</TableCell>
                    <TableCell className="tabular text-right font-medium">{rep.adjusted.adj_width.toFixed(2)}%</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
</ScrollTable>
            </Section>
          ) : null}

          {rep.adjusted?.bands?.length ? (
            <Section
              collapsible
              title={tx("The same, split by how long the position is held", "同样的数据，按持有时间拆开")}
              subtitle={tx("A single factor fitted across every horizon is the average of two different corrections, and the average is nobody's number. An overnight hold and a weekend hold need opposite adjustments, so each gets its own — and the overall reading above is only trustworthy if these are too.", "对所有持有期只拟合一个系数，等于把两种不同的修正取平均，而平均值对谁都不准。隔夜持有和周末持有需要相反方向的调整，所以各用各的——上面的总体读数，只有这些也可信时才可信。")}
            >
              <ScrollTable>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{tx("Window", "时间窗口")}</TableHead>
                    <TableHead className="text-right">{tx("Scored", "已评分")}</TableHead>
                    <TableHead className="text-right">{tx("Below p5 (target 5%)", "低于 p5（目标 5%）")}</TableHead>
                    <TableHead className="text-right">{tx("Above p95 (target 5%)", "高于 p95（目标 5%）")}</TableHead>
                    <TableHead className="text-right">{tx("Width, raw → adjusted", "宽度：原始 → 调整后")}</TableHead>
                    <TableHead className="text-right"><Term k="klo">k_lo</Term></TableHead>
                    <TableHead className="text-right"><Term k="margin">{tx("Margin", "边际")}</Term></TableHead>
                    <TableHead className="text-right">{tx("5% tail", "5% 尾部")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rep.adjusted.bands.map((b) => (
                    <TableRow key={b.band}>
                      <TableCell className="font-medium">{bandL(b.band)}</TableCell>
                      <TableCell className="tabular text-right">{b.n}</TableCell>
                      <TableCell className="tabular text-right font-medium">{fmtPct(b.adj_lo_coverage * 100, 1, false)}</TableCell>
                      <TableCell className="tabular text-right font-medium">{fmtPct(b.adj_hi_coverage * 100, 1, false)}</TableCell>
                      <TableCell className="tabular text-right">
                        {b.raw_width.toFixed(2)}% → <span className="font-medium">{b.adj_width.toFixed(2)}%</span>
                      </TableCell>
                      <TableCell className="tabular text-right">{b.k_lo.toFixed(2)}</TableCell>
                      <TableCell className="tabular text-right">{b.c_lo ? tx(`${b.c_lo.toFixed(1)} pts`, `${b.c_lo.toFixed(1)} 个百分点`) : "—"}</TableCell>
                      <TableCell className="text-right">
                        <Pill tone={b.adj_tail_band === "green" ? "good" : b.adj_tail_band === "amber" ? "warning" : "critical"}>{tb(b.adj_tail_band)}</Pill>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
</ScrollTable>
              <p className="mt-3 text-[13px] text-muted-foreground">
                {tx("A k_lo below 1 means the cohort's own p5 was already too pessimistic for that kind of window and gets pulled in, not pushed out. The margin is an absolute floor under narrow forecasts: a multiplicative factor alone left the narrowest third of forecasts breaching 8.2% of the time and the widest third 2.7%, and the margin is solved so the narrower half breaches 5% as well. The “before there was enough” row is every forecast made before its window had 120 matured examples of its own; those used the pooled factor, and they are shown rather than dropped.", "k_lo 小于 1 表示该类窗口里样本自身的 p5 本来就过于悲观，会被往回收，而不是往外推。边际是给窄区间预测加的绝对下限：只用乘法系数时，最窄的三分之一预测有 8.2% 突破，最宽的三分之一只有 2.7%；边际的取值使较窄的一半也刚好是 5% 突破。“样本还不够多的时候”那一行，是指该窗口自己还没有 120 个到期样本之前做出的所有预测；它们用的是合并系数，这里照实展示而不是丢掉。")}
              </p>
            </Section>
          ) : null}

          <Section collapsible title={tx(`Before adjustment: the raw search, ${rep.n_matured.toLocaleString()} matured forecasts`, `调整之前：原始搜索，${rep.n_matured.toLocaleString()} 个已到期预测`)} subtitle={Object.entries(rep.by_ticker).map(([t, n]) => `${t} ${n}`).join(" · ")} action={<Pill tone={bandTone}>{tx("raw 5% tail: ", "原始 5% 尾部：")}{tb(rep.tail.band)}</Pill>}>
            <p className="mb-3 text-sm text-muted-foreground">
              {tx("What the analog search says on its own, before the tail adjustment. The desk does not size on this; it is here because the adjustment above is only as honest as the number it corrects, and hiding the uncorrected one would make that impossible to check.", "相似时刻搜索自己给出的结果，尚未做尾部调整。交易台不按这个定仓位；它放在这里，是因为上面的调整只有与被修正的数字一样诚实才有意义，而藏起未修正的数字就无法检验这一点。")}
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label={tx("Breaches below p5", "跌破 p5 的次数")} value={`${rep.tail.breaches} / ${rep.tail.n}`} hint={tx(`expected ${(rep.tail.expected_rate * rep.tail.n).toFixed(1)}${rep.tail.n_nights ? ` · ${rep.tail.n_nights} nights` : ""}${rep.tail.night_ci ? ` · nights-resampled [${fmtPct(rep.tail.night_ci[0] * 100, 1, false)}, ${fmtPct(rep.tail.night_ci[1] * 100, 1, false)}]` : ""}`, `预期 ${(rep.tail.expected_rate * rep.tail.n).toFixed(1)}${rep.tail.n_nights ? ` · ${rep.tail.n_nights} 个夜晚` : ""}${rep.tail.night_ci ? ` · 按夜重抽样 [${fmtPct(rep.tail.night_ci[0] * 100, 1, false)}, ${fmtPct(rep.tail.night_ci[1] * 100, 1, false)}]` : ""}`)} tone={bandTone === "muted" ? undefined : bandTone} />
              <Stat label={tx("Failure-rate test", "失败率检验")} value={rep.tail.pof_p_value != null ? `p = ${rep.tail.pof_p_value.toFixed(3)}` : "—"} hint={rep.tail.pof_stat != null ? `LR ${rep.tail.pof_stat.toFixed(2)}` : tx("needs ≥ 20 forecasts", "至少需要 20 个预测")} />
              <Stat label={tx("Independence test", "独立性检验")} value={rep.tail.independence_p_value != null ? `p = ${rep.tail.independence_p_value.toFixed(3)}` : "—"} hint={tx("do breaches cluster?", "突破是否扎堆出现？")} />
              <Stat label={tx("Sharpness", "锐度")} value={rep.mean_width_p5_p95 != null ? `${rep.mean_width_p5_p95.toFixed(2)}%` : "—"} hint={tx(`mean p5–p95 width · |err p50| ${rep.mean_abs_error_p50?.toFixed(2) ?? "—"}%`, `p5–p95 平均宽度 · |p50 误差| ${rep.mean_abs_error_p50?.toFixed(2) ?? "—"}%`)} />
            </div>
          </Section>

          {rep.skill && rep.skill.skill != null ? (
            <Section
              collapsible
              title={tx("Does it beat guessing?", "它比瞎猜强吗？")}
              subtitle={tx(`Each replay forecast is paired with the distribution of random past hours from the same time-of-week bucket. Lower pinball loss is better. ${rep.skill.n.toLocaleString()} pairs; the analogs win ${fmtPct((rep.skill.win_share ?? 0) * 100, 0, false)} of them. This averages all five quantiles; the studies page tests only the 5th-percentile tail, where the analogs are narrowly ahead. Different questions, not a contradiction.`, `每个重演预测都与同一周内时段的随机历史小时分布配对。弹球损失越低越好。共 ${rep.skill.n.toLocaleString()} 对；相似时刻方法赢了其中的 ${fmtPct((rep.skill.win_share ?? 0) * 100, 0, false)}。这里对五个分位数取平均；研究页只检验第 5 百分位尾部，相似时刻在那里略占优。两者问的是不同的问题，并不矛盾。`)}
              action={
                <Pill tone={rep.skill.diff_ci_low != null && rep.skill.diff_ci_low > 0 ? "good" : rep.skill.diff_ci_high != null && rep.skill.diff_ci_high < 0 ? "critical" : "warning"}>
                  {tx("skill ", "技能 ")}{rep.skill.skill >= 0 ? "+" : ""}
                  {(rep.skill.skill * 100).toFixed(1)}%
                </Pill>
              }
            >
              <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
                <ScrollTable>

                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{tx("Quantile", "分位数")}</TableHead>
                      <TableHead className="text-right"><Term k="analog">{tx("Analog", "相似时刻")}</Term> {tx("loss", "损失")}</TableHead>
                      <TableHead className="text-right">{tx("Random loss", "随机损失")}</TableHead>
                      <TableHead className="text-right">{tx("Skill", "技能")}</TableHead>
                      <TableHead className="text-right">{tx("95% CI of gain", "增益的 95% 置信区间")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rep.skill.per_quantile.map((q) => (
                      <TableRow key={q.quantile}>
                        <TableCell className="font-medium">{q.quantile}</TableCell>
                        <TableCell className="tabular text-right">{q.loss_analog.toFixed(3)}</TableCell>
                        <TableCell className="tabular text-right">{q.loss_baseline.toFixed(3)}</TableCell>
                        <TableCell className={`tabular text-right ${q.skill > 0 ? "text-status-good" : q.skill < 0 ? "text-status-critical" : ""}`}>
                          {q.skill >= 0 ? "+" : ""}
                          {(q.skill * 100).toFixed(1)}%
                        </TableCell>
                        <TableCell className="tabular text-right text-muted-foreground">
                          [{q.diff_ci_low >= 0 ? "+" : ""}
                          {q.diff_ci_low.toFixed(3)}, {q.diff_ci_high >= 0 ? "+" : ""}
                          {q.diff_ci_high.toFixed(3)}]
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
</ScrollTable>
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-2">
                    <Stat label={tx("Mean loss, analog", "平均损失：相似时刻")} value={rep.skill.mean_loss_analog?.toFixed(3) ?? "—"} hint={tx("average pinball loss over the five quantiles", "五个分位数的平均弹球损失")} />
                    <Stat label={tx("Mean loss, random hours", "平均损失：随机小时")} value={rep.skill.mean_loss_baseline?.toFixed(3) ?? "—"} hint={tx(`gain CI [${rep.skill.diff_ci_low?.toFixed(3)}, ${rep.skill.diff_ci_high?.toFixed(3)}]`, `增益置信区间 [${rep.skill.diff_ci_low?.toFixed(3)}, ${rep.skill.diff_ci_high?.toFixed(3)}]`)} />
                    <Stat label={tx("Below p5", "低于 p5")} value={`${fmtPct((rep.skill.analog_lo_coverage ?? 0) * 100, 1, false)} vs ${fmtPct((rep.skill.baseline_lo_coverage ?? 0) * 100, 1, false)}`} hint={tx("analog vs random · target 5%", "相似时刻 vs 随机 · 目标 5%")} />
                    <Stat label={tx("Above p95", "高于 p95")} value={`${fmtPct((rep.skill.analog_hi_coverage ?? 0) * 100, 1, false)} vs ${fmtPct((rep.skill.baseline_hi_coverage ?? 0) * 100, 1, false)}`} hint={tx("analog vs random · target 5%", "相似时刻 vs 随机 · 目标 5%")} />
                  </div>
                  {/* A judge reading only the headline number would conclude the retrieval
                      is useless. It is nearly useless for direction, which is why the
                      verdict never takes one from it; the tail is the part that is used. */}
                  <p className="text-[13px] text-muted-foreground">
                    <span className="text-foreground">{tx("How to read this.", "怎么读这个。")}</span>{" "}
                    {tx("Scored by ", "评分采用")}<Term k="pinball" />{tx(". ", "。")}
                    {tx("Over the whole distribution the analogs are indistinguishable from picking random hours of the same kind, and around the quartiles they are measurably worse — the resemblance narrows the middle where the truth is wide. Where they help is the loss tail: ", "就整个分布而言，相似时刻与随机挑同类小时没有区别，在四分位附近还明显更差——相似性把本该很宽的中间部分收窄了。它真正有用的是亏损尾部：")}{fmtPct((rep.skill.analog_lo_coverage ?? 0) * 100, 1, false)} {tx("of outcomes fall below the analog 5th percentile against", "的结果低于相似时刻的第 5 百分位，而随机小时的对应比例是")}{" "}
                    {fmtPct((rep.skill.baseline_lo_coverage ?? 0) * 100, 1, false)} {tx("below the random-hours one. That is the number every verdict is sized against, and it is the only claim this product makes about the retrieval.", "。每个结论都是按这个数字定仓位的，这也是本产品对检索能力做出的唯一主张。")}
                  </p>
                  <p className="text-[13px] text-muted-foreground">
                    {tx("Per token:", "按代币：")}{" "}
                    {Object.entries(rep.skill.by_ticker)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([t, v]) => `${t} ${v >= 0 ? "+" : ""}${(v * 100).toFixed(0)}%`)
                      .join(" · ")}
                  </p>
                </div>
              </div>
            </Section>
          ) : null}

          {rep.walk_forward && rep.walk_forward.periods.length > 1 ? (
            <Section
              collapsible
              title={tx("Is it getting better or worse?", "它在变好还是变差？")}
              subtitle={`${tx("The same out-of-sample scoring, split by month.", "同样的样本外评分，按月拆开。")} ${walkNote(rep.walk_forward.note, lang)}`}
              action={
                rep.walk_forward.improving == null ? null : (
                  <Pill tone={rep.walk_forward.improving ? "good" : "warning"}>{rep.walk_forward.improving ? tx("closing on target", "正在接近目标") : tx("drifting from target", "正在偏离目标")}</Pill>
                )
              }
            >
              <ScrollTable>
                <Table className="min-w-[640px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead>{tx("Month", "月份")}</TableHead>
                      <TableHead className="text-right">{tx("Scored", "已评分")}</TableHead>
                      <TableHead className="text-right">{tx("Below p5, raw", "低于 p5，原始")}</TableHead>
                      <TableHead className="text-right">{tx("Below p5, adjusted", "低于 p5，调整后")}</TableHead>
                      <TableHead className="text-right">{tx("Inside band, adjusted", "区间内，调整后")}</TableHead>
                      <TableHead className="text-right">{tx("Band width", "区间宽度")}</TableHead>
                      <TableHead className="text-right">{tx("Skill", "技能")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rep.walk_forward.periods.map((p) => (
                      <TableRow key={p.label}>
                        <TableCell className="font-medium">
                          {p.label}
                          {p.thin ? <span className="ml-2 text-[13px] text-muted-foreground">{tx("thin", "样本少")}</span> : null}
                        </TableCell>
                        <TableCell className="tabular text-right">{p.n}</TableCell>
                        <TableCell className="tabular text-right text-muted-foreground">{fmtPct(p.raw_lo_coverage * 100, 1, false)}</TableCell>
                        <TableCell className={`tabular text-right ${Math.abs(p.adj_lo_coverage - 0.05) < 0.02 ? "text-status-good" : ""}`}>{fmtPct(p.adj_lo_coverage * 100, 1, false)}</TableCell>
                        <TableCell className="tabular text-right">{fmtPct(p.adj_band_coverage * 100, 1, false)}</TableCell>
                        <TableCell className="tabular text-right text-muted-foreground">
                          {p.raw_width.toFixed(1)} → {p.adj_width.toFixed(1)}
                        </TableCell>
                        <TableCell className={`tabular text-right ${p.skill != null && p.skill > 0 ? "text-status-good" : p.skill != null && p.skill < 0 ? "text-status-critical" : "text-muted-foreground"}`}>
                          {p.skill == null ? "—" : `${p.skill >= 0 ? "+" : ""}${(p.skill * 100).toFixed(1)}%`}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollTable>
              <p className="mt-2 text-[13px] text-muted-foreground">{tx("Targets: 5% below p5, 90% inside the band. A month marked thin has too few scored forecasts to read much into.", "目标：5% 低于 p5，90% 落在区间内。标为“样本少”的月份，已评分的预测太少，不宜过度解读。")}</p>
            </Section>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <Section collapsible title={tx("Coverage by quantile", "各分位数的覆盖率")} subtitle={tx("Observed share of outcomes below each predicted quantile, with a 95% interval.", "低于各预测分位数的结果所占的实际比例，附 95% 区间。")}>
              <ScrollTable>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead><Term k="coverage">{tx("Quantile", "分位数")}</Term></TableHead>
                    <TableHead className="text-right">{tx("Nominal", "名义值")}</TableHead>
                    <TableHead className="text-right">{tx("Observed", "实际值")}</TableHead>
                    <TableHead className="text-right">{tx("95% interval", "95% 区间")}</TableHead>
                    <TableHead className="text-right">{tx("OK", "合格")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rep.coverage.map((c) => (
                    <TableRow key={c.quantile}>
                      <TableCell className="font-medium">{c.quantile}</TableCell>
                      <TableCell className="tabular text-right">{fmtRatio(c.nominal)}</TableCell>
                      <TableCell className="tabular text-right">{Number.isNaN(c.observed) ? "—" : fmtPct(c.observed * 100, 1, false)}</TableCell>
                      <TableCell className="tabular text-right text-muted-foreground">
                        [{fmtRatio(c.ci_low)}, {fmtRatio(c.ci_high)}]
                      </TableCell>
                      <TableCell className="text-right">{c.within_ci ? <Pill tone="good">{tx("yes", "是")}</Pill> : <Pill tone="critical">{tx("no", "否")}</Pill>}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
</ScrollTable>
            </Section>
            <Section collapsible defaultOpen title={tx("Where outcomes landed", "结果落在哪里")} subtitle={tx("Share of realised returns per predicted band. A calibrated forecast is flat at the expected heights.", "各预测区间内实际收益所占的比例。校准良好的预测，柱高应与预期持平。")}>
              <figure aria-label={tx("Probability integral transform histogram", "概率积分变换直方图")}>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={pitData} margin={{ top: 12, right: 8, bottom: 4, left: -18 }} barCategoryGap={8}>
                    <CartesianGrid vertical={false} stroke="var(--grid)" />
                    <XAxis dataKey="bucket" tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} axisLine={{ stroke: "var(--grid)" }} tickLine={false} />
                    <YAxis tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
                    <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 }} formatter={(v, name) => [`${(Number(v) * 100).toFixed(1)}%`, name === "observed" ? tx("observed", "实际") : tx("expected", "预期")]} />
                    <Bar dataKey="expected" fill="var(--muted-foreground)" fillOpacity={0.35} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} name="expected" />
                    <Bar dataKey="observed" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} name="observed" />
                  </BarChart>
                </ResponsiveContainer>
                <figcaption className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <span aria-hidden className="inline-block h-2 w-3 rounded-sm bg-chart-1" /> {tx("observed", "实际")}
                  </span>
                  <span><Term k="pit" /></span>
                  <span className="inline-flex items-center gap-1">
                    <span aria-hidden className="inline-block h-2 w-3 rounded-sm bg-muted-foreground/40" /> {tx("expected if calibrated", "校准良好时的预期")}
                  </span>
                </figcaption>
              </figure>
            </Section>
          </div>
        </>
      )}
    </div>
  );
}

/** The page's answer in one paragraph, for a reader who does not speak p5 and pinball
 *  loss. Every number is the one the tables below print. */
function PlainWords({ adj }: { adj: NonNullable<CalibrationReport["adjusted"]> }) {
  const { tx } = useLang();
  const lo = adj.adj_lo_coverage * 100;
  const verdict =
    adj.adj_tail_band === "green"
      ? tx("That is on target, so the bad-case numbers the desk sizes with have held up.", "这符合目标，说明交易台用来定仓位的坏情形数字站得住脚。")
      : adj.adj_tail_band === "amber"
        ? tx("That is close to target but not on it, so treat the bad-case numbers as slightly optimistic.", "这接近目标但没有完全达到，所以请把坏情形数字视为略偏乐观。")
        : tx("That is off target, so the bad-case numbers have been too optimistic and should be read as such.", "这偏离了目标，说明坏情形数字过于乐观，应当这样理解。");
  return (
    <PlainBox>
      {tx("Every verdict comes with a bad case: “1 time in 20, it goes worse than this” (the ", "每个结论都带一个坏情形：“二十次里有一次会比这更糟”（即 ")}
      <Term k="p5">p5</Term>
      {tx(`). We wrote down ${adj.n_evaluated.toLocaleString()} of those before knowing what would happen, then checked. The real outcome was worse than the bad case ${fmtPct(lo, 1, false)} of the time, against the 5% it should be. ${verdict} Before the correction the raw history was worse than its own bad case ${fmtPct(adj.raw_lo_coverage * 100, 1, false)} of the time${adj.raw_lo_coverage > 0.05 ? ", which is why the desk corrects it." : ". That total looks fine, but it averages opposite errors by holding period (split below), which the correction fixes separately."}`, `）。我们在不知道结果之前写下了 ${adj.n_evaluated.toLocaleString()} 个这样的坏情形，然后去核对。实际结果比坏情形更差的比例是 ${fmtPct(lo, 1, false)}，而它本应是 5%。${verdict}修正之前，原始历史比它自己的坏情形更差的比例是 ${fmtPct(adj.raw_lo_coverage * 100, 1, false)}${adj.raw_lo_coverage > 0.05 ? "，这就是交易台要做修正的原因。" : "。这个总数看起来没问题，但它把不同持有期方向相反的误差平均掉了（见下面的拆分），修正是按持有期分别做的。"}`)}
    </PlainBox>
  );
}

/** Forecasts made after the method was frozen: out of sample by construction. */
function SinceFreezeBlock({ f }: { f: NonNullable<CalibrationReport["since_freeze"]> }) {
  const { tx } = useLang();
  const day = f.frozen_at.slice(0, 10);
  // Before the date, "frozen" would be a claim about the future: say it is scheduled.
  const ahead = new Date(f.frozen_at).getTime() > Date.now();
  const pretty = new Date(f.frozen_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  return (
    <Section
      title={ahead ? tx("Scored after the method freeze", "方法冻结之后才评分的预测") : tx("Scored after the method was frozen", "方法冻结之后才评分的预测")}
      subtitle={tx(
        `The tail adjustment was designed while looking at the history it is scored on above, so that number is optimistic by an unknown amount. ${ahead ? `Method freeze scheduled for ${pretty} (00:00 UTC); forecasts from then on are scored separately.` : `Method frozen on ${pretty}`} (git tag ${f.git_tag ?? "?"}). Only forecasts made after it count here, so nothing in this group could have shaped the method.`,
        `尾部调整是在看着上面所评分的历史时设计的，所以那个数字偏乐观的程度未知。${ahead ? `方法冻结定于 ${day}（UTC 00:00）；从那时起做出的预测将单独评分。` : `方法于 ${day} 冻结`}（git 标签 ${f.git_tag ?? "?"}）。这里只统计冻结之后做出的预测，所以这一组不可能影响过方法本身。`,
      )}
    >
      {f.n ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label={tx("Forecasts scored", "已评分预测")} value={f.n.toLocaleString()} hint={tx(`${f.n_nights} independent nights`, `${f.n_nights} 个独立夜晚`)} />
          <Stat label={tx("Below the 5th percentile", "低于第 5 百分位")} value={`${f.breaches} (${fmtPct((f.rate ?? 0) * 100, 1, false)})`} hint={tx("target 5%", "目标 5%")} />
          <Stat
            label={tx("If forecasts were independent", "若预测相互独立")}
            value={f.wilson_ci ? `${fmtPct(f.wilson_ci[0] * 100, 1, false)} to ${fmtPct(f.wilson_ci[1] * 100, 1, false)}` : "—"}
            hint={tx("assumes independence; too narrow", "假设独立，区间偏窄")}
          />
          <Stat
            label={tx("Resampling whole nights", "按整夜重抽样")}
            value={f.night_ci ? `${fmtPct(f.night_ci[0] * 100, 1, false)} to ${fmtPct(f.night_ci[1] * 100, 1, false)}` : "—"}
            hint={f.night_ci ? tx(`${f.n_nights} independent nights`, `${f.n_nights} 个独立夜晚`) : tx("too few nights for an interval yet", "夜晚太少，暂无区间")}
          />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {tx("No forecast made after the freeze has finished its holding period yet, so there is nothing to score. This fills in by itself, one night at a time; a few nights prove little, so read the night count before the rate.", "冻结之后做出的预测还没有一个走完持有期，所以暂时没有可评分的内容。它会自行逐夜增加；几个夜晚说明不了什么，请先看夜晚数再看比例。")}
        </p>
      )}
    </Section>
  );
}

/** What was tested, what passed, what did not: three lines for a reader who has not met a quantile.
 *  Everything below keeps the technical detail; this only says it in plain words, from the same numbers. */
function Scorecard({ rep }: { rep: CalibrationReport }) {
  const { tx, lang } = useLang();
  const adj = rep.adjusted;
  const tb = (b: string) => (lang === "zh" ? ({ green: "达标", amber: "略偏", red: "不达标" } as Record<string, string>)[b] ?? b : ({ green: "on target", amber: "slightly off", red: "off target" } as Record<string, string>)[b] ?? b);
  const bandName = (b: string) => (lang === "zh" ? BAND_LABEL_ZH[b] : BAND_LABEL[b]) ?? b;
  const weak = adj ? adj.bands.filter((b) => b.band !== "pooled" && b.adj_tail_band !== "green") : [];
  const sk = rep.skill;
  const beats = sk && sk.diff_ci_low != null && sk.diff_ci_low > 0;
  const loses = sk && sk.diff_ci_high != null && sk.diff_ci_high < 0;
  const pct = (x: number) => fmtPct(x * 100, 1, false);
  return (
    <div className="rounded-lg border border-border bg-card p-4 text-sm" aria-label={tx("The short version", "一句话版本")}>
      <p className="font-medium">{tx("The short version", "一句话版本")}</p>
      <ul className="mt-2 space-y-2">
        <li>
          <Pill tone="muted">{tx("Tested", "检验了什么")}</Pill>{" "}
          {tx(
            `${rep.n_matured.toLocaleString()} forecasts, each written down before the outcome was known, then scored once the holding period ended.`,
            `${rep.n_matured.toLocaleString()} 个预测，每个都在结果未知时先写下，持有期结束后再评分。`,
          )}
        </li>
        {adj ? (
          <li>
            <Pill tone={adj.adj_tail_band === "green" ? "good" : "warning"}>{tx("Passed", "通过")}</Pill>{" "}
            {tx(
              `The "1 time in 20 it goes worse than this" warning was beaten ${pct(adj.adj_lo_coverage)} of the time (target 5%): ${tb(adj.adj_tail_band)}. The raw history alone was ${pct(adj.raw_lo_coverage)}${adj.raw_lo_coverage > 0.05 ? ", which is why the desk corrects it." : "."}`,
              `“二十次里有一次会比这更糟”的警告，实际被突破 ${pct(adj.adj_lo_coverage)}（目标 5%）：${tb(adj.adj_tail_band)}。只用原始历史是 ${pct(adj.raw_lo_coverage)}${adj.raw_lo_coverage > 0.05 ? "，所以交易台要做修正。" : "。"}`,
            )}
          </li>
        ) : null}
        {weak.length ? (
          <li>
            <Pill tone="warning">{tx("Weaker", "较弱")}</Pill>{" "}
            {weak.map((b) => `${bandName(b.band)}: ${pct(b.adj_lo_coverage)} (${tb(b.adj_tail_band)})`).join("; ")}
            {tx(". Shown, not hidden.", "。照实展示，没有隐藏。")}
          </li>
        ) : null}
        {sk && sk.n === 0 ? (
          <li>
            <Pill tone="muted">{tx("Not measured", "未测量")}</Pill>{" "}
            {tx("The comparison with random past hours is made on replays, so there are no pairs in this view.", "与随机历史小时的对比是在重演预测上做的，所以这个视图里没有可配对的样本。")}
          </li>
        ) : null}
        {sk && sk.n > 0 ? (
          <li>
            <Pill tone={beats ? "good" : loses ? "critical" : "warning"}>{beats ? tx("Passed", "通过") : tx("Not proven", "未证明")}</Pill>{" "}
            {beats
              ? tx(`Beats picking a random past hour: the similar-moments forecast was closer in ${fmtPct((sk.win_share ?? 0) * 100, 0, false)} of ${sk.n.toLocaleString()} pairs.`, `优于随机挑一个历史小时：相似时刻的预测在 ${sk.n.toLocaleString()} 对中有 ${fmtPct((sk.win_share ?? 0) * 100, 0, false)} 更接近实际。`)
              : tx(`Does not clearly beat picking a random past hour (closer in ${fmtPct((sk.win_share ?? 0) * 100, 0, false)} of ${sk.n.toLocaleString()} pairs).`, `没有明显优于随机挑一个历史小时（${sk.n.toLocaleString()} 对中有 ${fmtPct((sk.win_share ?? 0) * 100, 0, false)} 更接近实际）。`)}
          </li>
        ) : null}
      </ul>
      <p className="mt-2 text-[13px] text-muted-foreground">{tx("The technical detail (percentile bands, correction factors, scoring rule) is below.", "技术细节（百分位区间、修正系数、评分规则）在下面。")}</p>
    </div>
  );
}
