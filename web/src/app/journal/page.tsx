"use client";

import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { fmtPct, fmtTime, fmtUsd } from "@/lib/format";

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
const LIMIT = 60; // a readable page; the whole journal is available from the API and the CLI

export default function JournalPage() {
  const [rows, setRows] = useState<ForecastRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<(typeof KINDS)[number]>("all");

  async function load() {
    setError(null);
    setRows(null);
    try {
      const r = (await api.forecasts(LIMIT, undefined, kind === "all" ? undefined : kind)) as unknown as ForecastRow[];
      setRows([...r].reverse()); // newest first
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the journal.");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

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
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Everything it has predicted</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            Each row was written down before the outcome existed, with the hash of the exact inputs. Replays are point-in-time forecasts over past closed-market windows; tickets are live
            analyses. Nothing is edited afterwards; maturing only adds the result.
          </p>
        </div>
        <div className="flex gap-1" role="group" aria-label="Forecast kind">
          {KINDS.map((k) => (
            <Button key={k} size="sm" variant={kind === k ? "default" : "secondary"} onClick={() => setKind(k)}>
              {k === "all" ? "All" : k === "replay" ? "Replays" : "Live tickets"}
            </Button>
          ))}
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="font-medium">Couldn&apos;t load the journal</p>
          <p className="text-xs text-muted-foreground">{error}</p>
          <Button variant="secondary" size="sm" className="mt-2" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      ) : !rows ? (
        <div className="space-y-4" aria-hidden>
          <Skeleton className="h-24 w-full rounded-lg" />
          <Skeleton className="h-96 w-full rounded-lg" />
        </div>
      ) : rows.length === 0 ? (
        <div className="flex min-h-[240px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-8 text-center">
          <p className="text-sm font-medium">Nothing journaled yet</p>
          <p className="max-w-prose text-sm text-muted-foreground">Analyse a ticket on the desk, or run a replay to score the forecasts the system would have made over past closed-market windows.</p>
        </div>
      ) : (
        <>
          <Section title={`${rows.length} most recent`} subtitle={`${matured.length} scored · ${rows.length - matured.length} still open${rows.length === LIMIT ? " · older rows are in the API and the CLI" : ""}`}>
            <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
              <div className="grid grid-cols-2 gap-2">
                <Stat label="Scored" value={String(matured.length)} hint="horizon passed, outcome recorded" />
                <Stat label="Inside the p5–p95 band" value={matured.length ? fmtPct((inside / matured.length) * 100, 1, false) : "—"} hint="90% if the distributions are honest" />
                <Stat label="Tokens" value={String(new Set(rows.map((r) => r.ticker)).size)} />
                <Stat label="Live tickets" value={String(rows.filter((r) => r.kind === "ticket").length)} hint="analyses a person asked for" />
              </div>
              <figure aria-label="Predicted median against realised return">
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
                      formatter={(v, name) => [`${Number(v).toFixed(2)}%`, String(name) === "x" ? "predicted median" : "realised"]}
                    />
                    <Scatter data={points} fill="var(--chart-1)" fillOpacity={0.55} isAnimationActive={false} />
                  </ScatterChart>
                </ResponsiveContainer>
                <figcaption className="mt-1 text-xs text-muted-foreground">
                  Predicted median (horizontal) against what happened (vertical). A useful forecast tilts along the diagonal; a useless one is a cloud.
                  {outside > 0 ? ` ${outside} point${outside === 1 ? "" : "s"} fall outside this view.` : ""}
                </figcaption>
              </figure>
            </div>
          </Section>

          <Section title="The journal" subtitle="Newest first. The band is the analog distribution at the moment of the call.">
            <div className="overflow-x-auto">
              <Table className="min-w-[820px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Trade</TableHead>
                    <TableHead className="text-right">Horizon</TableHead>
                    <TableHead className="text-right">p5 – p50 – p95</TableHead>
                    <TableHead className="text-right">Realised</TableHead>
                    <TableHead className="text-right">Verdict</TableHead>
                    <TableHead className="text-right">Inputs</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => {
                    const band = r.p5 != null && r.p95 != null;
                    const insideBand = band && r.ret_pct != null && r.ret_pct >= r.p5! && r.ret_pct <= r.p95!;
                    return (
                      <TableRow key={r.id}>
                        <TableCell className="whitespace-nowrap">
                          {fmtTime(r.as_of)}
                          <span className="block text-xs text-muted-foreground">{r.kind === "replay" ? "replay" : "live ticket"}</span>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          <span className="font-medium">{r.ticker}</span> {r.side}
                          <span className="block text-xs text-muted-foreground">
                            {fmtUsd(r.notional)} · {r.analog_n ?? 0} analogs
                          </span>
                        </TableCell>
                        <TableCell className="tabular text-right">{r.horizon_h.toFixed(0)}h</TableCell>
                        <TableCell className="tabular text-right whitespace-nowrap">
                          {band ? (
                            <>
                              {fmtPct(r.p5)} · {fmtPct(r.p50)} · {fmtPct(r.p95)}
                            </>
                          ) : (
                            <span className="text-muted-foreground">refused: too few analogs</span>
                          )}
                        </TableCell>
                        <TableCell className="tabular text-right">
                          {r.ret_pct == null ? (
                            <span className="text-muted-foreground">open</span>
                          ) : (
                            <span className={insideBand ? "" : "text-status-warning"}>{fmtPct(r.ret_pct)}</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {r.verdict ? (
                            <Pill tone={r.verdict === "GO" ? "good" : r.verdict === "NO_GO" ? "critical" : r.verdict === "HEDGE" ? "info" : "warning"}>{r.verdict.replace("_", " ")}</Pill>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs text-muted-foreground">{r.snapshot_hash}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
