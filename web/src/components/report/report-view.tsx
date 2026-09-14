"use client";

import { AlertTriangle, CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import { useState } from "react";
import { CostCurve } from "@/components/charts/cost-curve";
import { Histogram } from "@/components/charts/histogram";
import { Permalink } from "@/components/report/permalink";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type Report } from "@/lib/api";
import { bucketLabel, fmtBps, fmtHours, fmtPct, fmtPrice, fmtRatio, fmtTime, fmtUsd, titleCase } from "@/lib/format";

const VERDICT_TONE: Record<Report["verdict"]["verdict"], "good" | "warning" | "critical" | "info" | "muted"> = {
  GO: "good",
  REDUCE_TO: "warning",
  HEDGE: "info",
  NO_GO: "critical",
  REVIEW: "muted",
};

const VERDICT_TEXT: Record<Report["verdict"]["verdict"], string> = {
  GO: "Go at the requested size",
  REDUCE_TO: "Reduce the size",
  HEDGE: "Hedge instead of cutting",
  NO_GO: "Do not take this trade as specified",
  REVIEW: "Fill in what is missing before deciding",
};

export function ReportView({ report }: { report: Report }) {
  const v = report.verdict;
  const t = report.ticket;
  const primary = report.analog?.horizons[report.primary_horizon];
  const budget = 25;

  return (
    <div className="space-y-4">
      {/* Verdict — the one number the page leads with. */}
      <Section
        title={`${t.ticker} ${t.side.toUpperCase()} · ${fmtUsd(t.notional_quote)} USDT`}
        subtitle={`Horizon ${report.primary_horizon} (${fmtHours(report.horizon_h)}) · as of ${fmtTime(report.as_of)} · ${report.snapshot.labels.session} session, ${report.snapshot.labels.regime_label} regime`}
        action={<Pill tone={VERDICT_TONE[v.verdict]}>{v.verdict.replace("_", " ")}</Pill>}
      >
        <p className="text-2xl font-semibold leading-tight">
          {VERDICT_TEXT[v.verdict]}
          {v.recommended_notional != null && v.verdict === "REDUCE_TO" ? <span className="text-muted-foreground"> → {fmtUsd(v.recommended_notional)} USDT</span> : null}
          {v.hedge_ratio ? <span className="text-muted-foreground"> → hedge {fmtRatio(v.hedge_ratio)} via perp</span> : null}
        </p>
        <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
          {v.reasons.map((r) => (
            <li key={r} className="flex gap-2">
              <span aria-hidden>–</span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
        {report.forecast_id != null ? <TakenButton forecastId={report.forecast_id} /> : null}
        {report.warnings.length ? (
          <div className="mt-4 rounded-lg border border-status-warning/40 bg-status-warning/5 p-3 text-sm">
            <p className="mb-1 flex items-center gap-2 font-medium">
              <AlertTriangle className="h-4 w-4 text-status-warning" aria-hidden /> Caveats
            </p>
            <ul className="space-y-1 text-muted-foreground">
              {report.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </Section>

      {/* Now */}
      <Section title="Right now" subtitle={`Last completed bar ${fmtTime(report.snapshot.bar_ts)} · inputs hash ${report.snapshot.content_hash}`}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7">
          <Stat label="Token price" value={fmtPrice(report.snapshot.prices.spot_close)} />
          <Stat label="Fair value (index)" value={fmtPrice(report.snapshot.prices.index_close)} hint={`native close ${fmtPrice(report.snapshot.prices.native_close)} · ${fmtHours(report.snapshot.features.native_close_age_h)} old`} />
          <Stat label="Basis vs index" value={fmtBps(report.snapshot.features.basis_index_bps, 1, true)} hint={`z ${report.snapshot.features.basis_index_z?.toFixed(2) ?? "—"}`} />
          <Stat label="Realised vol (24h)" value={report.snapshot.features.rv_24h != null ? `${(report.snapshot.features.rv_24h * 100).toFixed(0)}%` : "—"} hint={`pctl ${report.snapshot.features.vol_pctl_90d?.toFixed(0) ?? "—"} · ${report.snapshot.labels.vol_state}`} />
          <Stat label="Trend vs 30d avg" value={fmtPct(report.snapshot.features.trend_sma_pct, 1)} hint={report.snapshot.labels.trend_state} />
          <Stat label="Next earnings" value={fmtHours(report.snapshot.features.hours_to_earnings)} hint={`FOMC in ${fmtHours(report.snapshot.features.hours_to_fomc)}`} />
          <Stat
            label="Last SEC filing"
            // 720 h is the cap the feature carries, not a measurement: say "over 30 d", not "30 d".
            value={report.snapshot.features.hours_since_filing != null ? (report.snapshot.features.hours_since_filing >= 720 ? "over 30 d ago" : `${fmtHours(report.snapshot.features.hours_since_filing)} ago`) : "—"}
            hint={report.snapshot.features.filings_72h ? `${report.snapshot.features.filings_72h} in the last 72h` : "none in the last 72h"}
            tone={report.snapshot.features.filings_72h ? "warning" : undefined}
          />
        </div>
        {report.snapshot.quality_flags.length ? (
          <p className="mt-3 text-xs text-muted-foreground">Flags: {report.snapshot.quality_flags.join(", ")}</p>
        ) : null}
      </Section>

      {/* Analogs */}
      <AnalogSection report={report} />

      {/* Stress */}
      <StressSection report={report} />

      {/* Exit & hedge */}
      <Section title="Getting out" subtitle={`${report.execution.book_source} order book${report.execution.book_ts ? ` · ${fmtTime(report.execution.book_ts)}` : ""}`}>
        {report.execution.exit_quote ? (
          <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
            <div className="grid grid-cols-2 gap-2">
              <Stat label={`Exit ${fmtUsd(report.execution.exit_quote.notional_quote)}`} value={fmtBps(report.execution.exit_quote.total_cost_bps)} hint={`${fmtBps(report.execution.exit_quote.walk_cost_bps)} walk + ${report.execution.exit_quote.fee_bps.toFixed(0)} bps fee`} tone={report.execution.exit_quote.fully_filled ? undefined : "critical"} />
              <Stat label="Fills" value={report.execution.exit_quote.fully_filled ? "Yes" : "No"} hint={`${report.execution.exit_quote.levels_consumed} levels`} tone={report.execution.exit_quote.fully_filled ? "good" : "critical"} />
              <Stat label={`Max size ≤ ${budget} bps`} value={fmtUsd(report.execution.max_notional_within_budget)} />
              {report.execution.hedge_quote ? (
                <Stat label={`Hedge 100% via ${report.execution.hedge_quote.perp_symbol}`} value={fmtBps(report.execution.hedge_quote.total_cost_bps_of_position)} hint={`fees ${fmtUsd(report.execution.hedge_quote.entry_fee_quote + report.execution.hedge_quote.exit_fee_quote, 2)} · funding ${fmtUsd(report.execution.hedge_quote.funding_quote, 2)} · residual basis p95 ${fmtBps(report.execution.hedge_quote.residual_basis_p95_bps, 0)}`} />
              ) : null}
            </div>
            {report.execution.cost_curve ? <CostCurve points={report.execution.cost_curve} requested={t.notional_quote} budgetBps={budget} /> : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No order book was available, so exit cost is unknown. Start the recorder or allow live book fetches.</p>
        )}
        <LiquidityByTimeOfWeek report={report} />
      </Section>

      {/* Gate + caps */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title={`Discipline gate · ${report.gate.decision.replace("_", " ")}`} subtitle={report.gate.risk_quote != null ? `Risk at stake ${fmtUsd(report.gate.risk_quote)} (${report.gate.risk_basis})` : undefined}>
          <ul className="space-y-2">
            {report.gate.rules.map((r) => (
              <li key={r.rule} className="flex items-start gap-2 text-sm">
                {r.decision === "GO" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-status-good" aria-label="passed" /> : r.decision === "REVIEW_REQUIRED" ? <CircleHelp className="mt-0.5 h-4 w-4 shrink-0 text-status-warning" aria-label="needs review" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-status-critical" aria-label="failed" />}
                <span>
                  <span className="font-medium">{titleCase(r.rule)}</span>
                  <span className="text-muted-foreground"> — {r.reason}</span>
                </span>
              </li>
            ))}
          </ul>
        </Section>
        <Section title="Sizing caps" subtitle="The smallest cap binds. Each one is independent and named.">
          <ul className="space-y-2">
            {report.sizing.caps.map((c) => {
              const binding = c.name === report.sizing.binding_cap;
              const max = Math.max(t.notional_quote, ...report.sizing.caps.map((x) => x.notional ?? 0));
              const width = c.notional == null ? 0 : Math.min(100, (c.notional / max) * 100);
              return (
                <li key={c.name} className="space-y-1">
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className={binding ? "font-semibold" : ""}>
                      {titleCase(c.name)}
                      {binding ? <Pill tone="warning">binds</Pill> : null}
                    </span>
                    <span className="tabular text-muted-foreground">{c.notional == null ? "n/a" : fmtUsd(c.notional)}</span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-muted" aria-hidden>
                    <div className={`h-1.5 rounded-full ${binding ? "bg-status-warning" : "bg-chart-1"}`} style={{ width: `${width}%` }} />
                  </div>
                  <p className="text-xs text-muted-foreground">{c.detail}</p>
                </li>
              );
            })}
          </ul>
        </Section>
      </div>

      {/* The case against */}
      <SecondOpinionSection report={report} />

      {/* The coarse map */}
      <RegimeSection report={report} />

      {/* The whole book */}
      <PortfolioSection report={report} />

      {/* The trader's own record */}
      <BreakerStrip report={report} />

      {/* What happened last time */}
      <LessonsSection report={report} />

      {/* What would change it */}
      <SensitivitySection report={report} />

      <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
        <span>
          Computed in {report.timings_ms.total} ms · sources: {report.sources.map((s) => String(s.kind)).join(", ")}
          {report.forecast_id != null ? ` · journaled as forecast #${report.forecast_id}` : ""}
        </span>
        {report.forecast_id != null ? <Permalink forecastId={report.forecast_id} /> : null}
      </p>
      {primary ? null : null}
    </div>
  );
}

function AnalogSection({ report }: { report: Report }) {
  const a = report.analog;
  if (!a || !a.result.ok) {
    return (
      <Section title="What history says" subtitle="Nearest past moments to now">
        <p className="text-sm text-muted-foreground">No analog cohort: {a?.result.reason ?? "search did not run"}. The verdict uses the stop for risk.</p>
      </Section>
    );
  }
  const primary = a.horizons[report.primary_horizon];
  const values = a.matches_outcomes.map((m) => m.outcomes[report.primary_horizon]?.ret_pct).filter((x): x is number => typeof x === "number");
  const c = primary?.cohort;
  const markers =
    c && !c.insufficient
      ? [
          { value: (primary?.p5_adjusted ?? c.p5) as number, label: primary?.p5_adjusted != null ? "p5 cal." : "p5" },
          { value: c.median_pct as number, label: "median" },
          { value: (primary?.p95_adjusted ?? c.p95) as number, label: primary?.p95_adjusted != null ? "p95 cal." : "p95" },
        ]
      : [];
  return (
    <Section
      title="What history says"
      subtitle={`${a.result.matches.length} distinct past moments most like now (${a.scope === "pooled" ? "pooled across tokens" : "same token"}; ${a.result.n_candidates.toLocaleString()} candidate hours, ${a.result.n_distinct_available.toLocaleString()} distinct)`}
    >
      {c && !c.insufficient ? (
        <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
          <div>
            <Histogram values={values} markers={markers} ariaLabel={`Distribution of token returns over ${report.primary_horizon} after the ${a.result.matches.length} most similar past moments`} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Stat label={`Median over ${report.primary_horizon}`} value={fmtPct(c.median_pct)} hint={`mean ${fmtPct(c.mean_pct)} [${fmtPct(c.ci_mean?.low)}, ${fmtPct(c.ci_mean?.high)}]`} />
            <Stat label="Win rate" value={fmtRatio(c.win_rate)} hint={`n = ${c.n}${c.n_pending ? `, ${c.n_pending} pending` : ""}`} />
            {primary?.p5_adjusted != null ? (
              <Stat label="5th percentile (calibrated)" value={fmtPct(primary.p5_adjusted)} hint={`raw ${fmtPct(c.p5)} · tails widened ×${primary.adjustment?.k_lo.toFixed(2)} from ${primary.adjustment?.n_fit} scored replays`} tone="critical" />
            ) : (
              <Stat label="5th percentile" value={fmtPct(c.p5)} hint={`CI [${fmtPct(c.ci_p5?.low)}, ${fmtPct(c.ci_p5?.high)}]`} tone="critical" />
            )}
            <Stat label="Average of the worst 5%" value={fmtPct(c.es5_pct)} hint={c.es5_n ? `${c.es5_n} episode${c.es5_n === 1 ? "" : "s"} below p5` : undefined} tone="critical" />
            <Stat label="Worst point in window (p5)" value={fmtPct(c.mae_p5_pct)} hint={`median worst ${fmtPct(c.mae_median_pct)}`} />
            {primary?.p95_adjusted != null ? (
              <Stat label="95th percentile (calibrated)" value={fmtPct(primary.p95_adjusted)} hint={`raw ${fmtPct(c.p95)} · ×${primary.adjustment?.k_hi.toFixed(2)}`} tone="good" />
            ) : (
              <Stat label="95th percentile" value={fmtPct(c.p95)} tone="good" />
            )}
            <Stat label="Max |basis| p95" value={fmtBps(c.max_abs_basis_p95_bps, 0)} hint="inside the window" />
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Cohort for {report.primary_horizon} is below the minimum sample (n = {c?.n ?? 0}). No distribution is shown.</p>
      )}
      <div className="mt-4 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Horizon</TableHead>
              <TableHead className="text-right">n</TableHead>
              <TableHead className="text-right">Median</TableHead>
              <TableHead className="text-right">p5</TableHead>
              <TableHead className="text-right">p95</TableHead>
              <TableHead className="text-right">Win</TableHead>
              <TableHead className="text-right">vs random hours</TableHead>
              <TableHead>Outcomes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Object.values(a.horizons).map((h) => (
              <TableRow key={h.horizon} className={h.horizon === report.primary_horizon ? "bg-accent/40" : ""}>
                <TableCell className="font-medium">
                  {titleCase(h.horizon)} <span className="text-muted-foreground">({fmtHours(h.hours)})</span>
                </TableCell>
                <TableCell className="tabular text-right">{h.cohort.n}</TableCell>
                <TableCell className="tabular text-right">{h.cohort.insufficient ? "—" : fmtPct(h.cohort.median_pct)}</TableCell>
                <TableCell className="tabular text-right">{h.cohort.insufficient ? "—" : fmtPct(h.cohort.p5)}</TableCell>
                <TableCell className="tabular text-right">{h.cohort.insufficient ? "—" : fmtPct(h.cohort.p95)}</TableCell>
                <TableCell className="tabular text-right">{h.cohort.insufficient ? "—" : fmtRatio(h.cohort.win_rate)}</TableCell>
                <TableCell className="tabular text-right">
                  {h.baseline?.mean_diff_pct != null ? (
                    <span>
                      {fmtPct(h.baseline.mean_diff_pct)} <span className="text-muted-foreground">(p = {h.baseline.permutation_p_value?.toFixed(2)})</span>
                    </span>
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {Object.entries(h.cohort.tag_counts)
                    .sort((x, y) => y[1] - x[1])
                    .map(([k, n]) => `${titleCase(k.toLowerCase())} ${n}`)
                    .join(" · ")}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ClosestMoments report={report} />
    </Section>
  );
}

/** The retrieved scenarios themselves: when they were, why they matched, what followed. */
function ClosestMoments({ report }: { report: Report }) {
  const a = report.analog;
  const [open, setOpen] = useState(false);
  if (!a || !a.result.ok || a.result.matches.length === 0) return null;
  const byTs = new Map(a.matches_outcomes.map((m) => [m.ts, m]));
  const shown = open ? a.result.matches : a.result.matches.slice(0, 6);
  const f = (v: number | undefined, digits = 2) => (v == null || Number.isNaN(v) ? "—" : v.toFixed(digits));
  return (
    <div className="mt-4">
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <p className="text-xs font-medium text-muted-foreground">
          The moments themselves · matched on {a.result.features_used.length} features{a.result.features_dropped.length ? `, ${a.result.features_dropped.length} dropped as constant` : ""}
        </p>
        <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)}>
          {open ? "Show fewer" : `Show all ${a.result.matches.length}`}
        </Button>
      </div>
      <div className="overflow-x-auto">
        <Table className="min-w-[720px]">
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Session</TableHead>
              <TableHead className="text-right">Similarity</TableHead>
              <TableHead className="text-right">Vol pctl</TableHead>
              <TableHead className="text-right">Basis z</TableHead>
              <TableHead className="text-right">Trend</TableHead>
              <TableHead className="text-right">To earnings</TableHead>
              <TableHead className="text-right">What followed</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((m) => {
              const o = byTs.get(m.ts)?.outcomes[report.primary_horizon];
              const hte = m.features.hours_to_earnings;
              return (
                <TableRow key={`${m.ticker}-${m.ts}`}>
                  <TableCell className="whitespace-nowrap">
                    {fmtTime(m.ts)}
                    {m.ticker !== report.ticket.ticker ? <span className="block text-xs text-muted-foreground">{m.ticker}</span> : null}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{bucketLabel(m.bucket)}</TableCell>
                  <TableCell className="tabular text-right">{fmtRatio(m.similarity)}</TableCell>
                  <TableCell className="tabular text-right">{f(m.features.vol_pctl_90d, 0)}</TableCell>
                  <TableCell className="tabular text-right">{f(m.features.basis_index_z)}</TableCell>
                  <TableCell className="tabular text-right">{fmtPct(m.features.trend_sma_pct, 1)}</TableCell>
                  <TableCell className="tabular text-right">{hte == null ? "—" : hte >= 720 ? "> 30 d" : `${hte.toFixed(0)} h`}</TableCell>
                  <TableCell className="tabular text-right">
                    {o?.status === "MATURED" ? (
                      <>
                        <span className={o.ret_pct != null && o.ret_pct < 0 ? "text-status-critical" : "text-status-good"}>{fmtPct(o.ret_pct)}</span>
                        <span className="block text-xs text-muted-foreground">worst {fmtPct(o.mae_pct)}</span>
                      </>
                    ) : (
                      <span className="text-muted-foreground">still open</span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

const SIZE_TONE: Record<string, "good" | "warning" | "critical" | "info" | "muted"> = { GO: "good", REDUCE_TO: "warning", HEDGE: "info", NO_GO: "critical", REVIEW: "muted" };

const LESSON_TONE: Record<string, "good" | "warning" | "critical" | "info" | "muted"> = {
  worse_than_stress: "critical",
  bad_tail: "warning",
  as_expected: "muted",
  good_tail: "info",
  better_than_forecast: "good",
  no_distribution: "muted",
};

const LESSON_LABEL: Record<string, string> = {
  worse_than_stress: "worse than the stress case",
  bad_tail: "bad tail",
  as_expected: "as expected",
  good_tail: "good tail",
  better_than_forecast: "better than forecast",
  no_distribution: "no forecast",
};

function SecondOpinionSection({ report }: { report: Report }) {
  const so = report.second_opinion;
  if (!so || (so.against.length === 0 && so.supporting.length === 0)) return null;
  return (
    <Section title="The case against this" subtitle={so.summary}>
      <ul className="space-y-2">
        {so.against.map((c) => (
          <li key={c.text} className="flex gap-2 text-sm">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-status-critical" aria-hidden />
            <span>
              {c.text} <span className="text-xs text-muted-foreground">{c.source}</span>
            </span>
          </li>
        ))}
        {so.supporting.map((c) => (
          <li key={c.text} className="flex gap-2 text-sm">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-status-good" aria-hidden />
            <span>
              {c.text} <span className="text-xs text-muted-foreground">{c.source}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted-foreground">Every point quotes a number from this report. Ranked by what it is worth in money, with one point from each source before any source repeats.</p>
    </Section>
  );
}

/** The recorded archive: is the book always this good, or only right now? */
function LiquidityByTimeOfWeek({ report }: { report: Report }) {
  const h = report.execution.liquidity_history;
  if (!h || h.buckets.length === 0) return null;
  const usable = h.buckets.filter((b) => !b.thin);
  if (usable.length === 0) {
    return <p className="mt-4 text-xs text-muted-foreground">The book archive has {h.n_snapshots.toLocaleString()} snapshots so far, not yet enough in any one part of the week to compare. It fills in as the recorder runs.</p>;
  }
  return (
    <div className="mt-4">
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        The same book at other times of the week · {h.n_snapshots.toLocaleString()} recorded snapshots{h.since ? ` since ${fmtTime(h.since)}` : ""}
      </p>
      <div className="overflow-x-auto">
        <Table className="min-w-[520px]">
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead className="text-right">Spread</TableHead>
              <TableHead className="text-right">Sellable inside 25 bps</TableHead>
              <TableHead className="text-right">Bad case</TableHead>
              <TableHead className="text-right">Too thin for {fmtUsd(h.reference_notional)}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {h.buckets.map((b) => (
              <TableRow key={b.bucket}>
                <TableCell>
                  {bucketLabel(b.bucket)}
                  {b.thin ? <span className="ml-2 text-xs text-muted-foreground">thin</span> : null}
                </TableCell>
                <TableCell className="tabular text-right">{fmtBps(b.spread_median_bps, 1)}</TableCell>
                <TableCell className="tabular text-right">{fmtUsd(b.depth_25bps_median)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">{fmtUsd(b.depth_25bps_p5)}</TableCell>
                <TableCell className={`tabular text-right ${(b.share_below_reference ?? 0) > 0.25 ? "text-status-warning" : ""}`}>
                  {b.share_below_reference == null ? "—" : fmtPct(b.share_below_reference * 100, 0, false)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {h.note ? <p className="mt-1 text-xs text-muted-foreground">{h.note}</p> : null}
    </div>
  );
}

function RegimeSection({ report }: { report: Report }) {
  const m = report.regimes;
  if (!m || m.regimes.length === 0) return null;
  const current = m.regimes.find((r) => r.id === m.current) ?? null;
  const nextLikely = m.current != null ? m.transitions[m.current].map((p, j) => ({ j, p })).filter((x) => x.j !== m.current).sort((a, b) => b.p - a.p).slice(0, 2) : [];
  return (
    <Section
      title="What kind of market this is"
      subtitle={`${m.n_fitted.toLocaleString()} past hours grouped into ${m.regimes.length} states by volatility, basis, trend and liquidity. Fitted only on hours before this moment, sorted calmest first.`}
      action={current ? <Pill tone={current.id >= m.regimes.length - 1 ? "warning" : "muted"}>now: {current.description}</Pill> : null}
    >
      <div className="overflow-x-auto">
        <Table className="min-w-[720px]">
          <TableHeader>
            <TableRow>
              <TableHead>State</TableHead>
              <TableHead className="text-right">Share of hours</TableHead>
              <TableHead className="text-right">Stays put</TableHead>
              <TableHead className="text-right">Next {fmtHours(m.horizon_h)}, median</TableHead>
              <TableHead className="text-right">Never moved</TableHead>
              <TableHead className="text-right">Next {fmtHours(m.horizon_h)}, p5</TableHead>
              <TableHead className="text-right">Episodes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {m.regimes.map((r) => (
              <TableRow key={r.id} className={r.id === m.current ? "bg-accent/40" : ""}>
                <TableCell>
                  <span className={r.id === m.current ? "font-semibold" : ""}>{r.description}</span>
                  {r.id === m.current ? <span className="ml-2 text-xs text-muted-foreground">now</span> : null}
                </TableCell>
                <TableCell className="tabular text-right">{fmtPct(r.share * 100, 0, false)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">{r.persistence == null ? "—" : fmtPct(r.persistence * 100, 0, false)}</TableCell>
                <TableCell className="tabular text-right">{r.next_ret_median_pct == null ? "—" : fmtPct(r.next_ret_median_pct)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">{r.flat_share == null ? "—" : fmtPct(r.flat_share * 100, 0, false)}</TableCell>
                <TableCell className="tabular text-right text-status-critical">{r.next_ret_p5_pct == null ? "—" : fmtPct(r.next_ret_p5_pct)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">{r.n_outcomes.toLocaleString()}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {nextLikely.length ? (
        <p className="mt-2 text-sm text-muted-foreground">
          If it changes, the usual next states are{" "}
          {nextLikely.map((x, i) => (
            <span key={x.j}>
              {i > 0 ? " and " : ""}
              <span className="text-foreground">{m.regimes.find((r) => r.id === x.j)?.description}</span> ({fmtPct(x.p * 100, 0, false)})
            </span>
          ))}
          .
        </p>
      ) : null}
      <p className="mt-2 text-xs text-muted-foreground">
        The medians sit on zero because these tokens do not trade every hour: in the &ldquo;never moved&rdquo; share of windows the price ends on the same
        last trade it started on. The p5 column is the one the sizing uses.
      </p>
    </Section>
  );
}

function PortfolioSection({ report }: { report: Report }) {
  const p = report.portfolio;
  if (!p) return null;
  const added = p.before.tail_loss_quote != null && p.after.tail_loss_quote != null ? p.after.tail_loss_quote - p.before.tail_loss_quote : null;
  const div = p.after.diversification_ratio;
  return (
    <Section
      title="What it does to the book"
      subtitle={`Your ${p.positions.length} position${p.positions.length === 1 ? "" : "s"} together, over ${fmtHours(p.horizon_h)}. Correlations are measured on the tokens' own hourly history, not assumed.`}
      action={div != null ? <Pill tone={div > 0.9 ? "critical" : div > 0.75 ? "warning" : "good"}>{div > 0.9 ? "one bet" : div > 0.75 ? "thin diversification" : "diversified"}</Pill> : null}
    >
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="grid grid-cols-2 gap-2">
          <Stat label="Gross exposure" value={fmtUsd(p.after.gross_quote)} hint={p.after.gross_pct_of_equity != null ? `${p.after.gross_pct_of_equity.toFixed(0)}% of equity · was ${fmtUsd(p.before.gross_quote)}` : `was ${fmtUsd(p.before.gross_quote)}`} />
          <Stat label="Net exposure" value={fmtUsd(p.after.net_quote)} hint={p.after.net_pct_of_equity != null ? `${p.after.net_pct_of_equity.toFixed(0)}% of equity` : undefined} />
          <Stat label="Largest name" value={p.after.largest_name ?? "—"} hint={p.after.largest_pct_of_gross != null ? `${p.after.largest_pct_of_gross.toFixed(0)}% of gross · top three ${p.after.top3_pct_of_gross?.toFixed(0)}%` : undefined} tone={p.after.largest_pct_of_gross != null && p.after.largest_pct_of_gross > 60 ? "warning" : undefined} />
          <Stat
            label="Book 5th-percentile loss"
            value={fmtUsd(p.after.tail_loss_quote)}
            hint={added != null ? `this trade adds ${fmtUsd(Math.abs(added))}` : "needs history for every name"}
            tone="critical"
          />
          {p.after.standalone_tail_sum_quote != null ? (
            <Stat label="If the names were independent" value={fmtUsd(p.after.standalone_tail_sum_quote)} hint={div != null ? `the book keeps ${fmtPct(div * 100, 0, false)} of that` : undefined} />
          ) : null}
          {p.mean_correlation_to_book != null ? (
            <Stat label={`${report.ticket.ticker} vs the book`} value={p.mean_correlation_to_book.toFixed(2)} hint="mean measured correlation" tone={p.mean_correlation_to_book > 0.7 ? "warning" : undefined} />
          ) : null}
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Measured correlation</p>
          <div className="overflow-x-auto">
            <Table className="min-w-[320px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Pair</TableHead>
                  <TableHead className="text-right">Correlation</TableHead>
                  <TableHead className="text-right">Hours</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {p.correlations.slice(0, 6).map((c) => (
                  <TableRow key={`${c.a}-${c.b}`}>
                    <TableCell>
                      {c.a} · {c.b}
                    </TableCell>
                    <TableCell className={`tabular text-right ${c.correlation != null && c.correlation > 0.7 ? "text-status-warning" : ""}`}>{c.correlation == null ? "not enough overlap" : c.correlation.toFixed(2)}</TableCell>
                    <TableCell className="tabular text-right text-muted-foreground">{c.overlap_hours.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
      {p.attribution && p.attribution.book_tail_quote != null ? (
        <div className="mt-4 overflow-x-auto">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Who carries the bad case · measured in the {p.attribution.n_windows.toLocaleString()} historical windows where this book was at its worst
          </p>
          <Table className="min-w-[560px]">
            <TableHeader>
              <TableRow>
                <TableHead>Position</TableHead>
                <TableHead className="text-right">Weight</TableHead>
                <TableHead className="text-right">Share of the loss</TableHead>
                <TableHead className="text-right">Loss in the bad case</TableHead>
                <TableHead className="text-right">If you dropped it</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {p.attribution.contributions.map((c) => (
                <TableRow key={`${c.ticker}-${c.side}-${c.notional_quote}`}>
                  <TableCell>
                    <span className="font-medium">{c.ticker}</span> <span className="text-muted-foreground">{c.side}</span>
                    <span className="block text-xs text-muted-foreground">{fmtUsd(c.notional_quote)}</span>
                  </TableCell>
                  <TableCell className="tabular text-right text-muted-foreground">{fmtPct(c.share_of_gross * 100, 0, false)}</TableCell>
                  <TableCell className={`tabular text-right ${c.component_share != null && c.component_share > c.share_of_gross * 1.25 ? "text-status-warning" : ""}`}>
                    {c.component_share == null ? c.note || "unknown" : fmtPct(c.component_share * 100, 0, false)}
                  </TableCell>
                  <TableCell className="tabular text-right">{c.component_quote == null ? "—" : fmtUsd(c.component_quote)}</TableCell>
                  <TableCell className="tabular text-right text-muted-foreground">
                    {c.marginal_quote == null ? "—" : c.marginal_quote < 0 ? `tail improves ${fmtUsd(Math.abs(c.marginal_quote))}` : `tail worsens ${fmtUsd(Math.abs(c.marginal_quote))}`}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-1 text-xs text-muted-foreground">A share of the loss well above the weight means that position is doing more damage than its size suggests.</p>
        </div>
      ) : null}
      {p.notes.length ? (
        <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
          {p.notes.map((n) => (
            <li key={n}>– {n}</li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}

/** Marking a trade taken is what turns an analysis into part of the loss record. */
function TakenButton({ forecastId }: { forecastId: number }) {
  const [state, setState] = useState<"idle" | "saving" | "taken" | "error">("idle");
  if (state === "taken") {
    return (
      <p className="mt-4 text-sm text-status-good">
        Logged as taken. It now counts towards your loss limits, and will be scored when the horizon passes.{" "}
        <button type="button" className="underline underline-offset-2" onClick={() => { setState("saving"); api.markTaken(forecastId, false).then(() => setState("idle")).catch(() => setState("error")); }}>
          Undo
        </button>
      </p>
    );
  }
  return (
    <div className="mt-4 flex items-center gap-3">
      <Button
        variant="secondary"
        size="sm"
        disabled={state === "saving"}
        onClick={() => { setState("saving"); api.markTaken(forecastId, true).then(() => setState("taken")).catch(() => setState("error")); }}
      >
        I took this trade
      </Button>
      <span className="text-xs text-muted-foreground">
        {state === "error" ? "Could not save that. Try again." : "Only trades you mark are counted by the circuit breaker."}
      </span>
    </div>
  );
}

function BreakerStrip({ report }: { report: Report }) {
  const b = report.breaker;
  if (!b) return null;
  // Nothing to say to someone who has not logged a trade yet.
  if (b.state === "NORMAL" && b.n_taken === 0) return null;
  const tone = b.state === "HALTED" ? "critical" : b.state === "COOLDOWN" ? "warning" : "good";
  return (
    <Section
      title="Your recent record"
      subtitle={`${b.n_taken} trade${b.n_taken === 1 ? "" : "s"} marked as taken. Only these count; analyses you did not act on are ignored.`}
      action={<Pill tone={tone}>{b.state.toLowerCase()}</Pill>}
    >
      <ul className="mb-3 space-y-1 text-sm text-muted-foreground">
        {b.reasons.map((r) => (
          <li key={r}>– {r}</li>
        ))}
      </ul>
      <div className="grid grid-cols-3 gap-2">
        {b.windows.map((w) => (
          <Stat
            key={w.name}
            label={`Last ${w.name}`}
            value={fmtUsd(w.realised_quote)}
            hint={w.limit_quote != null ? `${fmtPct((w.used_fraction ?? 0) * 100, 0, false)} of the ${fmtUsd(w.limit_quote)} limit · ${w.n_trades} trades` : `${w.n_trades} trades · no limit without equity`}
            tone={w.used_fraction != null && w.used_fraction >= 1 ? "critical" : w.used_fraction != null && w.used_fraction >= 0.75 ? "warning" : undefined}
          />
        ))}
      </div>
    </Section>
  );
}

function LessonsSection({ report }: { report: Report }) {
  const lessons = report.lessons ?? [];
  if (lessons.length === 0) return null;
  return (
    <Section
      title="What happened last time"
      subtitle="Past calls in conditions like these, scored after the fact. Each is one episode, not evidence: the distribution above is what you size against."
    >
      <ul className="space-y-2">
        {lessons.map((l) => (
          <li key={l.forecast_id} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
            <Pill tone={LESSON_TONE[l.classification] ?? "muted"}>{LESSON_LABEL[l.classification] ?? l.classification}</Pill>
            <span className="flex-1 text-muted-foreground">{l.text}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function SensitivitySection({ report }: { report: Report }) {
  const sen = report.sensitivity;
  if (!sen || sen.sizes.length === 0) return null;
  const requested = sen.requested_notional;
  const maxNotional = Math.max(...sen.sizes.map((p) => p.notional));
  return (
    <Section
      title="What would change it"
      subtitle="The same gate, caps and verdict, re-run at other sizes and stops. Nothing here is an estimate of the verdict; it is the verdict."
      action={sen.max_go_notional != null ? <Pill tone="good">GO up to {fmtUsd(sen.max_go_notional)}</Pill> : <Pill tone="critical">no size is a GO</Pill>}
    >
      <div className="space-y-4">
        <ul className="space-y-1 text-sm">
          {sen.notes.map((n) => (
            <li key={n} className="text-muted-foreground">
              – {n}
            </li>
          ))}
        </ul>
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Verdict by size</p>
          <ul className="space-y-1">
            {sen.sizes.map((p) => {
              const isRequest = Math.abs(p.notional - requested) < 1;
              return (
                <li key={p.notional} className="grid grid-cols-[5.5rem_1fr] items-center gap-x-2 gap-y-0.5 text-xs sm:grid-cols-[5.5rem_8rem_6rem_1fr]">
                  <span className={`tabular text-right ${isRequest ? "font-semibold" : "text-muted-foreground"}`}>
                    {fmtUsd(p.notional)}
                    {isRequest ? <span className="block text-[10px] font-normal text-muted-foreground">requested</span> : null}
                  </span>
                  <span className="hidden h-2 w-full rounded-full bg-muted sm:block" aria-hidden>
                    <span className="block h-2 rounded-full" style={{ width: `${Math.max(3, (p.notional / maxNotional) * 100)}%`, background: `var(--${p.verdict === "GO" ? "status-good" : p.verdict === "NO_GO" ? "status-critical" : p.verdict === "HEDGE" ? "chart-1" : "status-warning"})` }} />
                  </span>
                  <span className="justify-self-start">
                    <Pill tone={SIZE_TONE[p.verdict] ?? "muted"}>{p.verdict.replace("_", " ")}</Pill>
                  </span>
                  <span className="col-span-2 text-muted-foreground sm:col-span-1">
                    {p.binding_cap ? `${titleCase(p.binding_cap)} binds` : ""}
                    {p.exit_cost_bps != null ? ` · exit ${fmtBps(p.exit_cost_bps, 0)}` : ""}
                    {p.risk_pct_of_equity != null ? ` · risk ${p.risk_pct_of_equity.toFixed(2)}% of equity` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
        {sen.stops.length ? (
          <div className="overflow-x-auto">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Risk by stop distance, at the requested size</p>
            <Table className="min-w-[420px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Stop distance</TableHead>
                  <TableHead className="text-right">Stop price</TableHead>
                  <TableHead className="text-right">Risk, % of equity</TableHead>
                  <TableHead className="text-right">Risk-budget cap</TableHead>
                  <TableHead className="text-right">Verdict</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sen.stops.map((p) => (
                  <TableRow key={p.stop_distance_pct}>
                    <TableCell className="tabular">{p.stop_distance_pct.toFixed(2)}%</TableCell>
                    <TableCell className="tabular text-right">{fmtPrice(p.stop_price)}</TableCell>
                    <TableCell className="tabular text-right">{p.risk_pct_of_equity != null ? `${p.risk_pct_of_equity.toFixed(2)}%` : "—"}</TableCell>
                    <TableCell className="tabular text-right">{fmtUsd(p.risk_budget_notional)}</TableCell>
                    <TableCell className="text-right">
                      <Pill tone={SIZE_TONE[p.verdict] ?? "muted"}>{p.verdict.replace("_", " ")}</Pill>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </div>
    </Section>
  );
}

function StressSection({ report }: { report: Report }) {
  const s = report.stress;
  const mc = s.monte_carlo;
  const rows = s.presets.map((p, i) => ({ p, imp: s.impacts[i] }));
  const sevTone = (sev: string): "good" | "warning" | "critical" | "muted" => (sev === "extreme" ? "critical" : sev === "severe" ? "warning" : "muted");
  return (
    <Section
      title="What could go wrong"
      subtitle={`Presets calibrated from this token's own history: ${s.inputs_summary.closed_windows_n} closed windows, ${s.inputs_summary.earnings_gaps_n} earnings gaps, ${s.inputs_summary.closed_basis_obs_n} closed-hour basis observations`}
    >
      <div className="space-y-4">
        <div className="overflow-x-auto">
          <Table className="min-w-[560px]">
            <TableHeader>
              <TableRow>
                <TableHead>Scenario</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead className="text-right">Shock</TableHead>
                <TableHead className="text-right">P&amp;L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ p, imp }) => {
                const breach = Object.entries(imp.breaches).filter(([, v]) => v).map(([k]) => titleCase(k));
                const shock = p.price_move_pct ? fmtPct(p.price_move_pct, 1) : p.basis_shock_bps ? fmtBps(p.basis_shock_bps, 0) : p.depth_multiplier !== 1 ? `depth ×${p.depth_multiplier}` : p.funding_rate ? `${(p.funding_rate * 1e4).toFixed(1)} bps / 8h` : "—";
                return (
                  <TableRow key={p.id}>
                    <TableCell>
                      <span className="font-medium">{p.name}</span>
                      <span className="block text-xs text-muted-foreground">{p.probability_note}</span>
                    </TableCell>
                    <TableCell>
                      <Pill tone={sevTone(p.severity)}>{p.severity}</Pill>
                    </TableCell>
                    <TableCell className="tabular text-right">{shock}</TableCell>
                    <TableCell className="tabular text-right">
                      <span className={imp.total_pct_of_notional != null && imp.total_pct_of_notional < -5 ? "text-status-critical" : ""}>{fmtPct(imp.total_pct_of_notional)}</span>
                      <span className="block text-xs text-muted-foreground">
                        {fmtUsd(imp.total_pnl_quote)} {breach.length ? `· ${breach.join(", ")}` : ""}
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {mc ? (
            <>
              <Histogram values={mc.terminal_ret_pct} markers={[{ value: mc.p5, label: "p5" }, { value: mc.p50, label: "p50" }, { value: mc.p95, label: "p95" }]} binCount={40} height={180} ariaLabel={`Monte Carlo terminal return distribution over ${mc.horizon_h} hours`} />
              <div className="grid grid-cols-2 gap-2 content-start">
                <Stat label={`Monte Carlo p5 (${mc.horizon_h}h)`} value={fmtPct(mc.p5)} hint={`${mc.n_paths.toLocaleString()} paths · block bootstrap of ${mc.source_hours.toLocaleString()} hours`} tone="critical" />
                <Stat label="Expected shortfall (5%)" value={fmtPct(mc.expected_shortfall_5_pct)} hint={`P(loss > 5%) ${fmtRatio(mc.prob_loss_gt["5.0"])}`} />
                <Stat label="Worst point in window (p5)" value={fmtPct(mc.drawdown_p5)} />
                <Stat label="Move that loses 5% after costs" value={fmtPct(s.reverse_move_pct_for_5pct_loss)} />
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Not enough hourly history for a Monte Carlo over this horizon.</p>
          )}
        </div>
      </div>
    </Section>
  );
}
