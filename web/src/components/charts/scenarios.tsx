"use client";

import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import type { ScenarioPaths } from "@/lib/api";
import { type Lang, tr } from "@/lib/i18n";

/** The retrieved scenarios, drawn.
 *
 *  The cohort already says what followed moments like this one, as percentiles. This
 *  says it as shapes, which is the thing a person actually pictures — and the shape is
 *  not decoration here. Two cohorts with the same 5th percentile can be a slow bleed
 *  and a violent round trip, and only one of those takes out a stop on the way to an
 *  unremarkable close.
 *
 *  Paths are coloured by how close the match was, because the desk measured that the
 *  near ones are the *wider* ones and a reader should be able to see it rather than
 *  take our word for it. See the Studies page.
 */

interface Props {
  paths: ScenarioPaths;
  horizonLabel: string;
  height?: number;
  lang?: Lang;
}

/** Near matches one colour, far matches another, so the spread between them is visible.
 *
 *  Coloured by `rank` — position among the forty drawn — and deliberately not by
 *  `distance_percentile`, which ranks against every candidate hour searched. All forty
 *  retrieved analogs sit in the bottom fraction of that scale by construction, so
 *  colouring by it paints every line the same and says nothing.
 */
function pathColor(rank: number, highlighted: boolean): string {
  if (highlighted) return "var(--foreground)";
  return rank < 0.5 ? "var(--chart-1)" : "var(--chart-4)";
}

function hourLabel(h: number, lang: Lang = "en"): string {
  if (h === 0) return lang === "zh" ? "入场" : "entry";
  if (lang === "zh") return h < 24 ? `${Math.round(h)}小时` : `${(h / 24).toFixed(h % 24 === 0 ? 0 : 1)}天`;
  return h < 24 ? `${Math.round(h)}h` : `${(h / 24).toFixed(h % 24 === 0 ? 0 : 1)}d`;
}

export function Scenarios({ paths, horizonLabel, height = 300, lang = "en" }: Props) {
  const L = tr(lang);
  const [hover, setHover] = useState<number | null>(null);
  if (!paths.paths.length) return null;

  // Recharts wants one row per x value, so the paths are transposed once here rather
  // than forty times inside the render.
  const rows = paths.hours.map((h, i) => {
    const row: Record<string, number> = { h };
    paths.paths.forEach((p, j) => {
      row[`s${j}`] = p.values[i];
    });
    row.p5 = paths.fan.p5[i];
    row.p95 = paths.fan.p95[i];
    row.p25 = paths.fan.p25[i];
    row.p75 = paths.fan.p75[i];
    row.p50 = paths.fan.p50[i];
    // Areas stack from a base, so the outer band is drawn as base + thickness.
    row.band90 = paths.fan.p95[i] - paths.fan.p5[i];
    row.band50 = paths.fan.p75[i] - paths.fan.p25[i];
    row.base50 = paths.fan.p25[i];
    return row;
  });

  const active = hover != null ? paths.paths[hover] : null;
  const near = paths.paths.filter((p) => p.rank < 0.5).length;

  return (
    <figure className="w-full" aria-label={L(`${paths.paths.length} retrieved past scenarios over ${horizonLabel}, each drawn from its own entry`, `检索到的 ${paths.paths.length} 个历史情景（${horizonLabel}），各自从其入场点开始绘制`)}>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 12, right: 12, bottom: 4, left: -18 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis
            dataKey="h"
            type="number"
            domain={[0, paths.hours[paths.hours.length - 1]]}
            tickFormatter={(v: number) => hourLabel(v, lang)}
            tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
            axisLine={{ stroke: "var(--grid)" }}
            tickLine={false}
          />
          <YAxis tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} axisLine={false} tickLine={false} width={50} />

          {/* The forecast itself, under the paths it is made of. */}
          <Area dataKey="p5" stackId="fan" stroke="none" fill="none" isAnimationActive={false} />
          <Area dataKey="band90" stackId="fan" stroke="none" fill="var(--chart-1)" fillOpacity={0.18} isAnimationActive={false} />
          <Area dataKey="base50" stackId="inner" stroke="none" fill="none" isAnimationActive={false} />
          <Area dataKey="band50" stackId="inner" stroke="none" fill="var(--chart-1)" fillOpacity={0.28} isAnimationActive={false} />

          {paths.paths.map((p, j) => (
            <Line
              key={`${p.ticker}-${p.ts}`}
              dataKey={`s${j}`}
              stroke={pathColor(p.rank, hover === j)}
              strokeWidth={hover === j ? 2 : 1}
              strokeOpacity={hover == null ? 0.42 : hover === j ? 1 : 0.12}
              dot={false}
              isAnimationActive={false}
              onMouseEnter={() => setHover(j)}
              onMouseLeave={() => setHover(null)}
              style={{ cursor: "pointer" }}
            />
          ))}

          <Line dataKey="p50" stroke="var(--foreground)" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} strokeOpacity={hover == null ? 0.8 : 0.25} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeWidth={1} />
          {paths.stop_pct != null ? (
            <ReferenceLine
              y={paths.stop_pct}
              stroke="var(--status-critical)"
              strokeWidth={1.5}
              strokeDasharray="5 4"
              label={{ value: L("your stop", "你的止损"), position: "insideBottomLeft", fill: "var(--status-critical)", fontSize: 12 }}
            />
          ) : null}
        </ComposedChart>
      </ResponsiveContainer>

      <figcaption className="mt-2 space-y-1 text-[13px] leading-relaxed text-muted-foreground">
        <p>
          <span className="inline-block h-[2px] w-4 align-middle" style={{ background: "var(--chart-1)" }} />{" "}
          {L(`the ${near} closest matches`, `最相似的 ${near} 个`)} ·{" "}
          <span className="inline-block h-[2px] w-4 align-middle" style={{ background: "var(--chart-4)" }} />{" "}
          {L(`the ${paths.paths.length - near} furthest`, `最不相似的 ${paths.paths.length - near} 个`)}
          {L(" · shaded, the 5th–95th and 25th–75th of all of them · dashed, the median", " · 阴影为全部路径的 5%–95% 与 25%–75% 区间 · 虚线为中位数")}
        </p>
        {active ? (
          <p className="text-foreground">
            {active.ticker} · {new Date(active.ts).toISOString().slice(0, 16).replace("T", " ")} UTC · {L("ended", "最终")} {active.values[active.values.length - 1] > 0 ? "+" : ""}
            {active.values[active.values.length - 1].toFixed(2)}%
            {active.stopped_at_h != null
              ? ` · ${L(`would have stopped you out after ${hourLabel(active.stopped_at_h, lang)}`, `${hourLabel(active.stopped_at_h, lang)}后会触发你的止损`)}`
              : paths.stop_pct != null
                ? ` · ${L("never reached your stop", "从未触及你的止损")}`
                : ""}
          </p>
        ) : (
          <p>
            {L("Hover a line to see which moment it was.", "把鼠标移到某条线上，可看到它对应的是哪个时刻。")}
            {paths.n_dropped ? L(` ${paths.n_dropped} more had too little history after them to draw.`, ` 另有 ${paths.n_dropped} 个因之后的历史数据太少而未绘制。`) : ""}
          </p>
        )}
      </figcaption>
    </figure>
  );
}
