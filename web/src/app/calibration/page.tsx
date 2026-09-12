"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type CalibrationReport } from "@/lib/api";
import { fmtPct, fmtRatio } from "@/lib/format";

const PIT_ORDER = ["<p5", "p5-p25", "p25-p50", "p50-p75", "p75-p95", ">p95"];
const PIT_EXPECTED: Record<string, number> = { "<p5": 0.05, "p5-p25": 0.2, "p25-p50": 0.25, "p50-p75": 0.25, "p75-p95": 0.2, ">p95": 0.05 };

export default function CalibrationPage() {
  const [rep, setRep] = useState<CalibrationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"all" | "replay" | "ticket">("all");

  async function load() {
    setError(null);
    setRep(null);
    try {
      setRep(await api.calibration(undefined, kind === "all" ? undefined : kind));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load calibration.");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  const bandTone = rep?.tail.band === "green" ? "good" : rep?.tail.band === "amber" ? "warning" : rep?.tail.band === "red" ? "critical" : "muted";
  const pitData = rep ? PIT_ORDER.map((k) => ({ bucket: k, observed: (rep.pit_histogram[k] ?? 0) / Math.max(1, rep.n_matured), expected: PIT_EXPECTED[k] })) : [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Does it tell the truth?</h1>
          <p className="max-w-prose text-sm text-muted-foreground">Every forecast is written down before the outcome is known, then scored once the horizon passes. If the distributions are honest, 5% of outcomes land below p5 and 90% inside the p5–p95 band.</p>
        </div>
        <div className="flex gap-1" role="group" aria-label="Forecast kind">
          {(["all", "replay", "ticket"] as const).map((k) => (
            <Button key={k} size="sm" variant={kind === k ? "default" : "secondary"} onClick={() => setKind(k)}>
              {k === "all" ? "All" : k === "replay" ? "Replays" : "Live tickets"}
            </Button>
          ))}
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="font-medium">Couldn&apos;t load calibration</p>
          <p className="text-xs text-muted-foreground">{error}</p>
          <Button variant="secondary" size="sm" className="mt-2" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      ) : !rep ? (
        <div className="space-y-4" aria-hidden>
          <Skeleton className="h-28 w-full rounded-lg" />
          <Skeleton className="h-64 w-full rounded-lg" />
        </div>
      ) : rep.n_matured === 0 ? (
        <div className="flex min-h-[240px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-8 text-center">
          <p className="text-sm font-medium">No matured forecasts yet</p>
          <p className="max-w-prose text-sm text-muted-foreground">Run a replay (`nightwatch replay --tickers TSLA`) to score the forecasts the system would have made over past closed-market windows, or wait for live tickets to mature.</p>
        </div>
      ) : (
        <>
          <Section title={`${rep.n_matured} matured forecasts`} subtitle={Object.entries(rep.by_ticker).map(([t, n]) => `${t} ${n}`).join(" · ")} action={<Pill tone={bandTone}>5% tail: {rep.tail.band}</Pill>}>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Breaches below p5" value={`${rep.tail.breaches} / ${rep.tail.n}`} hint={`expected ${(rep.tail.expected_rate * rep.tail.n).toFixed(1)}`} tone={bandTone === "muted" ? undefined : bandTone} />
              <Stat label="Failure-rate test" value={rep.tail.pof_p_value != null ? `p = ${rep.tail.pof_p_value.toFixed(3)}` : "—"} hint={rep.tail.pof_stat != null ? `LR ${rep.tail.pof_stat.toFixed(2)}` : "needs ≥ 20 forecasts"} />
              <Stat label="Independence test" value={rep.tail.independence_p_value != null ? `p = ${rep.tail.independence_p_value.toFixed(3)}` : "—"} hint="do breaches cluster?" />
              <Stat label="Sharpness" value={rep.mean_width_p5_p95 != null ? `${rep.mean_width_p5_p95.toFixed(2)}%` : "—"} hint={`mean p5–p95 width · |err p50| ${rep.mean_abs_error_p50?.toFixed(2) ?? "—"}%`} />
            </div>
          </Section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Section title="Coverage by quantile" subtitle="Observed share of outcomes below each predicted quantile, with a 95% interval.">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Quantile</TableHead>
                    <TableHead className="text-right">Nominal</TableHead>
                    <TableHead className="text-right">Observed</TableHead>
                    <TableHead className="text-right">95% interval</TableHead>
                    <TableHead className="text-right">OK</TableHead>
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
                      <TableCell className="text-right">{c.within_ci ? <Pill tone="good">yes</Pill> : <Pill tone="critical">no</Pill>}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Section>
            <Section title="Where outcomes landed" subtitle="Share of realised returns per predicted band. A calibrated forecast is flat at the expected heights.">
              <figure aria-label="Probability integral transform histogram">
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={pitData} margin={{ top: 12, right: 8, bottom: 4, left: -18 }} barCategoryGap={8}>
                    <CartesianGrid vertical={false} stroke="var(--grid)" />
                    <XAxis dataKey="bucket" tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} axisLine={{ stroke: "var(--grid)" }} tickLine={false} />
                    <YAxis tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
                    <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 }} formatter={(v, name) => [`${(Number(v) * 100).toFixed(1)}%`, name === "observed" ? "observed" : "expected"]} />
                    <Bar dataKey="expected" fill="var(--muted-foreground)" fillOpacity={0.35} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} name="expected" />
                    <Bar dataKey="observed" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} name="observed" />
                  </BarChart>
                </ResponsiveContainer>
                <figcaption className="mt-2 flex gap-4 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <span aria-hidden className="inline-block h-2 w-3 rounded-sm bg-chart-1" /> observed
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span aria-hidden className="inline-block h-2 w-3 rounded-sm bg-muted-foreground/40" /> expected if calibrated
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
