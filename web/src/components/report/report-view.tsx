"use client";

import { AlertTriangle, CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import { CostCurve } from "@/components/charts/cost-curve";
import { Histogram } from "@/components/charts/histogram";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Report } from "@/lib/api";
import { fmtBps, fmtHours, fmtPct, fmtPrice, fmtRatio, fmtTime, fmtUsd, titleCase } from "@/lib/format";

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
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Token price" value={fmtPrice(report.snapshot.prices.spot_close)} />
          <Stat label="Fair value (index)" value={fmtPrice(report.snapshot.prices.index_close)} hint={`native close ${fmtPrice(report.snapshot.prices.native_close)} · ${fmtHours(report.snapshot.features.native_close_age_h)} old`} />
          <Stat label="Basis vs index" value={fmtBps(report.snapshot.features.basis_index_bps, 1, true)} hint={`z ${report.snapshot.features.basis_index_z?.toFixed(2) ?? "—"}`} />
          <Stat label="Realised vol (24h)" value={report.snapshot.features.rv_24h != null ? `${(report.snapshot.features.rv_24h * 100).toFixed(0)}%` : "—"} hint={`pctl ${report.snapshot.features.vol_pctl_90d?.toFixed(0) ?? "—"} · ${report.snapshot.labels.vol_state}`} />
          <Stat label="Trend vs 30d avg" value={fmtPct(report.snapshot.features.trend_sma_pct, 1)} hint={report.snapshot.labels.trend_state} />
          <Stat label="Next earnings" value={fmtHours(report.snapshot.features.hours_to_earnings)} hint={`FOMC in ${fmtHours(report.snapshot.features.hours_to_fomc)}`} />
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

      <p className="text-xs text-muted-foreground">
        Computed in {report.timings_ms.total} ms · sources: {report.sources.map((s) => String(s.kind)).join(", ")}
        {report.forecast_id != null ? ` · journaled as forecast #${report.forecast_id}` : ""}
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
      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
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
        <div className="space-y-3">
          {mc ? (
            <>
              <Histogram values={mc.terminal_ret_pct} markers={[{ value: mc.p5, label: "p5" }, { value: mc.p50, label: "p50" }, { value: mc.p95, label: "p95" }]} binCount={40} height={160} ariaLabel={`Monte Carlo terminal return distribution over ${mc.horizon_h} hours`} />
              <div className="grid grid-cols-2 gap-2">
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
