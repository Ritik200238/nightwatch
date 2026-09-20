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
    </div>
  );
}
