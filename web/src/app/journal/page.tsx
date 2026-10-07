"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Button } from "@/components/ui/button";
import { LoadingRecord, PageHead, PlainBox, PROOF_WIDTH, ScrollTable } from "@/components/proof-page";
import { Term } from "@/components/term";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useLang } from "@/lib/lang";
import { t as tl } from "@/lib/i18n";
import { fmtPct, fmtUsd } from "@/lib/format";
import { fmtTimeL } from "@/lib/i18n";

/** One journal row as the API returns it. Everything optional is null until maturity. */
interface ForecastRow {
  id: number;
  kind: string;
  ticker: string;
  side: string;
  notional: number;
  as_of: string;
  horizon_h: number;
  horizon_end: string;
  entry_price: number;
  analog_n: number | null;
  p5: number | null;
  p50: number | null;
  p95: number | null;
  verdict: string | null;
  recommended_notional: number | null;
  ret_pct: number | null;
  mae_pct: number | null;
  exit_price: number | null;
  snapshot_hash: string;
}

const KINDS = ["all", "ticket", "replay"] as const;
/** A hold longer than this is shown as days; "9999h" tells nobody anything. */
const LONG_HORIZON_H = 720;
const LIMIT = 60; // a readable page; the whole journal is available from the API and the CLI

interface JournalGroup {
  row: ForecastRow;
  count: number;
}

/** Collapse consecutive rows that are the same call made again within the same hour:
 *  same ticker, side, size, kind and verdict. Rows arrive newest first, so a run is
 *  adjacent. The newest row of the run is the one shown. */
function groupRows(rows: ForecastRow[]): JournalGroup[] {
  const out: JournalGroup[] = [];
  for (const r of rows) {
    const prev = out[out.length - 1];
    const same =
      prev !== undefined &&
      prev.row.ticker === r.ticker &&
      prev.row.side === r.side &&
      prev.row.notional === r.notional &&
      prev.row.kind === r.kind &&
      (prev.row.verdict ?? "") === (r.verdict ?? "") &&
      prev.row.as_of.slice(0, 13) === r.as_of.slice(0, 13);
    if (same && prev) prev.count += 1;
    else out.push({ row: r, count: 1 });
  }
  return out;
}

function fmtHorizon(h: number, zh: boolean): string {
  if (h > LONG_HORIZON_H) return zh ? "> 30 天" : "> 30 d";
  return `${h.toFixed(0)}h`;
}

