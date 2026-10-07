"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtCompact } from "@/lib/format";
import { type Lang, tr } from "@/lib/i18n";

interface Point {
  notional: number;
  total_cost_bps: number | null;
  fully_filled: boolean;
}

/** Exit cost (bps) versus size on a log x-axis, with the trader's size and the budget marked. */
export function CostCurve({ points, requested, budgetBps, height = 180, lang = "en" }: { points: Point[]; requested: number; budgetBps: number; height?: number; lang?: Lang }) {
  const L = tr(lang);
  const data = points.filter((p) => p.total_cost_bps != null && p.fully_filled).map((p) => ({ notional: p.notional, bps: p.total_cost_bps as number }));
  if (data.length < 2) {
    return <p className="text-sm text-muted-foreground">{L("The book cannot absorb enough sizes to draw a curve.", "盘口深度不足以承接足够多的仓位档位，无法绘制曲线。")}</p>;
  }
  return (
    <figure aria-label={L("Exit cost by position size", "不同仓位大小的平仓成本")} className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: -18 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis dataKey="notional" scale="log" domain={["dataMin", "dataMax"]} type="number" tickFormatter={(v: number) => fmtCompact(v)} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} axisLine={{ stroke: "var(--grid)" }} tickLine={false} minTickGap={14} />
          <YAxis tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v} bps`} width={60} />
          <Tooltip
            contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 }}
            formatter={(value) => [`${Number(value).toFixed(1)} bps`, L("total exit cost", "平仓总成本")]}
            labelFormatter={(v) => `${L("size", "仓位")} ${fmtCompact(Number(v))}`}
          />
          <ReferenceLine y={budgetBps} stroke="var(--status-warning)" strokeWidth={1} label={{ value: L(`${budgetBps} bps budget`, `${budgetBps} bps 预算`), position: "insideTopRight", fill: "var(--muted-foreground)", fontSize: 12 }} />
          <ReferenceLine x={requested} stroke="var(--foreground)" strokeWidth={1} label={{ value: L("your size", "你的仓位"), position: "top", fill: "var(--muted-foreground)", fontSize: 12 }} ifOverflow="extendDomain" />
          <Line type="monotone" dataKey="bps" stroke="var(--chart-1)" strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--card)", fill: "var(--chart-1)" }} activeDot={{ r: 6 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  );
}
