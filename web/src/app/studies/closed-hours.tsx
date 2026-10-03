"use client";

import { CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { ScrollTable } from "@/components/proof-page";
import { type ClosedHours, type Est } from "@/lib/api";
import { fmtTimeL } from "@/lib/i18n";
import { useLang } from "@/lib/lang";

/** A measured study, not a test: it sits under the studies and is outside their correction.
 *
 *  Everything printed here is read from the committed result of
 *  research/closed_hours.py; no number is typed in. Each estimate carries its 95% interval
 *  from a block bootstrap over calendar weeks, so a reader can see how much of a
 *  difference is noise.
 */

const pct = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(d)}%`);
const num = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : v.toFixed(d));
const times = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(d)}×`);

/** "38.6% [34.4–43.3%]" */
function withCi(e: Est | undefined, fmt: (v: number | null | undefined) => string): string {
  if (!e || e.est == null) return "—";
  return e.lo == null || e.hi == null ? fmt(e.est) : `${fmt(e.est)} [${fmt(e.lo)}–${fmt(e.hi)}]`;
}

const ANCHOR_ORDER = ["weekend_only", "to_premarket_start", "to_preopen"] as const;

export function ClosedHoursSection({ ch }: { ch: ClosedHours }) {
  const { tx, lang } = useLang();
  const mv = ch.movement.primary.stats;
  const hourly = ch.movement.hourly_tally?.stats;
  const wk = ch.weekend;
  const liq = ch.liquidity;
  // Said only when the interval backs it: the sentence is prose around numbers that a re-run can change.
  const quieter = (mv.per_hour_var_ratio?.hi ?? 1) < 1 && (hourly?.abs_share?.hi ?? 1) < (mv.time_share?.lo ?? 0);
  const verdict = wk?.verdict ?? "unclear";
  const verdictLabel = lang === "zh" ? { yes: "是", no: "否", unclear: "暂时无法判断" }[verdict] : { yes: "yes", no: "no", unclear: "cannot tell yet" }[verdict];
  const VerdictIcon = verdict === "yes" ? CheckCircle2 : verdict === "no" ? XCircle : CircleHelp;
  const tone = verdict === "yes" ? "good" : verdict === "no" ? "warning" : "muted";

  const anchorLabel: Record<string, string> = {
    weekend_only: tx("Fri 20:00 → Mon 04:00 ET, no US venue open", "周五 20:00 → 周一 04:00（美东），美国交易场所均未开市"),
    to_premarket_start: tx("Fri close → Mon 04:00 ET, adds Friday after-hours", "周五收盘 → 周一 04:00（美东），加上周五盘后"),
    to_preopen: tx("Fri close → Mon 09:00 ET, adds Monday pre-market", "周五收盘 → 周一 09:00（美东），再加上周一盘前"),
  };
  const kindRows: { key: string; label: string }[] = [
    { key: "overnight", label: tx("Weeknights", "工作日夜间") },
    { key: "weekend", label: tx("Weekends", "周末") },
    { key: "holiday", label: tx("Weekday holidays", "工作日休市日") },
  ];
  const liqRows: { key: string; label: string }[] = [
    { key: "overnight", label: tx("Weeknights", "工作日夜间") },
    { key: "weekend", label: tx("Weekends", "周末") },
    { key: "sunday_3am", label: tx("Sunday 02:00–04:00 ET", "周日 02:00–04:00（美东）") },
  ];

  const tokens = ch.movement.primary.per_token ?? [];
  const sorted = [...tokens].sort((a, b) => (b.var_share.est ?? 0) - (a.var_share.est ?? 0));

  return (
    <Section
      title={tx("What the tokens do while the US market is shut", "美国股市休市时，代币在做什么")}
      subtitle={tx(
        `Measured, not tested: it adds no question to the count above. ${ch.data.tokens} tokens, ${ch.data.first_day} to ${ch.data.last_day}, computed ${fmtTimeL(ch.ran_at, lang)} by research/closed_hours.py. Every interval is 95%, from a ${ch.settings.block_weeks}-week block bootstrap over calendar weeks with all tokens resampled together.`,
        `这是测量，不是检验：不会增加上面的问题数。${ch.data.tokens} 个代币，${ch.data.first_day} 至 ${ch.data.last_day}，由 research/closed_hours.py 于 ${fmtTimeL(ch.ran_at, lang)} 计算。所有区间均为 95%，来自按日历周做的 ${ch.settings.block_weeks} 周分块自助法，所有代币一起重抽样。`,
      )}
    >
      <div className="space-y-6 text-sm">
        {/* ------------------------------------------------------------ Q1 */}
        <div className="space-y-3">
          <p className="text-[13px] font-medium tracking-wide text-muted-foreground uppercase">
            {tx("1. How much of the movement happens while the market is shut?", "1. 有多少价格波动发生在休市期间？")}
          </p>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            <Stat
              label={tx("Share of the clock", "占时间的比例")}
              value={pct(mv.time_share?.est, 0)}
              hint={tx("hours the US cash market is shut", "美国现货市场休市的小时数")}
            />
            <Stat
              label={tx("Share of the movement", "占波动的比例")}
              value={pct(mv.var_share?.est, 1)}
              hint={tx(`variance, ${withCi(mv.var_share, (v) => pct(v, 1))}`, `方差，${withCi(mv.var_share, (v) => pct(v, 1))}`)}
            />
            <Stat
              label={tx("A shut hour vs an open hour", "休市一小时 vs 开市一小时")}
              value={times(mv.per_hour_var_ratio?.est, 2)}
              hint={tx(`variance per hour, ${withCi(mv.per_hour_var_ratio, (v) => times(v, 2))}`, `每小时方差，${withCi(mv.per_hour_var_ratio, (v) => times(v, 2))}`)}
            />
            <Stat
              label={tx("Hourly tally, absolute moves", "逐小时累加绝对涨跌幅")}
              value={pct(hourly?.abs_share?.est, 1)}
              hint={tx(`how a simple sum is counted, ${withCi(hourly?.abs_share, (v) => pct(v, 1))}`, `简单累加的算法，${withCi(hourly?.abs_share, (v) => pct(v, 1))}`)}
            />
          </div>
          <p className="leading-relaxed">
            {tx(
              `The market is shut for ${pct(mv.time_share?.est, 0)} of the week, so a claim that most movement happens in closed hours is true of anything that moves at a steady rate. The question that means something is movement per hour: a shut hour carried ${times(mv.per_hour_var_ratio?.est, 2)} the variance of an open hour (${withCi(mv.per_hour_var_ratio, (v) => times(v, 2))}). By variance ${pct(mv.var_share?.est, 0)} of the movement happened while shut; counting summed absolute hourly moves instead gives ${pct(hourly?.abs_share?.est, 0)}.${quieter ? ` Both are far below the ${pct(mv.time_share?.est, 0)} the clock would give: per hour, closed time was quieter than open time.` : ""}`,
              `休市占一周时间的 ${pct(mv.time_share?.est, 0)}，所以“大部分波动发生在休市期间”这种说法，对任何匀速波动的东西都成立。有意义的问题是每小时的波动：休市一小时的方差是开市一小时的 ${times(mv.per_hour_var_ratio?.est, 2)}（${withCi(mv.per_hour_var_ratio, (v) => times(v, 2))}）。按方差算，${pct(mv.var_share?.est, 0)} 的波动发生在休市期间；改成逐小时累加绝对涨跌幅则是 ${pct(hourly?.abs_share?.est, 0)}。${quieter ? `两者都远低于按时间计算的 ${pct(mv.time_share?.est, 0)}：按每小时算，休市时段比开市时段更平静。` : ""}`,
            )}
          </p>
          <ScrollTable>
            <table className="w-full min-w-[520px] text-[13px]">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-1 pr-3 font-medium">{tx("Kind of closed stretch", "休市类型")}</th>
                  <th className="py-1 pr-3 text-right font-medium">{tx("Share of all movement", "占全部波动")}</th>
                  <th className="py-1 text-right font-medium">{tx("Variance per hour vs an open hour", "每小时方差 ÷ 开市时")}</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {kindRows.map((k) => (
                  <tr key={k.key} className="border-b border-border/50">
                    <td className="py-1 pr-3">{k.label}</td>
                    <td className="py-1 pr-3 text-right">{withCi(mv[`var_share_${k.key}`], (v) => pct(v, 1))}</td>
                    <td className="py-1 text-right">{withCi(mv[`per_hour_var_ratio_${k.key}`], (v) => times(v, 2))}</td>
                  </tr>
                ))}
                <tr className="border-b border-border/50 text-muted-foreground">
                  <td className="py-1 pr-3">{tx("Open session (09:00–16:00 ET)", "开市时段（美东 09:00–16:00）")}</td>
                  <td className="py-1 pr-3 text-right">{withCi(mv.var_share_open, (v) => pct(v, 1))}</td>
                  <td className="py-1 text-right">1.00×</td>
                </tr>
              </tbody>
            </table>
          </ScrollTable>
          <p className="text-[13px] text-muted-foreground">
            {tx(
              `Same question, other populations. Windows with a fresh price at both ends: ${pct(ch.movement.fresh_only.stats.var_share?.est, 1)}. Leaving out windows that touch an earnings date: ${withCi(ch.movement.no_earnings.stats.var_share, (v) => pct(v, 1))} (the earnings table starts in September 2025, so this removes only the earnings it knows). n = ${ch.movement.primary.n_windows.toLocaleString()} windows over ${ch.movement.primary.n_weeks ?? "—"} weeks.`,
              `同一问题，换个样本。两端价格都新鲜的窗口：${pct(ch.movement.fresh_only.stats.var_share?.est, 1)}。剔除碰到财报日的窗口：${withCi(ch.movement.no_earnings.stats.var_share, (v) => pct(v, 1))}（财报表从 2025 年 9 月才开始，所以只剔除了它已知的财报）。n = ${ch.movement.primary.n_windows.toLocaleString()} 个窗口，跨 ${ch.movement.primary.n_weeks ?? "—"} 周。`,
            )}
          </p>
          {sorted.length ? (
            <details className="text-[13px]">
              <summary className="cursor-pointer text-muted-foreground">{tx(`Each of the ${sorted.length} tokens`, `逐个代币（共 ${sorted.length} 个）`)}</summary>
              <div className="mt-2">
                <ScrollTable>
                  <table className="w-full min-w-[480px]">
                    <thead>
                      <tr className="border-b border-border text-left text-muted-foreground">
                        <th className="py-1 pr-3 font-medium">{tx("Token", "代币")}</th>
                        <th className="py-1 pr-3 text-right font-medium">{tx("Share of movement while shut", "休市期间的波动占比")}</th>
                        <th className="py-1 pr-3 text-right font-medium">{tx("Shut hour vs open hour", "休市小时 ÷ 开市小时")}</th>
                        <th className="py-1 text-right font-medium">n</th>
                      </tr>
                    </thead>
                    <tbody className="tabular">
                      {sorted.map((t) => (
                        <tr key={t.ticker} className="border-b border-border/50">
                          <td className="py-1 pr-3">{t.ticker}</td>
                          <td className="py-1 pr-3 text-right">{withCi(t.var_share, (v) => pct(v, 0))}</td>
                          <td className="py-1 pr-3 text-right">{withCi(t.per_hour_var_ratio, (v) => times(v, 2))}</td>
                          <td className="py-1 text-right">{t.n_windows.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollTable>
              </div>
            </details>
          ) : null}
        </div>

        {/* ------------------------------------------------------------ Q2 */}
        {wk ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[13px] font-medium tracking-wide text-muted-foreground uppercase">
                {tx("2. Is the token's weekend move informative about Monday's open?", "2. 代币的周末涨跌，能否预示周一开盘？")}
              </p>
              <Pill tone={tone}>
                <VerdictIcon className="mr-1 h-3 w-3" aria-hidden />
                {verdictLabel}
              </Pill>
            </div>
            <p className="leading-relaxed">
              {tx(
                `Judged on the strictest cut, Friday 20:00 to Monday 04:00 ET, when no US venue is open: the token's move had a slope of ${withCi(wk.primary.stats.slope_open, (v) => num(v, 2))} on Monday's gap (1.0 would mean the stock opens exactly where the token went). On moves of 1% or more the stock's gap had the token's sign ${withCi(wk.primary.stats.hit_rate_big, (v) => pct(v, 0))} of the time. After a weekend the token rose, the stock's open averaged ${pct(wk.primary.stats.gap_after_up_minus_down?.est, 1)} higher than after one it fell (${withCi(wk.primary.stats.gap_after_up_minus_down, (v) => pct(v, 1))}). Predicting the gap out of sample with a slope fitted only on earlier weekends cut the squared error by ${withCi(wk.primary.stats.oos_skill, (v) => pct(v, 0))} against predicting no gap. n = ${wk.primary.n.toLocaleString()} weekends over ${wk.primary.n_weeks} weeks; ${wk.primary.tokens_with_positive_slope} of ${wk.primary.tokens_scored} tokens have a positive slope.`,
                `按最严格的口径判断，即周五 20:00 到周一 04:00（美东），此时美国没有任何交易场所开市：代币涨跌对周一跳空的斜率为 ${withCi(wk.primary.stats.slope_open, (v) => num(v, 2))}（1.0 表示股票开盘恰好落在代币走到的位置）。在涨跌幅达到 1% 以上的周末，股票跳空方向与代币一致的比例是 ${withCi(wk.primary.stats.hit_rate_big, (v) => pct(v, 0))}。代币上涨的周末之后，股票开盘平均比下跌的周末之后高 ${pct(wk.primary.stats.gap_after_up_minus_down?.est, 1)}（${withCi(wk.primary.stats.gap_after_up_minus_down, (v) => pct(v, 1))}）。只用更早的周末拟合斜率、再做样本外预测，平方误差比“预测没有跳空”低 ${withCi(wk.primary.stats.oos_skill, (v) => pct(v, 0))}。n = ${wk.primary.n.toLocaleString()} 个周末，跨 ${wk.primary.n_weeks} 周；${wk.primary.tokens_scored} 个代币中有 ${wk.primary.tokens_with_positive_slope} 个斜率为正。`,
              )}
            </p>
            <ScrollTable>
              <table className="w-full min-w-[720px] text-[13px]">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-1 pr-3 font-medium">{tx("Token move measured", "代币涨跌的取值区间")}</th>
                    <th className="py-1 pr-3 text-right font-medium">n</th>
                    <th className="py-1 pr-3 text-right font-medium">{tx("Slope on Monday's gap", "对周一跳空的斜率")}</th>
                    <th className="py-1 pr-3 text-right font-medium">{tx("Correlation", "相关系数")}</th>
                    <th className="py-1 pr-3 text-right font-medium">{tx("Slope on Monday's close", "对周一收盘的斜率")}</th>
                    <th className="py-1 text-right font-medium">{tx("Out-of-sample gain", "样本外改善")}</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {ANCHOR_ORDER.map((a) => {
                    const b = wk.by_anchor[a];
                    if (!b) return null;
                    return (
                      <tr key={a} className="border-b border-border/50 align-top">
                        <td className="py-1 pr-3">{anchorLabel[a]}</td>
                        <td className="py-1 pr-3 text-right">{b.n.toLocaleString()}</td>
                        <td className="py-1 pr-3 text-right">{withCi(b.stats.slope_open, (v) => num(v, 2))}</td>
                        <td className="py-1 pr-3 text-right">{withCi(b.stats.corr_open, (v) => num(v, 2))}</td>
                        <td className="py-1 pr-3 text-right">{withCi(b.stats.slope_close, (v) => num(v, 2))}</td>
                        <td className="py-1 text-right">{withCi(b.stats.oos_skill, (v) => pct(v, 0))}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </ScrollTable>
            <p className="leading-relaxed text-muted-foreground">
              {tx(
                `Why three rows. We first measured only the last one and got a correlation of ${num(wk.by_anchor.to_preopen?.stats.corr_open?.est, 2)}, which is too good to be about the weekend: US stocks trade pre-market from 04:00 ET and the token follows them, so a token price at 09:00 Monday has already seen the stock's pre-market. We added the two stricter cuts after seeing that and judge the verdict on the strictest. The correlation falls from ${num(wk.by_anchor.to_preopen?.stats.corr_open?.est, 2)} to ${num(wk.primary.stats.corr_open?.est, 2)} once the pre-market is excluded; ${verdict === "yes" ? "The weekend itself is informative, though less than the 09:00 figure suggests." : ""}`,
                `为什么有三行。我们最初只测了最后一行，得到的相关系数是 ${num(wk.by_anchor.to_preopen?.stats.corr_open?.est, 2)}，好得不像是在说周末：美国股票从美东 04:00 起就有盘前交易，代币会跟随，所以周一 09:00 的代币价格已经看过股票的盘前走势。看到这个结果后我们加入了两种更严格的口径，并以最严格的一种来下结论。排除盘前之后，相关系数从 ${num(wk.by_anchor.to_preopen?.stats.corr_open?.est, 2)} 降到 ${num(wk.primary.stats.corr_open?.est, 2)}。${verdict === "yes" ? "周末本身确实有信息，但没有 09:00 那个数字显示的那么多。" : ""}`,
              )}
            </p>
            <p className="leading-relaxed text-muted-foreground">
              {tx(
                `Does Monday keep or reverse it? A slope near 1 on the gap means the stock opens about where the token went; the interval on the slope to Monday's close, ${withCi(wk.primary.stats.slope_close, (v) => num(v, 2))}, is too wide to say the stock reverses any of it by evening, and too wide to say it does not. We do not read a slope below 1 as "Monday reverses part of it": the token's price is noisy when few trades happen overnight, and noise in the token's move pulls any slope toward zero.`,
                `周一是保留还是回吐？对跳空的斜率接近 1，说明股票开盘大致落在代币走到的位置；对周一收盘的斜率区间是 ${withCi(wk.primary.stats.slope_close, (v) => num(v, 2))}，太宽，既不能说傍晚前股票回吐了一部分，也不能说没有回吐。我们不把小于 1 的斜率解读为“周一回吐了一部分”：夜间成交稀少时代币价格本身有噪声，而噪声会把任何斜率拉向零。`,
              )}
            </p>
            {ch.overnight?.by_anchor?.weekend_only ? (
              <p className="text-[13px] text-muted-foreground">
                {tx(
                  `For comparison, weeknights on the same strict cut (20:00 to 04:00): slope ${withCi(ch.overnight.by_anchor.weekend_only.stats.slope_open, (v) => num(v, 2))}, correlation ${withCi(ch.overnight.by_anchor.weekend_only.stats.corr_open, (v) => num(v, 2))}, n = ${ch.overnight.by_anchor.weekend_only.n.toLocaleString()}.`,
                  `作为对照，工作日夜间用同样严格的口径（20:00 到 04:00）：斜率 ${withCi(ch.overnight.by_anchor.weekend_only.stats.slope_open, (v) => num(v, 2))}，相关系数 ${withCi(ch.overnight.by_anchor.weekend_only.stats.corr_open, (v) => num(v, 2))}，n = ${ch.overnight.by_anchor.weekend_only.n.toLocaleString()}。`,
                )}
              </p>
            ) : null}
          </div>
        ) : null}

        {/* ------------------------------------------------------------ Q3 */}
        {liq && liq.n_snapshots > 0 ? (
          <div className="space-y-3">
            <p className="text-[13px] font-medium tracking-wide text-muted-foreground uppercase">
              {tx("3. How thin is the book while the market is shut?", "3. 休市期间盘口有多薄？")}
            </p>
            <ScrollTable>
              <table className="w-full min-w-[560px] text-[13px]">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-1 pr-3 font-medium">{tx("Compared with the open session", "与开市时段相比")}</th>
                    <th className="py-1 pr-3 text-right font-medium">{tx("Spread (wider if above 1)", "买卖价差（大于 1 为更宽）")}</th>
                    <th className="py-1 pr-3 text-right font-medium">{tx("Depth inside 25 bps (thinner if below 1)", "25 bps 内深度（小于 1 为更薄）")}</th>
                    <th className="py-1 text-right font-medium">{tx("Snapshots with no bids", "买盘为空的快照")}</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {liqRows.map((r) => (
                    <tr key={r.key} className="border-b border-border/50">
                      <td className="py-1 pr-3">{r.label}</td>
                      <td className="py-1 pr-3 text-right">{withCi(liq.stats[`spread_ratio_${r.key}`], (v) => times(v, 2))}</td>
                      <td className="py-1 pr-3 text-right">{withCi(liq.stats[`depth_ratio_${r.key}`], (v) => times(v, 2))}</td>
                      <td className="py-1 text-right">{withCi(liq.stats[`empty_share_${r.key}`], (v) => pct(v, 1))}</td>
                    </tr>
                  ))}
                  <tr className="border-b border-border/50 text-muted-foreground">
                    <td className="py-1 pr-3">{tx("Open session", "开市时段")}</td>
                    <td className="py-1 pr-3 text-right">1.00×</td>
                    <td className="py-1 pr-3 text-right">1.00×</td>
                    <td className="py-1 text-right">{withCi(liq.stats.empty_share_open, (v) => pct(v, 2))}</td>
                  </tr>
                </tbody>
              </table>
            </ScrollTable>
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              {tx(
                `Each cell is the median across ${liq.tokens ?? "—"} tokens of that token's geometric-mean ratio. n = ${liq.n_snapshots.toLocaleString()} order-book snapshots from ${liq.first_day} to ${liq.last_day}, which contain only ${liq.n_weekend_windows ?? "—"} weekends. That is a description of those weeks, not an estimate of a long-run average, and the weekend and Sunday intervals are wide for that reason.`,
                `每个格子是 ${liq.tokens ?? "—"} 个代币各自几何平均比值的中位数。n = ${liq.n_snapshots.toLocaleString()} 份盘口快照，时间从 ${liq.first_day} 到 ${liq.last_day}，其中只包含 ${liq.n_weekend_windows ?? "—"} 个周末。这是对那几周的描述，不是长期平均值的估计，周末和周日的区间之所以宽就是这个原因。`,
              )}
            </p>
          </div>
        ) : null}

        {/* ------------------------------------------------------------ limits */}
        <div className="rounded-lg border border-border bg-muted/30 p-3">
          <p className="text-[13px] font-medium tracking-wide text-muted-foreground uppercase">{tx("What this cannot tell you", "这项测量说明不了什么")}</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 leading-relaxed">
            <li>
              {tx(
                `The open window starts at 09:00 ET, not 09:30, because the stored bars are hourly. The half hour before the cash open counts as open, which can only make the closed share look smaller.`,
                `开市窗口从美东 09:00 起算而不是 09:30，因为存储的是小时 K 线。开盘前那半小时被算作开市，这只会让休市占比显得更小。`,
              )}
            </li>
            <li>
              {tx(
                `Bars cover January 2025 onward, so a token has at most ${ch.movement.primary.n_weeks ?? "—"} weeks, and the strict weekend cut keeps ${wk?.primary.n_weeks ?? "—"} of them because the token often had not traded within ${ch.settings.stale_hours} hours of Friday 20:00 or Monday 04:00 (${wk?.dropped_stale ?? "—"} weekend-token pairs dropped).`,
                `K 线从 2025 年 1 月开始，所以一个代币最多只有 ${ch.movement.primary.n_weeks ?? "—"} 周；严格的周末口径只保留其中 ${wk?.primary.n_weeks ?? "—"} 周，因为代币常常在周五 20:00 或周一 04:00 前 ${ch.settings.stale_hours} 小时内没有成交（丢弃了 ${wk?.dropped_stale ?? "—"} 个周末-代币组合）。`,
              )}
            </li>
            <li>
              {tx(
                `Weekend moves and Monday gaps share the market's moves, so part of any slope is "the market moved". Each weekend's cross-token mean can be removed to ask about a token's own move; that variant is in the data file (slope_own_open).`,
                `周末涨跌和周一跳空共享整个市场的涨跌，所以任何斜率里都有一部分是“大盘动了”。可以去掉每个周末所有代币的均值，只看代币自己的涨跌；该变体在数据文件中（slope_own_open）。`,
              )}
            </li>
            <li>
              {tx(
                `Not a trading result: nothing here says a position taken on a weekend move would have made money.`,
                `这不是交易结果：这里没有任何内容表明按周末涨跌建仓会赚钱。`,
              )}
            </li>
          </ul>
        </div>
      </div>
    </Section>
  );
}