export default function JournalPage() {
  const { tx, lang } = useLang();
  const sideW = (s: string) => (lang === "zh" ? (s === "long" ? "做多" : s === "short" ? "做空" : s) : s);
  const verdictPill = (r: ForecastRow) =>
    r.verdict ? <Pill verdict={r.verdict}>{lang === "zh" ? tl(lang, "verdictName", r.verdict) : r.verdict.replace("_", " ")}</Pill> : <span className="text-[13px] text-muted-foreground">—</span>;
  const [rows, setRows] = useState<ForecastRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<(typeof KINDS)[number]>("all");
  const [details, setDetails] = useState(false);

  async function load() {
    setError(null);
    setRows(null);
    try {
      const r = (await api.forecasts(LIMIT, undefined, kind === "all" ? undefined : kind)) as unknown as ForecastRow[];
      setRows([...r].reverse()); // newest first
    } catch (e) {
      setError(e instanceof Error ? e.message : tx("Could not load the journal.", "无法加载日志。"));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  const grouped = useMemo(() => groupRows(rows ?? []), [rows]);
  const matured = useMemo(() => (rows ?? []).filter((r) => r.ret_pct != null), [rows]);
  const inside = useMemo(() => matured.filter((r) => r.p5 != null && r.p95 != null && r.ret_pct! >= r.p5! && r.ret_pct! <= r.p95!).length, [matured]);
  const points = useMemo(() => matured.filter((r) => r.p50 != null).map((r) => ({ x: r.p50 as number, y: r.ret_pct as number, ticker: r.ticker })), [matured]);
  // Scale to the bulk of the cloud, not to one outlier, so the shape stays readable.
  const span = useMemo(() => {
    const vals = points.flatMap((p) => [Math.abs(p.x), Math.abs(p.y)]).sort((a, b) => a - b);
    if (!vals.length) return 5;
    return Math.max(1, Math.ceil(vals[Math.floor(vals.length * 0.95)] * 1.1));
  }, [points]);

  const outside = useMemo(() => points.filter((p) => Math.abs(p.x) > span || Math.abs(p.y) > span).length, [points, span]);

  return (
    <div className={`${PROOF_WIDTH} space-y-4`}>
      <PageHead
        tabs
        title={tx("Everything it has predicted", "它做过的所有预测")}
        intro={tx("Each row was written down before the outcome existed, with the hash of the exact inputs. Replays are point-in-time forecasts over past closed-market windows; tickets are live analyses. Nothing is edited afterwards; maturing only adds the result.", "每一行都是在结果出现之前写下的，并附上精确输入的哈希。重演是针对过去休市窗口、按当时时点做出的预测；表单交易是实时分析。事后不会修改任何内容；到期只是补上结果。")}
        actions={
          <div className="flex gap-1" role="group" aria-label={tx("Forecast kind", "预测类型")}>
            {KINDS.map((k) => (
              <Button key={k} size="sm" variant={kind === k ? "default" : "secondary"} onClick={() => setKind(k)}>
                {k === "all" ? tx("All", "全部") : k === "replay" ? tx("Replays", "重演") : tx("Live tickets", "实时交易")}
              </Button>
            ))}
          </div>
        }
      />
      <p className="text-[13px] text-muted-foreground">
        <span className="font-medium text-verdict-review">{tx("REVIEW", "需要复核")}</span>{" "}
        {tx("means something is missing or unclear, such as a stop, a plan or your account size, so there is no firm verdict yet.", "表示缺少或不清楚某些信息，例如止损、计划或账户规模，所以暂时还没有确定的结论。")}
      </p>
      {rows && rows.length > 0 ? (
        <PlainBox>
          {tx(`Of the ${rows.length} most recent forecasts, ${matured.length} have been scored against what happened. `, `最近的 ${rows.length} 个预测中，已有 ${matured.length} 个对照实际结果评了分。`)}
          {matured.length
            ? tx(`${fmtPct((inside / matured.length) * 100, 1, false)} of them landed inside the `, `其中 ${fmtPct((inside / matured.length) * 100, 1, false)} 落在 `)
            : tx("None has landed yet, so there is nothing to check against the ", "目前还没有结果落地，所以还无法检验落在 ")}
          <Term k="p5">p5</Term>
          {tx("–", "–")}
          <Term k="p95">p95</Term>
          {tx(" band the desk stated; if its ranges are honest that share should be near 90%. Rows are never edited afterwards.", " 区间内的比例；如果它给出的区间是诚实的，这个比例应当接近 90%。事后不会修改任何一行。")}
        </PlainBox>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="font-medium">{tx("Couldn't load the journal", "无法加载日志")}</p>
          <p className="text-[13px] text-muted-foreground">{error}</p>
          <Button variant="secondary" size="sm" className="mt-2" onClick={() => void load()}>
            {tx("Try again", "重试")}
          </Button>
        </div>
      ) : !rows ? (
        <LoadingRecord blocks={[96, 384]} />
      ) : rows.length === 0 ? (
        <div className="flex min-h-[240px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-8 text-center">
          <p className="text-sm font-medium">{tx("Nothing journaled yet", "日志里还没有内容")}</p>
          <p className="max-w-prose text-sm text-muted-foreground">{tx("Analyse a ticket on the desk, or run a replay to score the forecasts the system would have made over past closed-market windows.", "在交易台分析一笔交易，或运行重演，为系统在过去休市窗口本会做出的预测评分。")}</p>
        </div>
      ) : (
        <>
          <Section title={tx(`${rows.length} most recent`, `最近 ${rows.length} 条`)} subtitle={tx(`${matured.length} scored · ${rows.length - matured.length} still open${rows.length === LIMIT ? " · older rows are in the API and the CLI" : ""}`, `${matured.length} 条已评分 · ${rows.length - matured.length} 条尚未到期${rows.length === LIMIT ? " · 更早的记录在 API 和命令行里" : ""}`)}>
            <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
              <div className="grid grid-cols-2 gap-2">
                <Stat label={tx("Scored", "已评分")} value={String(matured.length)} hint={tx("horizon passed, outcome recorded", "持有期已过，结果已记录")} />
                <Stat label={tx("Inside the p5–p95 band", "落在 p5–p95 区间内")} value={matured.length ? fmtPct((inside / matured.length) * 100, 1, false) : "—"} hint={tx("90% if the distributions are honest", "分布若诚实应为 90%")} />
                <Stat label={tx("Tokens", "代币")} value={String(new Set(rows.map((r) => r.ticker)).size)} />
                <Stat label={tx("Live tickets", "实时交易")} value={String(rows.filter((r) => r.kind === "ticket").length)} hint={tx("analyses a person asked for", "有人主动请求的分析")} />
              </div>
              {points.length === 0 ? (
                <p className="self-center rounded-lg border border-dashed border-border px-4 py-3 text-[13px] text-muted-foreground">
                  {tx("No forecast has been scored yet, so there is nothing to plot. The chart appears once the first outcome is recorded.", "还没有预测被评分，所以暂时没有可画的内容。第一个结果记录后，图表就会出现。")}
                </p>
              ) : (
              <figure aria-label={tx("Predicted median against realised return", "预测中位数与实际收益对比")}>
                <ResponsiveContainer width="100%" height={240}>
                  <ScatterChart margin={{ top: 8, right: 12, bottom: 16, left: -12 }}>
                    <CartesianGrid stroke="var(--grid)" />
                    <XAxis type="number" dataKey="x" domain={[-span, span]} allowDataOverflow tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} tickFormatter={(v: number) => `${v}%`} axisLine={{ stroke: "var(--grid)" }} tickLine={false}>
                    </XAxis>
                    <YAxis type="number" dataKey="y" domain={[-span, span]} allowDataOverflow tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} tickFormatter={(v: number) => `${v}%`} axisLine={false} tickLine={false} />
                    <ZAxis range={[24, 24]} />
                    <ReferenceLine x={0} stroke="var(--grid)" />
                    <ReferenceLine y={0} stroke="var(--grid)" />
                    <Tooltip
                      cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
                      contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 }}
                      formatter={(v, name) => [`${Number(v).toFixed(2)}%`, String(name) === "x" ? tx("predicted median", "预测中位数") : tx("realised", "实际")]}
                    />
                    <Scatter data={points} fill="var(--chart-1)" fillOpacity={0.55} isAnimationActive={false} />
                  </ScatterChart>
                </ResponsiveContainer>
                <figcaption className="mt-1 text-[13px] text-muted-foreground">
                  {tx("Predicted median (horizontal) against what happened (vertical). A useful forecast tilts along the diagonal; a useless one is a cloud.", "预测中位数（横轴）与实际发生的结果（纵轴）。有用的预测会沿对角线倾斜；没用的则是一团散点。")}
                  {outside > 0 ? tx(` ${outside} point${outside === 1 ? "" : "s"} fall outside this view.`, ` 有 ${outside} 个点在此视图之外。`) : ""}
                </figcaption>
              </figure>
              )}
            </div>
          </Section>

          <Section
            title={tx("The journal", "日志")}
            subtitle={tx(`Newest first. The band is the analog distribution at the moment of the call.${grouped.length < rows.length ? ` ${rows.length - grouped.length} repeat calls inside the same hour are folded into a ×N row.` : ""}`, `最新的在前。区间是给出结论时相似时刻样本的分布。${grouped.length < rows.length ? `同一小时内重复的 ${rows.length - grouped.length} 次相同调用，已折叠成“×N”的一行。` : ""}`)}
            action={
              <Button size="sm" variant="secondary" aria-pressed={details} onClick={() => setDetails((d) => !d)}>
                {details ? tx("Hide details", "隐藏详情") : tx("Details", "详情")}
              </Button>
            }
          >
            <div className="hidden md:block">
            <ScrollTable>
              <Table className="min-w-[820px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>{tx("When", "时间")}</TableHead>
                    <TableHead>{tx("Trade", "交易")}</TableHead>
                    <TableHead>{tx("Verdict", "结论")}</TableHead>
                    <TableHead className="text-right">{tx("Horizon", "持有期")}</TableHead>
                    <TableHead className="text-right">p5 – p50 – p95</TableHead>
                    <TableHead className="text-right">{tx("Realised", "实际")}</TableHead>
                    {details ? <TableHead className="text-right">{tx("Inputs (hash)", "输入（哈希）")}</TableHead> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {grouped.map(({ row: r, count }) => {
                    const band = r.p5 != null && r.p95 != null;
                    const insideBand = band && r.ret_pct != null && r.ret_pct >= r.p5! && r.ret_pct <= r.p95!;
                    return (
                      <TableRow key={r.id}>
                        <TableCell className="whitespace-nowrap">
                          {/* Live tickets keep their full report for a while, so the row
                              opens the argument. Replays keep only the numbers here. */}
                          {r.kind === "replay" ? (
                            fmtTimeL(r.as_of, lang)
                          ) : (
                            <Link href={`/r/${r.id}`} className="rounded underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                              {fmtTimeL(r.as_of, lang)}
                            </Link>
                          )}
                          <span className="block text-[13px] text-muted-foreground">{r.kind === "replay" ? tx("replay", "重演") : tx("live ticket", "实时交易")}</span>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          <span className="font-medium">{r.ticker}</span> {sideW(r.side)}
                          {count > 1 ? <span className="tabular ml-1 rounded border border-border px-1 text-[13px] text-muted-foreground" title={tx(`${count} identical calls in this hour`, `这一小时内有 ${count} 次相同调用`)}>×{count}</span> : null}
                          <span className="block text-[13px] text-muted-foreground">
                            {fmtUsd(r.notional)} · {r.analog_n ?? 0} {tx("analogs", "个相似时刻")}
                          </span>
                        </TableCell>
                        <TableCell>{verdictPill(r)}</TableCell>
                        <TableCell className="tabular text-right whitespace-nowrap">{fmtHorizon(r.horizon_h, lang === "zh")}</TableCell>
                        <TableCell className="tabular text-right whitespace-nowrap">
                          {band ? (
                            <>
                              {fmtPct(r.p5)} · {fmtPct(r.p50)} · {fmtPct(r.p95)}
                            </>
                          ) : (
                            <span className="text-muted-foreground">{tx("refused: too few analogs", "拒绝：相似时刻太少")}</span>
                          )}
                        </TableCell>
                        <TableCell className="tabular text-right">
                          {r.ret_pct == null ? (
                            <span className="text-muted-foreground">{tx("open", "未到期")}</span>
                          ) : (
                            <span className={insideBand ? "" : "text-status-warning"}>{fmtPct(r.ret_pct)}</span>
                          )}
                        </TableCell>
                        {details ? <TableCell className="text-right font-mono text-[13px] text-muted-foreground">{r.snapshot_hash}</TableCell> : null}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </ScrollTable>
            </div>
            <ul className="divide-y divide-border rounded-lg border border-border md:hidden" aria-label={tx("The journal", "日志")}>
              {grouped.map(({ row: r, count }) => {
                const band = r.p5 != null && r.p95 != null;
                const insideBand = band && r.ret_pct != null && r.ret_pct >= r.p5! && r.ret_pct <= r.p95!;
                return (
                  <li key={r.id} className="space-y-1.5 px-3 py-3">
                    <div className="flex items-center justify-between gap-2">
                      {verdictPill(r)}
                      <span className="text-[13px] text-muted-foreground">{r.kind === "replay" ? tx("replay", "重演") : tx("live ticket", "实时交易")}</span>
                    </div>
                    <p className="text-sm">
                      <span className="font-semibold">{r.ticker}</span> {sideW(r.side)} · {fmtUsd(r.notional)}
                      {count > 1 ? <span className="tabular ml-1.5 rounded border border-border px-1 text-[13px] text-muted-foreground" title={tx(`${count} identical calls in this hour`, `这一小时内有 ${count} 次相同调用`)}>×{count}</span> : null}
                    </p>
                    <p className="text-[13px] text-muted-foreground">
                      {r.kind === "replay" ? (
                        fmtTimeL(r.as_of, lang)
                      ) : (
                        <Link href={`/r/${r.id}`} className="rounded underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                          {fmtTimeL(r.as_of, lang)}
                        </Link>
                      )}
                      {" · "}
                      {r.analog_n ?? 0} {tx("analogs", "个相似时刻")} · {fmtHorizon(r.horizon_h, lang === "zh")}
                    </p>
                    <dl className="tabular grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[13px]">
                      <dt className="text-muted-foreground">p5 – p50 – p95</dt>
                      <dd className="text-right">
                        {band ? `${fmtPct(r.p5)} · ${fmtPct(r.p50)} · ${fmtPct(r.p95)}` : <span className="text-muted-foreground">{tx("refused: too few analogs", "拒绝：相似时刻太少")}</span>}
                      </dd>
                      <dt className="text-muted-foreground">{tx("Realised", "实际")}</dt>
                      <dd className="text-right">
                        {r.ret_pct == null ? <span className="text-muted-foreground">{tx("open", "未到期")}</span> : <span className={insideBand ? "" : "text-status-warning"}>{fmtPct(r.ret_pct)}</span>}
                      </dd>
                      {details ? (
                        <>
                          <dt className="text-muted-foreground">{tx("Inputs (hash)", "输入（哈希）")}</dt>
                          <dd className="min-w-0 break-all text-right font-mono text-muted-foreground">{r.snapshot_hash}</dd>
                        </>
                      ) : null}
                    </dl>
                  </li>
                );
              })}
            </ul>
          </Section>
        </>
      )}
    </div>
  );
}
