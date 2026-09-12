"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtCompact } from "@/lib/format";

interface Point {
  notional: number;
  total_cost_bps: number | null;
  fully_filled: boolean;
}

/** Exit cost (bps) versus size on a log x-axis, with the trader's size and the budget marked. */
export function CostCurve({ points, requested, budgetBps, height = 180 }: { points: Point[]; requested: number; budgetBps: number; height?: number }) {
  const data = points.filter((p) => p.total_cost_bps != null && p.fully_filled).map((p) => ({ notional: p.notional, bps: p.total_cost_bps as number }));
  if (data.length < 2) {
    return <p className="text-sm text-muted-foreground">The book cannot absorb enough sizes to draw a curve.</p>;
  }
  return (
    <figure aria-label="Exit cost by position size" className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: -18 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis dataKey="notional" scale="log" domain={["dataMin", "dataMax"]} type="number" tickFormatter={(v: number) => fmtCompact(v)} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} axisLine={{ stroke: "var(--grid)" }} tickLine={false} />
          <YAxis tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v} bps`} width={60} />
          <Tooltip
            contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 }}
            formatter={(value) => [`${Number(value).toFixed(1)} bps`, "total exit cost"]}
            labelFormatter={(v) => `size ${fmtCompact(Number(v))}`}
          />
          <ReferenceLine y={budgetBps} stroke="var(--status-warning)" strokeWidth={1} label={{ value: `${budgetBps} bps budget`, position: "insideTopRight", fill: "var(--muted-foreground)", fontSize: 11 }} />
          <ReferenceLine x={requested} stroke="var(--foreground)" strokeWidth={1} label={{ value: "your size", position: "top", fill: "var(--muted-foreground)", fontSize: 11 }} ifOverflow="extendDomain" />
          <Line type="monotone" dataKey="bps" stroke="var(--chart-1)" strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--card)", fill: "var(--chart-1)" }} activeDot={{ r: 6 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  );
}
