"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type MissesResponse, type VerifyResponse } from "@/lib/api";
import { fmtPct, fmtTime, fmtUsd } from "@/lib/format";

/** Mistakes found in the desk itself, newest first. Each one changed a number a trader
 *  was shown; the fix is in the repository's history and the evidence in the notes. */
const FOUND: { when: string; what: string; fix: string; open?: boolean }[] = [
  {
    when: "29 Sep",
    what: "Shorts were sized on the wrong side of history. The one-in-twenty loss was read from the stock falling, which is a short's gain, so the gate, the size cap and the leverage check all judged shorts on their good nights.",
    fix: "A short is now sized on the stock rising: the calibrated 95th percentile, turned over. The report says which way hurts.",
  },
  {
    when: "29 Sep",
    what: "That upper tail is still slightly optimistic on quiet nights: out of sample it is breached 5.8% of the time against 5%, and 6.8% on the narrowest third of forecasts.",
    fix: "Two corrections were measured and neither beat the current tail on both breaches and pinball loss, so neither shipped. Open.",
    open: true,
  },
  {
    when: "29 Sep",
    what: "Bitget's US-stock data (analyst ratings, insider trades, the live stock price) was silently missing from every live report. Bitget's server refused new sessions over this server's IPv4 address and the report just left the section out.",
    fix: "The API now reaches it over IPv6; the data-sources panel shows how many tokens currently have it.",
  },
  {
    when: "29 Sep",
    what: "\"Over the weekend\" asked on a weekday was run as a six-day hold to Monday, longer than any hold the desk has scored, and the reply did not say so.",
    fix: "The report now says which weekend it measured and gives what past Friday-to-Monday weekends did for that stock.",
  },
  {
    when: "29 Sep",
    what: "The written docs quoted study numbers the live Studies page no longer supported: \"not one of 24 tokens\" had become one, and a t-statistic had changed sign.",
    fix: "The docs quote the live run, and a script fails when they drift apart again.",
  },
  {
    when: "29 Sep",
    what: "A Chinese trader who wrote 我想周末拿点特斯拉 (hold some Tesla over the weekend) was asked \"long or short?\" on every turn and never got an answer.",
    fix: "拿, 入手, 上车 and 抄底 read as a long, and a clarifying question says back what it already has.",
  },
  {
    when: "28 Sep",
    what: "Shorts were never stress-tested. Every preset was a fall, so a TSLA short's \"1-in-100 gap\" showed as a +7.4% gain.",
    fix: "Presets come from the tail that hurts the position; the same short now shows −6.8%.",
  },
  {
    when: "Earlier",
    what: "The raw history's tails were too narrow: 8.5% of outcomes fell below the stated one-in-twenty line instead of 5%.",
    fix: "Every tail is widened by factors fitted only on forecasts that had already matured; out of sample it is back to 5%.",
  },
  {
    when: "Earlier",
    what: "One tail factor for every holding period hid two opposite errors: overnight tails too narrow, weekend tails about twice too wide, so weekend positions were being cut by 43% for nothing.",
    fix: "Each holding period has its own factor.",
  },
];

