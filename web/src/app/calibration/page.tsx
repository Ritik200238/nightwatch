"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type CalibrationReport } from "@/lib/api";
import { fmtPct, fmtRatio } from "@/lib/format";

/** Horizon bands, said the way a person holding the position would say it. */
const BAND_LABEL: Record<string, string> = {
  overnight: "Overnight (under 40h)",
  multi_day: "Weekend or longer (40h+)",
  pooled: "Before there was enough of either",
};

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
          {rep.adjusted ? (
            <Section
              title="What the desk sizes on, scored out of sample"
              subtitle="Every verdict is sized on the adjusted tail. These are those tails, each scored against what then happened, with the adjustment fitted only on forecasts that had matured before it."
              action={<Pill tone={rep.adjusted.adj_tail_band === "green" ? "good" : rep.adjusted.adj_tail_band === "amber" ? "warning" : "critical"}>5% tail: {rep.adjusted.adj_tail_band}</Pill>}
            >
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat
                  label="Outcomes below the 5th percentile"
                  value={fmtPct(rep.adjusted.adj_lo_coverage * 100, 1, false)}
                  hint={`target 5% · ${rep.adjusted.n_evaluated.toLocaleString()} forecasts · raw search ${fmtPct(rep.adjusted.raw_lo_coverage * 100, 1, false)}`}
                />
                <Stat label="Inside the 5th-95th band" value={fmtPct(rep.adjusted.adj_band_coverage * 100, 1, false)} hint={`target 90% · raw ${fmtPct(rep.adjusted.raw_band_coverage * 100, 1, false)}`} />
                {rep.adjusted.bands
                  .filter((b) => b.band !== "pooled")
                  .map((b) => (
                    <Stat
                      key={b.band}
                      label={BAND_LABEL[b.band] ?? b.band}
                      value={fmtPct(b.adj_lo_coverage * 100, 1, false)}
                      hint={`below the 5th percentile · ${b.n.toLocaleString()} forecasts · ${b.adj_tail_band}`}
                    />
                  ))}
              </div>
            </Section>
          ) : null}

          {rep.adjusted ? (
            <Section
              title="Tail adjustment, scored out of sample"
              subtitle={`Each forecast re-scored with tail factors fitted only on forecasts that had matured before it (${rep.adjusted.n_evaluated} evaluated; latest k_lo ${rep.adjusted.k_lo_last?.toFixed(2)}, k_hi ${rep.adjusted.k_hi_last?.toFixed(2)}). The verdict uses the adjusted tails.`}
            >
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Metric</TableHead>
                    <TableHead className="text-right">Target</TableHead>
                    <TableHead className="text-right">Raw</TableHead>
                    <TableHead className="text-right">Adjusted</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell>Outcomes below p5</TableCell>
                    <TableCell className="tabular text-right">5%</TableCell>
                    <TableCell className="tabular text-right">{fmtPct(rep.adjusted.raw_lo_coverage * 100, 1, false)}</TableCell>
                    <TableCell className="tabular text-right font-medium">{fmtPct(rep.adjusted.adj_lo_coverage * 100, 1, false)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Outcomes above p95</TableCell>
                    <TableCell className="tabular text-right">5%</TableCell>
                    <TableCell className="tabular text-right">{fmtPct(rep.adjusted.raw_hi_coverage * 100, 1, false)}</TableCell>
                    <TableCell className="tabular text-right font-medium">{fmtPct(rep.adjusted.adj_hi_coverage * 100, 1, false)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Inside the p5–p95 band</TableCell>
                    <TableCell className="tabular text-right">90%</TableCell>
                    <TableCell className="tabular text-right">{fmtPct(rep.adjusted.raw_band_coverage * 100, 1, false)}</TableCell>
                    <TableCell className="tabular text-right font-medium">{fmtPct(rep.adjusted.adj_band_coverage * 100, 1, false)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>5% tail band</TableCell>
                    <TableCell className="tabular text-right">green</TableCell>
                    <TableCell className="text-right">
                      <Pill tone={rep.adjusted.raw_tail_band === "green" ? "good" : rep.adjusted.raw_tail_band === "amber" ? "warning" : "critical"}>{rep.adjusted.raw_tail_band}</Pill>
                    </TableCell>
                    <TableCell className="text-right">
                      <Pill tone={rep.adjusted.adj_tail_band === "green" ? "good" : rep.adjusted.adj_tail_band === "amber" ? "warning" : "critical"}>{rep.adjusted.adj_tail_band}</Pill>
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Mean p5–p95 width (sharpness)</TableCell>
                    <TableCell className="tabular text-right">—</TableCell>
                    <TableCell className="tabular text-right">{rep.adjusted.raw_width.toFixed(2)}%</TableCell>
                    <TableCell className="tabular text-right font-medium">{rep.adjusted.adj_width.toFixed(2)}%</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </Section>
          ) : null}

          {rep.adjusted?.bands?.length ? (
            <Section
              title="The same, split by how long the position is held"
              subtitle="A single factor fitted across every horizon is the average of two different corrections, and the average is nobody's number. An overnight hold and a weekend hold need opposite adjustments, so each gets its own — and the overall reading above is only trustworthy if these are too."
            >
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Window</TableHead>
                    <TableHead className="text-right">Scored</TableHead>
                    <TableHead className="text-right">Below p5 (target 5%)</TableHead>
                    <TableHead className="text-right">Above p95 (target 5%)</TableHead>
                    <TableHead className="text-right">Width, raw → adjusted</TableHead>
                    <TableHead className="text-right">k_lo</TableHead>
                    <TableHead className="text-right">5% tail</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rep.adjusted.bands.map((b) => (
                    <TableRow key={b.band}>
                      <TableCell className="font-medium">{BAND_LABEL[b.band] ?? b.band}</TableCell>
                      <TableCell className="tabular text-right">{b.n}</TableCell>
                      <TableCell className="tabular text-right font-medium">{fmtPct(b.adj_lo_coverage * 100, 1, false)}</TableCell>
                      <TableCell className="tabular text-right font-medium">{fmtPct(b.adj_hi_coverage * 100, 1, false)}</TableCell>
                      <TableCell className="tabular text-right">
                        {b.raw_width.toFixed(2)}% → <span className="font-medium">{b.adj_width.toFixed(2)}%</span>
                      </TableCell>
                      <TableCell className="tabular text-right">{b.k_lo.toFixed(2)}</TableCell>
                      <TableCell className="text-right">
                        <Pill tone={b.adj_tail_band === "green" ? "good" : b.adj_tail_band === "amber" ? "warning" : "critical"}>{b.adj_tail_band}</Pill>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="mt-3 text-xs text-muted-foreground">
                A k_lo below 1 means the cohort&apos;s own p5 was already too pessimistic for that kind of window and gets pulled in, not pushed out. The &ldquo;before there was
                enough&rdquo; row is every forecast made before its window had 120 matured examples of its own; those used the pooled factor, and they are shown rather than dropped.
              </p>
            </Section>
          ) : null}

          <Section title={`Before adjustment: the raw search, ${rep.n_matured} matured forecasts`} subtitle={Object.entries(rep.by_ticker).map(([t, n]) => `${t} ${n}`).join(" · ")} action={<Pill tone={bandTone}>raw 5% tail: {rep.tail.band}</Pill>}>
            <p className="mb-3 text-sm text-muted-foreground">
              What the analog search says on its own, before the tail adjustment. The desk does not size on this; it is here because the adjustment above is only as honest as
              the number it corrects, and hiding the uncorrected one would make that impossible to check.
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Breaches below p5" value={`${rep.tail.breaches} / ${rep.tail.n}`} hint={`expected ${(rep.tail.expected_rate * rep.tail.n).toFixed(1)}`} tone={bandTone === "muted" ? undefined : bandTone} />
              <Stat label="Failure-rate test" value={rep.tail.pof_p_value != null ? `p = ${rep.tail.pof_p_value.toFixed(3)}` : "—"} hint={rep.tail.pof_stat != null ? `LR ${rep.tail.pof_stat.toFixed(2)}` : "needs ≥ 20 forecasts"} />
              <Stat label="Independence test" value={rep.tail.independence_p_value != null ? `p = ${rep.tail.independence_p_value.toFixed(3)}` : "—"} hint="do breaches cluster?" />
              <Stat label="Sharpness" value={rep.mean_width_p5_p95 != null ? `${rep.mean_width_p5_p95.toFixed(2)}%` : "—"} hint={`mean p5–p95 width · |err p50| ${rep.mean_abs_error_p50?.toFixed(2) ?? "—"}%`} />
            </div>
          </Section>

          {rep.skill && rep.skill.skill != null ? (
            <Section
              title="Does it beat guessing?"
              subtitle={`Each replay forecast is paired with the distribution of random past hours from the same time-of-week bucket. Lower pinball loss is better. ${rep.skill.n} pairs; the analogs win ${fmtPct((rep.skill.win_share ?? 0) * 100, 0, false)} of them.`}
              action={
                <Pill tone={rep.skill.diff_ci_low != null && rep.skill.diff_ci_low > 0 ? "good" : rep.skill.diff_ci_high != null && rep.skill.diff_ci_high < 0 ? "critical" : "warning"}>
                  skill {rep.skill.skill >= 0 ? "+" : ""}
                  {(rep.skill.skill * 100).toFixed(1)}%
                </Pill>
              }
            >
              <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Quantile</TableHead>
                      <TableHead className="text-right">Analog loss</TableHead>
                      <TableHead className="text-right">Random loss</TableHead>
                      <TableHead className="text-right">Skill</TableHead>
                      <TableHead className="text-right">95% CI of gain</TableHead>
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
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-2">
                    <Stat label="Mean loss, analog" value={rep.skill.mean_loss_analog?.toFixed(3) ?? "—"} hint="average pinball loss over the five quantiles" />
                    <Stat label="Mean loss, random hours" value={rep.skill.mean_loss_baseline?.toFixed(3) ?? "—"} hint={`gain CI [${rep.skill.diff_ci_low?.toFixed(3)}, ${rep.skill.diff_ci_high?.toFixed(3)}]`} />
                    <Stat label="Below p5" value={`${fmtPct((rep.skill.analog_lo_coverage ?? 0) * 100, 1, false)} vs ${fmtPct((rep.skill.baseline_lo_coverage ?? 0) * 100, 1, false)}`} hint="analog vs random · target 5%" />
                    <Stat label="Above p95" value={`${fmtPct((rep.skill.analog_hi_coverage ?? 0) * 100, 1, false)} vs ${fmtPct((rep.skill.baseline_hi_coverage ?? 0) * 100, 1, false)}`} hint="analog vs random · target 5%" />
                  </div>
                  {/* A judge reading only the headline number would conclude the retrieval
                      is useless. It is nearly useless for direction, which is why the
                      verdict never takes one from it; the tail is the part that is used. */}
                  <p className="text-xs text-muted-foreground">
                    <span className="text-foreground">How to read this.</span> Over the whole distribution the analogs are indistinguishable from picking random hours of the
                    same kind, and around the quartiles they are measurably worse — the resemblance narrows the middle where the truth is wide. Where they help is the loss
                    tail: {fmtPct((rep.skill.analog_lo_coverage ?? 0) * 100, 1, false)} of outcomes fall below the analog 5th percentile against{" "}
                    {fmtPct((rep.skill.baseline_lo_coverage ?? 0) * 100, 1, false)} below the random-hours one. That is the number every verdict is sized against, and it is
                    the only claim this product makes about the retrieval.
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Per token:{" "}
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
              title="Is it getting better or worse?"
              subtitle={`The same out-of-sample scoring, split by month. ${rep.walk_forward.note || ""}`}
              action={
                rep.walk_forward.improving == null ? null : (
                  <Pill tone={rep.walk_forward.improving ? "good" : "warning"}>{rep.walk_forward.improving ? "closing on target" : "drifting from target"}</Pill>
                )
              }
            >
              <div className="overflow-x-auto">
                <Table className="min-w-[640px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Month</TableHead>
                      <TableHead className="text-right">Scored</TableHead>
                      <TableHead className="text-right">Below p5, raw</TableHead>
                      <TableHead className="text-right">Below p5, adjusted</TableHead>
                      <TableHead className="text-right">Inside band, adjusted</TableHead>
                      <TableHead className="text-right">Band width</TableHead>
                      <TableHead className="text-right">Skill</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rep.walk_forward.periods.map((p) => (
                      <TableRow key={p.label}>
                        <TableCell className="font-medium">
                          {p.label}
                          {p.thin ? <span className="ml-2 text-xs text-muted-foreground">thin</span> : null}
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
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Targets: 5% below p5, 90% inside the band. A month marked thin has too few scored forecasts to read much into.</p>
            </Section>
          ) : null}

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
