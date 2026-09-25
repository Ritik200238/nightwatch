"use client";

import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";
import type { Report } from "@/lib/api";
import { fmtHours, fmtUsd } from "@/lib/format";

/** The spot market this report is about, as Bitget names it.
 *
 *  Taken from the order-book source rather than guessed from the ticker, because the
 *  token symbol is the exchange's business and rTSLA is not TSLA.
 */
function spotSymbol(report: Report): string | null {
  const book = report.sources.find((s) => s.kind === "orderbook");
  return (book?.symbol as string | undefined) ?? null;
}

/** The verdict as something you could hand to a broker.
 *
 *  It carries the size the desk arrived at, not the one that was asked for, because that
 *  difference is the entire output of the thing.
 */
function ticketText(report: Report, symbol: string): string {
  const t = report.ticket;
  const v = report.verdict;
  const size = v.recommended_notional ?? t.notional_quote;
  const lines = [
    `${t.side === "long" ? "BUY" : "SELL"} ${symbol} · ${fmtUsd(size)} USDT`,
    `Hold ${fmtHours(report.horizon_h)} (${report.primary_horizon})`,
  ];
  if (t.stop_price) lines.push(`Stop ${t.stop_price}`);
  if (v.hedge_ratio) lines.push(`Hedge ${(v.hedge_ratio * 100).toFixed(0)}% with the perp`);
  if (size !== t.notional_quote) lines.push(`Asked for ${fmtUsd(t.notional_quote)}; the ${report.sizing.binding_cap?.replace("_", " ") ?? "binding"} cap cut it.`);
  if (report.forecast_id != null) lines.push(`Nightwatch #${report.forecast_id} · ${typeof window !== "undefined" ? `${window.location.origin}/r/${report.forecast_id}` : ""}`);
  return lines.join("\n");
}

/** Where a verdict ends.
 *
 *  Nightwatch does not place orders and is not going to, so this is the honest end of the
 *  loop: the market open in a tab, and the sized ticket on the clipboard. When the answer
 *  is no, the ticket is not offered - handing someone a one-click path to the trade you
 *  just told them not to make is not a courtesy.
 */
export function ActOnIt({ report }: { report: Report }) {
  const [copied, setCopied] = useState(false);
  const symbol = spotSymbol(report);
  if (!symbol) return null;
  const refused = report.verdict.verdict === "NO_GO";

  async function copy() {
    const text = ticketText(report, symbol as string);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy this ticket", text);
    }
  }

  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <a
        href={`https://www.bitget.com/spot/${symbol}`}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <ExternalLink className="h-3.5 w-3.5" aria-hidden />
        Open {symbol} on Bitget
      </a>
      {refused ? (
        <span className="text-xs text-muted-foreground">The desk says no to this one, so it will not hand you the ticket.</span>
      ) : (
        <button
          type="button"
          onClick={() => void copy()}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-status-good" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
          {copied ? "Ticket copied" : "Copy the sized ticket"}
        </button>
      )}
      <span className="text-xs text-muted-foreground">Nightwatch never places an order.</span>
      {!refused ? <EntryPlanNote report={report} symbol={symbol} /> : null}
    </div>
  );
}

/** A prompt for an AI tool with Bitget Agent Hub installed, in dry-run: the model can
 *  preview the order through Bitget's own tools, and the human confirms. */
function agentHubPrompt(report: Report, symbol: string): string | null {
  const p = report.entry_plan;
  if (!p || !p.slices || p.limit_price == null || p.slice_notional == null) return null;
  const slices = p.slices === 1 ? "one order" : `${p.slices} equal slices`;
  return (
    `Using Bitget Agent Hub in dry-run mode, preview a limit ${p.side} of ${Math.round(p.slice_notional).toLocaleString()} USDT on ${symbol} ` +
    `at ${p.limit_price}, as ${slices}. Show me the preview and do not place anything until I confirm. ` +
    `(Sized by Nightwatch${report.forecast_id != null && report.forecast_id > 0 ? ` #${report.forecast_id}` : ""}.)`
  );
}

/** Getting in: the cost of the whole size at once, and the slices that keep each one
 *  inside the cost budget when it does not fit. */
function EntryPlanNote({ report, symbol }: { report: Report; symbol: string }) {
  const [copied, setCopied] = useState(false);
  const p = report.entry_plan;
  if (!p) return null;
  const prompt = agentHubPrompt(report, symbol);
  let line: string;
  if (p.slices === 1) {
    line = `Getting in: ${p.side === "buy" ? "buying" : "selling"} the whole ${fmtUsd(p.notional)} USDT at once costs ${p.full_cost_bps?.toFixed(0)} bps, inside the ${p.budget_bps.toFixed(0)} bps budget - one limit order at ${p.limit_price} fills it.`;
  } else if (p.slices && p.slice_notional != null) {
    line = `Getting in: all ${fmtUsd(p.notional)} USDT at once would cost ${p.full_cost_bps != null ? `${p.full_cost_bps.toFixed(0)} bps` : "more than the book holds"}. In ${p.slices} slices of ${fmtUsd(p.slice_notional)} USDT, each costs about ${p.slice_cost_bps?.toFixed(0)} bps with a limit at ${p.limit_price} - ${p.note}.`;
  } else {
    line = `Getting in: ${p.note}.`;
  }
  return (
    <div className="mt-1 w-full rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
      <p>{line}</p>
      {prompt ? (
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(prompt).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            });
          }}
          className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          title={prompt}
        >
          {copied ? <Check className="h-3 w-3 text-status-good" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
          {copied ? "Prompt copied" : "Copy a dry-run prompt for Bitget Agent Hub"}
        </button>
      ) : null}
    </div>
  );
}
