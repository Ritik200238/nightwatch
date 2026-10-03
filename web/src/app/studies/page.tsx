"use client";

import { CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { LoadingRecord, PageHead, PlainBox, PROOF_WIDTH, ScrollTable } from "@/components/proof-page";
import { Term } from "@/components/term";
import { api, type StudiesResponse, type Study } from "@/lib/api";
import { fmtTimeL } from "@/lib/i18n";
import { useLang } from "@/lib/lang";

/** The verdict answers the question in the title, and nothing else.
 *
 *  It deliberately does not say whether the answer flattered us: "no, a token is not
 *  best explained by its own past" is why the search is pooled, and colouring that red
 *  would be lying about what the study found.
 */
const VERDICT: Record<Study["verdict"], { label: string; tone: "good" | "warning" | "muted"; Icon: typeof CheckCircle2 }> = {
  yes: { label: "yes", tone: "good", Icon: CheckCircle2 },
  no: { label: "no", tone: "warning", Icon: XCircle },
  unclear: { label: "cannot tell yet", tone: "muted", Icon: CircleHelp },
};

const STAT_LABEL_ZH: Record<string, string> = {
  sd_ratio_near_over_far: "近半部分的离散度 ÷ 远半部分",
  iqr_ratio_near_over_far: "近半部分的四分位距 ÷ 远半部分",
  share_near_tighter: "近的一半更集中的时刻占比",
  breach_equal: "低于 p5 的结果，等权重",
  "breach_similarity (already computed)": "低于 p5 的结果，按相似度加权",
  pooled_lo_coverage: "单一系数：低于 p5 的结果，总体",
  pooled_lo_overnight: "单一系数：隔夜",
  pooled_lo_multi_day: "单一系数：多日",
  banded_lo_overnight: "按持有期分别拟合：隔夜",
  banded_lo_multi_day: "按持有期分别拟合：多日",
  pooled_width_multi_day: "单一系数：多日区间宽度",
  banded_width_multi_day: "按持有期分别拟合：多日区间宽度",
  heldout_lo_batch: "留出检验，我们实际采用的",
  heldout_lo_online: "留出检验，在线更新",
  mean_move_farthest_quartile: "最远四分之一之后的波动",
  mean_move_closest_quartile: "最近四分之一之后的波动",
  pooled_t: "t 值，合并",
  clustered_t: "t 值，按代币聚类",
  raw_diff: "突破率，分歧最大的三分之一减最小的三分之一",
  raw_t: "t 值，仅看分歧（三等分）",
  alone_t: "t 值，仅看分歧（斜率）",
  controlled_t: "t 值，固定规模后的分歧",
  size_t: "t 值，实际采用数字的大小",
  controlled_up: "分歧仍有预测力的代币数",
  ensemble_t: "t 值，各版本中位数 vs 实际采用",
  ensemble_up: "中位数更优的代币数",
  breach_shipped: "低于实际采用 p5 的结果",
  breach_ensemble: "低于各版本中位数 p5 的结果",
  breach_narrow: "低于 p5 的结果，最窄的三分之一",
  breach_wide: "低于 p5 的结果，最宽的三分之一",
  median_spread: "分歧中位数，占实际采用数字的比例",
  versions: "引擎版本数",
  breach_own_token: "低于 p5 的结果，同代币相似时刻",
  breach_other_tokens: "低于 p5 的结果，其他代币相似时刻",
  boot_ci_low: "自助法区间，下限",
  boot_ci_high: "自助法区间，上限",
  move_flagged: "被标记的披露之后的波动",
  move_rest: "其余披露之后的波动",
  n_flagged: "被标记的披露数",
  n_rest: "未被标记的披露数",
  tokens_agreeing: "成立的代币数",
  hit_rate: "方向判断正确率",
  ci_low: "区间，下限",
  ci_high: "区间，上限",
  share_committed: "它给出明确判断的披露占比",
  n_called: "做出方向判断的次数",
  n_read: "读取的披露数",
  conditions_judged: "有明确结论的条件数",
  conditions_better: "收窄后评分更好的条件数",
  conditions_worse: "收窄后评分更差的条件数",
};

/** Stat keys are machine names; these are what a person would call them. Anything not
 *  named here still shows, with the underscores turned back into spaces. */
const STAT_LABEL: Record<string, string> = {
  sd_ratio_near_over_far: "spread of near half ÷ far half",
  iqr_ratio_near_over_far: "IQR of near half ÷ far half",
  share_near_tighter: "moments where near was tighter",
  breach_equal: "outcomes below p5, equal weighting",
  "breach_similarity (already computed)": "outcomes below p5, similarity weighting",
  pooled_lo_coverage: "one factor: outcomes below p5, overall",
  pooled_lo_overnight: "one factor: overnight",
  pooled_lo_multi_day: "one factor: multi-day",
  banded_lo_overnight: "per holding period: overnight",
  banded_lo_multi_day: "per holding period: multi-day",
  pooled_width_multi_day: "one factor: multi-day band width",
  banded_width_multi_day: "per holding period: multi-day band width",
  heldout_lo_batch: "held out, what we ship",
  heldout_lo_online: "held out, online update",
  mean_move_farthest_quartile: "move after the farthest quarter",
  mean_move_closest_quartile: "move after the closest quarter",
  pooled_t: "t, pooled",
  clustered_t: "t, clustered by token",
  raw_diff: "breach rate, most-disagreed third minus least",
  raw_t: "t, disagreement alone (thirds)",
  alone_t: "t, disagreement alone (slope)",
  controlled_t: "t, disagreement with size held fixed",
  size_t: "t, size of the shipped number",
  controlled_up: "tokens where disagreement still predicts",
  ensemble_t: "t, median of versions vs shipped",
  ensemble_up: "tokens where the median wins",
  breach_shipped: "outcomes below shipped p5",
  breach_ensemble: "outcomes below median-of-versions p5",
  breach_narrow: "outcomes below p5, narrowest third",
  breach_wide: "outcomes below p5, widest third",
  median_spread: "median disagreement, as a share of the shipped number",
  versions: "versions of the engine",
  breach_own_token: "outcomes below p5, same-token analogs",
  breach_other_tokens: "outcomes below p5, other-token analogs",
  boot_ci_low: "bootstrap interval, low",
  boot_ci_high: "bootstrap interval, high",
  move_flagged: "move after a flagged filing",
  move_rest: "move after the rest",
  n_flagged: "filings flagged",
  n_rest: "filings not flagged",
  tokens_agreeing: "tokens where it holds",
  hit_rate: "directional calls correct",
  ci_low: "interval, low",
  ci_high: "interval, high",
  share_committed: "filings it committed to",
  n_called: "directional calls made",
  n_read: "filings read",
  conditions_judged: "conditions with a decided answer",
  conditions_better: "narrowing scored better",
  conditions_worse: "narrowing scored worse",
};

/** Per-condition results, for a study whose stats are keyed "condition.metric".
 *
 *  Sixty numbers in a grid would bury the one comparison that matters, which is the
 *  same two columns for each condition: how often the unfiltered tail was breached and
 *  how often the narrowed one was, against a target of 5%.
 */
function ConditionTable({ stats, labels }: { stats: Record<string, number>; labels: Record<string, string> }) {
  const { tx } = useLang();
  const byCondition = new Map<string, Record<string, number>>();
  for (const [k, v] of Object.entries(stats)) {
    const dot = k.indexOf(".");
    if (dot < 0) continue;
    const name = k.slice(0, dot);
    const row = byCondition.get(name) ?? {};
    row[k.slice(dot + 1)] = v;
    byCondition.set(name, row);
  }
  if (!byCondition.size) return null;
  const rows = [...byCondition.entries()].sort((a, b) => (b[1].n ?? 0) - (a[1].n ?? 0));
  const pct = (v: number | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
  const num = (v: number | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : v.toFixed(d));
  return (
    <div>
      <ScrollTable>
      <table className="w-full min-w-[560px] text-[13px]">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-1 pr-3 font-medium">{tx("condition", "条件")}</th>
            <th className="py-1 pr-3 text-right font-medium">{tx("nights", "夜数")}</th>
            <th className="py-1 pr-3 text-right font-medium">{tx("below p5, all hours", "低于 p5，全部小时")}</th>
            <th className="py-1 pr-3 text-right font-medium">{tx("below p5, narrowed", "低于 p5，收窄后")}</th>
            <th className="py-1 pr-3 text-right font-medium">{tx("typical p5, all → narrowed", "典型 p5：全部 → 收窄后")}</th>
            <th className="py-1 text-right font-medium"><Term k="clustered">{tx("t, by token", "t 值，按代币")}</Term></th>
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map(([name, r]) => (
            <tr key={name} className="border-b border-border/50">
              <td className="py-1 pr-3">{labels[name] ?? name.replace(/_/g, " ")}</td>
              <td className="py-1 pr-3 text-right">{num(r.n, 0)}</td>
              <td className="py-1 pr-3 text-right">{pct(r.breach_all)}</td>
              <td className="py-1 pr-3 text-right">
                {pct(r.breach_lens)}
                {r.breach_lens_lo != null ? <span className="text-muted-foreground"> [{pct(r.breach_lens_lo)}–{pct(r.breach_lens_hi)}]</span> : null}
              </td>
              <td className="py-1 pr-3 text-right">
                {r.p5_all_median != null ? `${num(r.p5_all_median, 1)}% → ${num(r.p5_lens_median, 1)}%` : "—"}
              </td>
              <td className="py-1 text-right">{num(r.t_clustered, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </ScrollTable>
      <p className="mt-1 text-muted-foreground">{tx("Target for both breach columns is 5%. A positive t means the narrowed tail scored better.", "两列突破率的目标都是 5%。t 为正表示收窄后的尾部评分更好。")}</p>
    </div>
  );
}

/** The verdict in one line, for the collapsed header.
 *
 *  The header keeps showing its summary while the section is open, which is right when
 *  the summary is a digest of stats and wrong when it is the finding itself — the whole
 *  paragraph would then be printed twice, once small and grey and once properly. So the
 *  header gets the answer and the body gets the argument.
 */
function firstSentence(text: string): string {
  const m = text.match(/^.*?[.?!](?=\s|$)/);
  return m ? m[0] : text;
}

/** Shares are printed as percentages and everything else at three places, because a
 *  t-statistic rendered as "215%" is worse than no label at all. */
function statValue(key: string, v: number): string {
  const isShare =
    key.startsWith("breach_") ||
    key.startsWith("pooled_lo") ||
    key.startsWith("banded_lo") ||
    key.startsWith("heldout_lo") ||
    key === "share_near_tighter" ||
    key === "hit_rate" ||
    key === "ci_low" ||
    key === "ci_high" ||
    key === "share_committed";
  if (isShare) return `${(v * 100).toFixed(1)}%`;
  if (key.includes("width") || key.startsWith("mean_move") || key.startsWith("move_")) return `${v.toFixed(2)}%`;
  return Number.isInteger(v) ? String(v) : v.toFixed(3);
}

/** Very small p-values are printed as a bound; a reader cannot use "0.0000023". */
function fmtP(p: number): string {
  if (p < 0.001) return "< 0.001";
  return p < 0.1 ? p.toFixed(3) : p.toFixed(2);
}

/** One line of evidence per study: the raw p, the p after the correction, and whether the
 *  result is still standing once the number of questions asked is paid for. */
function Significance({ s, m }: { s: Study; m: number | undefined }) {
  const { tx } = useLang();
  if (s.p_value == null) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
        <span title={s.p_method}>{tx("No p-value: this is not a hypothesis test, so it is not part of the correction.", "没有 p 值：这不是假设检验，因此不参与多重检验校正。")}</span>
        {s.small_sample ? <Pill tone="warning">{tx("small sample", "样本量小")}</Pill> : null}
        {s.small_sample && s.small_sample_note ? <span>{s.small_sample_note}</span> : null}
      </div>
    );
  }
  const survives = s.survives_fdr === true;
  return (
    <div className="space-y-1 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="tabular">
          p = {fmtP(s.p_value)}
          {s.q_value != null ? tx(`, after correcting for ${m ?? "all"} questions q = ${fmtP(s.q_value)}`, `，校正 ${m ?? "全部"} 个问题后 q = ${fmtP(s.q_value)}`) : ""}
        </span>
        {s.survives_fdr != null ? <Pill tone={survives ? "good" : "warning"}>{survives ? tx("survives", "经得起校正") : tx("does not survive", "经不起校正")}</Pill> : null}
        {s.small_sample ? <Pill tone="warning">{tx("small sample", "样本量小")}</Pill> : null}
      </div>
      {s.p_method ? <p className="text-muted-foreground">{s.p_method}</p> : null}
      {s.small_sample && s.small_sample_note ? <p className="text-muted-foreground">{s.small_sample_note}</p> : null}
    </div>
  );
}

export default function StudiesPage() {
  const { tx, lang } = useLang();
  const statLabel = (k: string) => (lang === "zh" ? STAT_LABEL_ZH[k] : undefined) ?? STAT_LABEL[k] ?? k.replace(/_/g, " ");
  const verdictLabel = (k: Study["verdict"]) => (lang === "zh" ? { yes: "是", no: "否", unclear: "暂时无法判断" }[k] : VERDICT[k].label);
  const [rep, setRep] = useState<StudiesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lensLabels, setLensLabels] = useState<Record<string, string>>({});

  useEffect(() => {
    api
      .studies()
      .then(setRep)
      .catch((e) => setError(e instanceof Error ? e.message : tx("Could not load the studies.", "无法加载研究。")));
    // The names a trader sees for each condition. Missing labels fall back to the
    // machine name, so a failed request costs wording, not the table.
    api
      .lenses()
      .then((r) => setLensLabels(Object.fromEntries(r.lenses.map((l) => [l.name, l.label]))))
      .catch(() => undefined);
  }, []);

  const yes = rep?.studies.filter((s) => s.verdict === "yes").length ?? 0;
  const no = rep?.studies.filter((s) => s.verdict === "no").length ?? 0;
  const unclear = rep?.studies.filter((s) => s.verdict === "unclear").length ?? 0;

  return (
    <div className={`${PROOF_WIDTH} space-y-4`}>
      <PageHead
        tabs
        title={tx("What we tested about our own retrieval", "我们对自己的检索做了哪些检验")}
        intro={
          <>
            {tx("The desk finds past moments (", "交易台会找出与眼前相似的历史时刻（")}
            <Term k="analog">{tx("analogs", "相似时刻")}</Term>
            {tx(") like the one in front of you and reports what followed. These are the claims underneath it, written so they could fail, each tested against this database and reported whichever way it came out.", "），并报告后来发生了什么。这些是它背后的主张，每一条都写成可能被证伪的形式，用这个数据库逐一检验，无论结果如何都如实报告。")}
          </>
        }
      />
      {rep?.studies.length ? (
        <PlainBox>
          {tx(`We asked ${rep.studies.length} questions, each written so the answer could be no. ${yes} came back yes, ${no} came back no, and ${unclear} cannot be told yet. `, `我们提出了 ${rep.studies.length} 个问题，每个都写成可能得到“否”的形式。${yes} 个回答为是，${no} 个回答为否，${unclear} 个暂时无法判断。`)}
          {rep.fdr
            ? tx(`Because so many questions were asked at once, a lucky “yes” is likely, so the results are corrected for that (`, `因为同时问了这么多问题，很容易碰巧得到“是”，所以结果做了校正（`)
            : null}
          {rep.fdr ? <Term k="fdr" /> : null}
          {rep.fdr ? tx(`): ${rep.fdr.yes_survive} of ${rep.fdr.yes_tested} “yes” answers survive. `, `）：${rep.fdr.yes_tested} 个“是”的回答中有 ${rep.fdr.yes_survive} 个经得起校正。`) : null}
          {tx("The answers that came back no matter as much as the yeses: they show where the obvious improvement makes the forecast worse, and where a market ", "回答为否的问题和回答为是的一样重要：它们说明了哪些看似显而易见的改进反而让预测变差，以及哪种市场")}
          <Term k="regime" />
          {tx(" needs its own treatment.", "需要单独处理。")}
        </PlainBox>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="font-medium">{tx("Couldn't load the studies", "无法加载研究")}</p>
          <p className="text-[13px] text-muted-foreground">{error}</p>
        </div>
      ) : null}

      {!rep && !error ? (
        <LoadingRecord blocks={[96, 192, 192]} />
      ) : null}

      {rep && !rep.studies.length ? (
        <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          {rep.note || tx("No studies have been run against this database yet.", "还没有对这个数据库运行过任何研究。")}
        </div>
      ) : null}

      {rep?.studies.length ? (
        <>
          <Section
            title={tx("The scoreboard", "记分牌")}
            subtitle={tx(`Last recomputed ${rep.last_run ? fmtTimeL(rep.last_run, lang) : "unknown"}. Every number on this page is derived from the stored bars and the journal by \`nightwatch studies\`; none of it is typed in.`, `上次重新计算：${rep.last_run ? fmtTimeL(rep.last_run, lang) : "未知"}。本页的每个数字都由 \`nightwatch studies\` 从存储的 K 线和日志推导而来，没有一个是手填的。`)}
          >
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <Stat label={tx("Questions asked", "提出的问题")} value={String(rep.studies.length)} hint={tx("each written so it could come back no", "每个都写成可能得到“否”的形式")} />
              <Stat label={tx("Answered yes", "回答为是")} value={String(yes)} hint={tx("and acted on", "并据此采取了行动")} tone={yes ? "good" : undefined} />
              <Stat label={tx("Answered no", "回答为否")} value={String(no)} hint={tx("which is the more useful half", "这是更有用的那一半")} tone={no ? "warning" : undefined} />
              <Stat label={tx("Cannot tell yet", "暂时无法判断")} value={String(unclear)} hint={tx("not enough matured history", "已到期的历史不够多")} />
            </div>
            {rep.fdr ? (
              <p className="mt-3 text-[13px] text-muted-foreground">
                {tx(`Asking ${rep.fdr.m_tests} testable questions at once makes a lucky “yes” likely, so the p-values are corrected together (Benjamini–Hochberg, a ${Math.round(rep.fdr.alpha * 100)}% false-discovery rate). ${rep.fdr.yes_survive} of ${rep.fdr.yes_tested} “yes” answers survive the correction${rep.fdr.yes_fail.length ? `. The other ${rep.fdr.yes_fail.length} should be read as leads, not settled findings` : ""}. The remaining ${rep.fdr.m_studies - rep.fdr.m_tests} ${rep.fdr.m_studies - rep.fdr.m_tests === 1 ? "study is" : "studies are"} not hypothesis tests and carry no p-value.`, `同时提出 ${rep.fdr.m_tests} 个可检验的问题，很容易碰巧得到“是”，所以对 p 值统一做了校正（Benjamini–Hochberg，假发现率 ${Math.round(rep.fdr.alpha * 100)}%）。${rep.fdr.yes_tested} 个回答为“是”的问题中有 ${rep.fdr.yes_survive} 个经得起校正${rep.fdr.yes_fail.length ? `；其余 ${rep.fdr.yes_fail.length} 个应当视为线索，而不是定论` : ""}。剩下的 ${rep.fdr.m_studies - rep.fdr.m_tests} 项研究不是假设检验，没有 p 值。`)}
              </p>
            ) : null}
            <p className="mt-3 text-[13px] text-muted-foreground">
              {tx("A study that nobody acted on is decoration, so each one below ends with what changed because of it — including “nothing, and here is why that is the right answer”. The calibration behind two of these is on the", "没人据此行动的研究只是摆设，所以下面每一项都以“因此改变了什么”结尾——包括“什么都没改，以及为什么这是正确答案”。其中两项背后的校准在")}{" "}
              <Link href="/calibration" className="underline underline-offset-2">
                {tx("calibration page", "校准页面")}
              </Link>
              {tx(".", "。")}
            </p>
          </Section>

          {rep.studies.map((s) => {
            const v = VERDICT[s.verdict];
            return (
              <Section
                key={s.key}
                collapsible
                summary={
                  <>
                    <span className="block text-[13px]">{s.question}</span>
                    <span className="mt-1 block text-[13px] font-medium text-foreground">{firstSentence(s.finding)}</span>
                  </>
                }
                title={s.title}
                action={
                  <Pill tone={v.tone}>
                    <v.Icon className="mr-1 h-3 w-3" aria-hidden />
                    {verdictLabel(s.verdict)}
                  </Pill>
                }
              >
                <div className="space-y-3 text-sm">
                  <div>
                    <p className="text-[13px] font-medium tracking-wide text-muted-foreground uppercase">{tx("How it was tested", "怎么检验的")}</p>
                    <p className="mt-1 text-muted-foreground">{s.method}</p>
                  </div>
                  <div>
                    <p className="text-[13px] font-medium tracking-wide text-muted-foreground uppercase">{tx("What came back", "结果如何")}</p>
                    <p className="mt-1 leading-relaxed">{s.finding}</p>
                  </div>
                  <Significance s={s} m={rep.fdr?.m_tests} />
                  <div className="rounded-lg border border-border bg-muted/30 p-3">
                    <p className="text-[13px] font-medium tracking-wide text-muted-foreground uppercase">{tx("What changed because of it", "因此改变了什么")}</p>
                    <p className="mt-1 leading-relaxed">{s.consequence}</p>
                  </div>
                  {Object.keys(s.stats).length ? (
                    <div>
                      <p className="mb-2 text-[13px] font-medium tracking-wide text-muted-foreground uppercase">{tx(`The numbers (${s.n.toLocaleString()} observations)`, `数字（${s.n.toLocaleString()} 个观测）`)}</p>
                      <ConditionTable stats={s.stats} labels={lensLabels} />
                      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[13px] lg:grid-cols-3">
                        {Object.entries(s.stats).filter(([k]) => !k.includes(".")).map(([k, val]) => (
                          <div key={k} className="flex items-baseline justify-between gap-2 border-b border-border/50 py-1">
                            <span className="min-w-0 text-muted-foreground">{statLabel(k)}</span>
                            <span className="tabular shrink-0 font-medium">{statValue(k, val)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </Section>
            );
          })}
        </>
      ) : null}
    </div>
  );
}