export default function WrongPage() {
  const [misses, setMisses] = useState<MissesResponse | null>(null);
  const [chain, setChain] = useState<VerifyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.misses().then(setMisses).catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load the misses."));
    api.verify().then(setChain).catch(() => setChain(null));
  }, []);

  const live = misses?.totals.ticket;
  const replay = misses?.totals.replay;

  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-lg font-semibold tracking-tight">What we got wrong</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          A risk tool that only shows its hits is asking to be trusted. This page shows the other half: every live verdict where the loss went past the line the desk
          said it would pass only one time in twenty, the mistakes we found in the desk itself, and a check anyone can run that no past verdict was edited afterwards.
        </p>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="font-medium">Couldn&apos;t load the misses</p>
          <p className="text-xs text-muted-foreground">{error}</p>
        </div>
      ) : null}

      <Section
        title="Live verdicts that went past their line"
        subtitle="Scored exactly as the calibration page scores them: the tail that was in force when the verdict was given, fitted only on forecasts that had already matured. If the desk is honest, about 5% should miss."
      >
        {!misses && !error ? (
          <Skeleton className="h-24 w-full" />
        ) : misses ? (
          <>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <Stat label="Live verdicts scored" value={live ? live.scored.toLocaleString() : "0"} hint="given to real users, then scored when the hold ended" />
              <Stat
                label="Went past the line"
                value={live ? `${live.missed} (${fmtPct(live.rate * 100, 1, false)})` : "—"}
                hint="target about 5%"
                tone={live && live.rate > 0.075 ? "critical" : undefined}
              />
              <Stat label="Replayed forecasts scored" value={replay ? replay.scored.toLocaleString() : "0"} hint="the past, run as if live" />
              <Stat label="Went past the line" value={replay ? `${replay.missed} (${fmtPct(replay.rate * 100, 1, false)})` : "—"} hint="target about 5%" />
            </div>
            {misses.misses.length ? (
              <div className="mt-4 overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>When</TableHead>
                      <TableHead>Trade</TableHead>
                      <TableHead>Verdict</TableHead>
                      <TableHead className="text-right">Line stated</TableHead>
                      <TableHead className="text-right">What happened</TableHead>
                      <TableHead className="text-right">Lost past the line</TableHead>
                      <TableHead>Receipt</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {misses.misses.map((m) => (
                      <TableRow key={m.id}>
                        <TableCell className="whitespace-nowrap">{fmtTime(m.as_of)}</TableCell>
                        <TableCell className="whitespace-nowrap">
                          {m.side} {fmtUsd(m.notional)} {m.ticker} · {m.horizon_h.toFixed(0)}h
                        </TableCell>
                        <TableCell>{(m.verdict ?? "—").replace("_", " ")}</TableCell>
                        <TableCell className="tabular text-right">{fmtPct(m.stated_p5_pct, 1)}</TableCell>
                        <TableCell className="tabular text-right font-medium">{fmtPct(m.outcome_pct, 1)}</TableCell>
                        <TableCell className="tabular text-right">{fmtUsd(Math.abs(m.beyond_quote))} USDT</TableCell>
                        <TableCell className="font-mono text-xs">
                          {m.receipt ? (
                            <a href={`/api/verify/${m.id}`} target="_blank" rel="noreferrer" className="underline underline-offset-2" title={m.receipt}>
                              {m.receipt.slice(0, 10)}…
                            </a>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">No live verdict has gone past its line yet.</p>
            )}
            <p className="mt-3 text-xs text-muted-foreground">
              Most live verdicts come from people trying the desk, so many are small test trades. They are scored all the same.
            </p>
          </>
        ) : null}
      </Section>

      <Section
        title="Check that no verdict was changed afterwards"
        subtitle="Every live verdict gets a receipt when it is given: a SHA-256 over what was asked and what the desk said, chained to the receipt before it. Change or delete any past verdict and every receipt after it stops matching."
        action={chain ? <Pill tone={chain.ok ? "good" : "critical"}>{chain.ok ? "chain intact" : "chain broken"}</Pill> : undefined}
      >
        {chain ? (
          <div className="space-y-2 text-sm">
            <p className="flex items-center gap-2">
              {chain.ok ? <CheckCircle2 className="h-4 w-4 text-status-good" aria-hidden /> : <XCircle className="h-4 w-4 text-destructive" aria-hidden />}
              {chain.ok
                ? `Recomputed just now: all ${chain.checked.toLocaleString()} receipts match the verdicts they cover.`
                : `Recomputed just now: receipt ${chain.first_break?.seq} breaks - ${chain.first_break?.reason}.`}
            </p>
            <p className="break-all font-mono text-xs text-muted-foreground">Latest receipt: {chain.head}</p>
            <p className="text-xs text-muted-foreground">
              Run it yourself: <a href="/api/verify" target="_blank" rel="noreferrer" className="underline underline-offset-2">/api/verify</a>, or{" "}
              <code>/api/verify/&lt;id&gt;</code> for one verdict; every report shows its own receipt. What this proves and what it does not: the chain shows nothing
              was changed after its receipt was written. It is kept by the same server that writes the verdicts, so it cannot prove the whole chain was never rebuilt,
              and verdicts given before 29 September were chained that day. Replayed forecasts are not chained - they are rebuilt from the code and stored prices
              whenever the replay runs, and anyone can rebuild them the same way.
            </p>
          </div>
        ) : (
          <Skeleton className="h-16 w-full" />
        )}
      </Section>

      <Section title="Mistakes we found in the desk itself" subtitle="Each one changed a number a trader was shown. Newest first; the open one is still open.">
        <ul className="space-y-3">
          {FOUND.map((f) => (
            <li key={f.what} className="rounded-lg border border-border p-3 text-sm">
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                {f.when}
                {f.open ? <Pill tone="warning">open</Pill> : <Pill tone="good">fixed</Pill>}
              </p>
              <p className="mt-1">{f.what}</p>
              <p className="mt-1 text-muted-foreground">{f.fix}</p>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted-foreground">
          The questions we asked about the method itself, and the five that came back &ldquo;no&rdquo;, are on the{" "}
          <Link href="/studies" className="underline underline-offset-2">
            Studies
          </Link>{" "}
          page.
        </p>
      </Section>
    </div>
  );
}
