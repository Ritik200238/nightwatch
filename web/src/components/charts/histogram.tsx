"use client";

import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtPct } from "@/lib/format";

interface HistogramProps {
  /** Raw observations, binned here. Use `bins` instead when the server already binned. */
  values?: number[];
  /** Counts per bin with their edges: `edges.length === counts.length + 1`. */
  bins?: { edges: number[]; counts: number[] };
  /** Vertical guide lines with labels, e.g. p5 / median / p95. */
  markers?: { value: number; label: string }[];
  binCount?: number;
  height?: number;
  ariaLabel: string;
  unit?: string;
}

function bin(values: number[], count: number) {
  if (!values.length) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = span / count;
  const bins = Array.from({ length: count }, (_, i) => ({ x0: min + i * width, x1: min + (i + 1) * width, n: 0 }));
  for (const v of values) {
    const i = Math.min(count - 1, Math.max(0, Math.floor((v - min) / width)));
    bins[i].n += 1;
  }
  return bins.map((b) => ({ mid: (b.x0 + b.x1) / 2, label: `${fmtPct(b.x0, 1)} to ${fmtPct(b.x1, 1)}`, n: b.n, share: b.n / values.length }));
}

/**
 * Distribution of outcomes. Single series (no legend), thin bars with a surface gap,
 * hover tooltip per bin, reference lines for the quantiles the verdict uses.
 */
function fromBins(b: { edges: number[]; counts: number[] }) {
  const total = b.counts.reduce((a, c) => a + c, 0) || 1;
  return b.counts.map((n, i) => ({
    mid: (b.edges[i] + b.edges[i + 1]) / 2,
    label: `${fmtPct(b.edges[i], 1)} to ${fmtPct(b.edges[i + 1], 1)}`,
    n,
    share: n / total,
  }));
}

export function Histogram({ values, bins, markers = [], binCount = 24, height = 200, ariaLabel, unit = "%" }: HistogramProps) {
  // Prefer bins the server sent: five thousand raw path values are 180 KB of response
  // for a forty-bar chart. Raw values still work, for reports stored before that change.
  const data = bins && bins.counts.length ? fromBins(bins) : bin(values ?? [], binCount);
  if (!data.length) {
    return <p className="text-sm text-muted-foreground">No outcomes to plot.</p>;
  }
  return (
    <figure aria-label={ariaLabel} className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 16, right: 12, bottom: 4, left: -18 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis
            dataKey="mid"
            tickFormatter={(v: number) => `${v.toFixed(1)}${unit}`}
            tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
            axisLine={{ stroke: "var(--grid)" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
          <Tooltip
            cursor={{ fill: "var(--accent)", opacity: 0.4 }}
            contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 }}
            formatter={(value, _name, item) => [`${value} episodes (${((item.payload as { share: number }).share * 100).toFixed(0)}%)`, (item.payload as { label: string }).label]}
            labelFormatter={() => ""}
          />
          <Bar dataKey="n" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
          {markers.map((m) => (
            <ReferenceLine
              key={m.label}
              x={m.value}
              stroke="var(--foreground)"
              strokeWidth={1}
              strokeDasharray="0"
              label={{ value: m.label, position: "top", fill: "var(--muted-foreground)", fontSize: 11 }}
              ifOverflow="extendDomain"
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </figure>
  );
}
