"use client";

import { useEffect, useState } from "react";
import { Chat } from "@/components/desk/chat";
import { OpenPositions, useOpenPositions } from "@/components/desk/open-positions";
import { Sources } from "@/components/desk/sources";
import { TicketForm } from "@/components/desk/ticket-form";
import { ReportView } from "@/components/report/report-view";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, api, type Report, type TicketInput, type UniverseEntry } from "@/lib/api";

export default function DeskPage() {
  const [universe, setUniverse] = useState<UniverseEntry[] | null>(null);
  const [universeError, setUniverseError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTicket, setLastTicket] = useState<TicketInput | null>(null);
  const [equity, setEquity] = useState<number | null>(200000);
  const { positions, setPositions } = useOpenPositions();

  async function loadUniverse() {
    setUniverseError(null);
    try {
      setUniverse(await api.universe(true));
    } catch (e) {
      setUniverseError(e instanceof Error ? e.message : "Could not load the token list.");
    }
  }

  useEffect(() => {
    void loadUniverse();
  }, []);

  async function run(ticket: TicketInput) {
    setBusy(true);
    setError(null);
    setLastTicket(ticket);
    setEquity(ticket.account_equity_quote ?? null);
    try {
      // The book travels with the ticket so the report can judge both.
      setReport(await api.analyze({ ...ticket, open_positions: positions }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The analysis failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    // min-w-0 on both columns: a grid track is auto-sized by default, so one wide table
    // in the report stretches the whole column past the viewport and takes the sidebar
    // with it. With it, the tables' own overflow-x-auto wrappers do the scrolling.
    <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
      <aside className="min-w-0 space-y-4 lg:sticky lg:top-6 lg:self-start">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Stress-test a trade</h1>
          <p className="text-sm text-muted-foreground">Tokenized US stocks trade 24/7. Find out what past moments like now did, what could go wrong, and whether you can get out — before you place it.</p>
        </div>
        <Tabs defaultValue="form">
          <TabsList className="w-full">
            <TabsTrigger value="form" className="flex-1">
              Ticket
            </TabsTrigger>
            <TabsTrigger value="chat" className="flex-1">
              Chat
            </TabsTrigger>
          </TabsList>
          <TabsContent value="form" className="pt-3">
            {universe ? (
              <div className="space-y-5">
                <TicketForm universe={universe} busy={busy} onSubmit={run} />
                <div className="border-t border-border pt-4">
                  <OpenPositions universe={universe} positions={positions} onChange={setPositions} />
                </div>
                <div className="border-t border-border pt-4">
                  <Sources />
                </div>
              </div>
            ) : universeError ? (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
                <p className="font-medium">Couldn&apos;t load the token list</p>
                <p className="text-xs text-muted-foreground">{universeError}</p>
                <Button variant="secondary" size="sm" className="mt-2" onClick={() => void loadUniverse()}>
                  Try again
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            )}
          </TabsContent>
          <TabsContent value="chat" className="pt-3">
            <Chat accountEquity={equity} busy={busy} setBusy={setBusy} onReport={setReport} />
          </TabsContent>
        </Tabs>
      </aside>

      <section className="min-w-0" aria-live="polite" aria-busy={busy}>
        {busy && !report ? <ReportSkeleton /> : null}
        {error ? (
          <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
            <p className="font-medium">Couldn&apos;t run the analysis</p>
            <p className="text-xs text-muted-foreground">{error}</p>
            {lastTicket ? (
              <Button variant="secondary" size="sm" className="mt-2" onClick={() => void run(lastTicket)} disabled={busy}>
                Try again
              </Button>
            ) : null}
          </div>
        ) : null}
        {report ? (
          <div className={busy ? "opacity-60 transition-opacity" : ""}>
            <ReportView report={report} />
          </div>
        ) : !busy && !error ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-8 text-center">
            <p className="text-sm font-medium">No report yet</p>
            <p className="max-w-prose text-sm text-muted-foreground">Fill in the ticket or describe the trade in chat. You will get a sized verdict, the distribution of similar past moments, calibrated stress tests and the real cost of exiting.</p>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function ReportSkeleton() {
  return (
    <div className="space-y-4" aria-hidden>
      <Skeleton className="h-36 w-full rounded-lg" />
      <Skeleton className="h-28 w-full rounded-lg" />
      <Skeleton className="h-72 w-full rounded-lg" />
      <Skeleton className="h-64 w-full rounded-lg" />
    </div>
  );
}
