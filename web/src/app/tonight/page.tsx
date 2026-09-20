"use client";

import { AlertTriangle, Clock, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { OpenPositions, useOpenPositions } from "@/components/desk/open-positions";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api, type TonightReport, type UniverseEntry } from "@/lib/api";
import { fmtBps, fmtPct, fmtTime, fmtUsd } from "@/lib/format";

/** What each flag is, in the words a person would use. Order is the order they are read. */
const FLAG_LABEL: Record<string, string> = {
  earnings_in_window: "earnings tonight",
  fomc_in_window: "FOMC tonight",
  fresh_filing: "filing just landed",
  cannot_exit: "cannot exit now",
  thin_book: "book often too thin",
  hostile_regime: "hostile regime",
  wide_tail: "wide overnight band",
};

const FLAG_TONE: Record<string, "critical" | "warning" | "muted"> = {
  earnings_in_window: "critical",
  fomc_in_window: "critical",
  cannot_exit: "critical",
  fresh_filing: "warning",
  thin_book: "warning",
  hostile_regime: "warning",
  wide_tail: "muted",
};

export default function TonightPage() {
  const { positions, setPositions } = useOpenPositions();
  const [universe, setUniverse] = useState<UniverseEntry[] | null>(null);
  const [report, setReport] = useState<TonightReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [equity, setEquity] = useState<number | null>(200000);

  useEffect(() => {
    void api.universe(true).then(setUniverse).catch(() => setUniverse([]));
    try {
      const raw = window.localStorage.getItem("nightwatch.equity");
      if (raw) setEquity(Number(raw) || null);
    } catch {
      /* a blocked store just means the default */
    }
  }, []);

  const run = useCallback(async () => {
    if (!positions.length) {
      setReport(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setReport(await api.tonight(positions, equity));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not read the book tonight.");
    } finally {
      setBusy(false);
    }
  }, [positions, equity]);

  const worst = report?.items?.[0] ?? null;
  const needAttention = (report?.items ?? []).filter((i) => i.flags.some((f) => f !== "wide_tail"));

  return (
    <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
      <aside className="min-w-0 space-y-4 lg:sticky lg:top-6 lg:self-start">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
            <Moon className="h-4 w-4" aria-hidden /> Tonight
          </h1>
          <p className="text-sm text-muted-foreground">
            The desk answers what you ask it. This is the question you would not have thought to ask: of what you are already holding, which position needs you before the market opens
            again.
          </p>
        </div>
        {universe ? <OpenPositions universe={universe} positions={positions} onChange={setPositions} /> : <Skeleton className="h-32 w-full" />}
        <Button onClick={() => void run()} disabled={busy || !positions.length} className="w-full">
          {busy ? "Reading the book…" : positions.length ? `Watch these ${positions.length}` : "Add what you hold"}
        </Button>
        <p className="text-xs text-muted-foreground">
          Every position gets the same full analysis the desk would give if you asked about it directly — the analogs over tonight&apos;s window, the presets at the size you hold, and
          the live book walked for that size. That takes a couple of seconds each.
        </p>
      </aside>

      <section aria-live="polite" aria-busy={busy} className="min-w-0 space-y-4">
        {error ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
            <p className="font-medium">Couldn&apos;t read the book</p>
            <p className="text-xs text-muted-foreground">{error}</p>
          </div>
        ) : null}

        {busy && !report ? (
          <>
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </>
        ) : null}

        {!report && !busy ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-8 text-center">
            <Moon className="h-6 w-6 text-muted-foreground" aria-hidden />
            <p className="font-medium">Nothing on the watch yet</p>
            <p className="max-w-md text-sm text-muted-foreground">
              Add the positions you are carrying and this page will tell you which of them has earnings landing overnight, which one the book will not absorb at three in the morning,
              and which one carries the widest tail between now and the open.
            </p>
            <p className="text-sm text-muted-foreground">
              Or{" "}
              <Link href="/" className="underline underline-offset-2">
                stress-test something new
              </Link>{" "}
              on the desk.
            </p>
          </div>
        ) : null}

        {report ? (
          <>
            <Section
              title={report.market_is_open ? "Until the close" : "Until the next open"}
              subtitle={
                report.window_end
                  ? `${report.hours.toFixed(0)} hours, to ${fmtTime(report.window_end)}. ${report.market_is_open ? "The regular session is open, so this is what you would be carrying into the close." : "Everything below is measured over exactly this window."}`
                  : undefined
              }
              action={
                <Pill tone={needAttention.length ? "warning" : "good"}>
                  {report.market_is_open ? <Sun className="mr-1 h-3 w-3" aria-hidden /> : <Clock className="mr-1 h-3 w-3" aria-hidden />}
                  {needAttention.length ? `${needAttention.length} want a look` : "nothing pressing"}
                </Pill>
              }
            >
              <p className="text-lg font-medium leading-snug">{report.summary}</p>
              <div className="mt-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
                <Stat label="Positions" value={String(report.items.length)} hint={report.note || "all judged"} />
                <Stat label="Gross held" value={fmtUsd(report.gross_quote)} hint="USDT across the book" />
                <Stat
                  label="Worst tonight"
                  value={worst?.p5_quote != null ? `−${fmtUsd(Math.abs(worst.p5_quote))}` : "—"}
                  hint={worst ? `${worst.ticker}, at the calibrated 5th percentile` : undefined}
                  tone="warning"
                />
                <Stat
                  label="Added up"
                  value={`−${fmtUsd(report.items.reduce((a, i) => a + Math.abs(i.p5_quote ?? 0), 0))}`}
                  hint="if every bad case landed at once, which they would not"
                />
              </div>
            </Section>

            {report.items.map((item) => (
              <Section
                key={`${item.ticker}-${item.side}`}
                collapsible
                summary={`${item.headline}`}
                title={`${item.ticker} ${item.side} · ${fmtUsd(item.notional_quote)} USDT`}
                subtitle="What this position looks like over tonight's window."
                action={
                  item.flags.length ? (
                    <span className="flex flex-wrap gap-1">
                      {item.flags.map((f) => (
                        <Pill key={f} tone={FLAG_TONE[f] ?? "muted"}>
                          {FLAG_LABEL[f] ?? f.replace(/_/g, " ")}
                        </Pill>
                      ))}
                    </span>
                  ) : (
                    <Pill tone="good">quiet</Pill>
                  )
                }
              >
                <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                  <Stat
                    label="Bad case tonight"
                    value={item.p5_quote != null ? `−${fmtUsd(Math.abs(item.p5_quote))}` : "—"}
                    hint={item.p5_pct != null ? `${fmtPct(item.p5_pct, 1)} of the position, calibrated` : "no distribution"}
                    tone="warning"
                  />
                  <Stat
                    label="Worst preset"
                    value={item.worst_preset_quote != null ? `−${fmtUsd(Math.abs(item.worst_preset_quote))}` : "—"}
                    hint={item.worst_preset ?? undefined}
                    tone="critical"
                  />
                  <Stat
                    label="Getting out now"
                    value={item.exit_cost_bps != null ? fmtBps(item.exit_cost_bps) : item.exit_fills ? "—" : "will not fill"}
                    hint={item.exit_fills ? "on the live book" : "the book cannot absorb this size"}
                    tone={item.exit_fills ? undefined : "critical"}
                  />
                  <Stat
                    label="Book at these hours"
                    value={item.thin_share != null ? `${(item.thin_share * 100).toFixed(0)}% too thin` : "—"}
                    hint="share of recorded snapshots that could not take this size"
                    tone={item.thin_share != null && item.thin_share >= 0.2 ? "warning" : undefined}
                  />
                </div>
                {item.events.length ? (
                  <div className="mt-3 rounded-lg border border-status-warning/40 bg-status-warning/5 p-3 text-sm">
                    <p className="mb-1 flex items-center gap-2 font-medium">
                      <AlertTriangle className="h-4 w-4 text-status-warning" aria-hidden /> Landing inside the window
                    </p>
                    <ul className="space-y-1 text-muted-foreground">
                      {item.events.map((e) => (
                        <li key={e}>{e}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <p className="mt-3 text-xs text-muted-foreground">
                  Regime: {item.regime_label ?? "unknown"}.{" "}
                  <Link href="/" className="underline underline-offset-2">
                    Stress-test a change to this position
                  </Link>{" "}
                  on the desk.
                </p>
              </Section>
            ))}
          </>
        ) : null}
      </section>
    </div>
  );
}
