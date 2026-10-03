"use client";

import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";
import type { Report } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import { fmtHoursL, type Lang, t as tLabel, tr } from "@/lib/i18n";

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
function ticketText(report: Report, symbol: string, lang: Lang): string {
  const L = tr(lang);
  const t = report.ticket;
  const v = report.verdict;
  const size = v.recommended_notional ?? t.notional_quote;
  const lines = [
    `${t.side === "long" ? L("BUY", "买入") : L("SELL", "卖出")} ${symbol} · ${fmtUsd(size)} USDT`,
    L(`Hold ${fmtHoursL(report.horizon_h, lang)} (${report.primary_horizon})`, `持有 ${fmtHoursL(report.horizon_h, lang)}（${report.primary_horizon}）`),
  ];
  if (t.stop_price) lines.push(L(`Stop ${t.stop_price}`, `止损 ${t.stop_price}`));
  if (v.hedge_ratio) lines.push(L(`Hedge ${(v.hedge_ratio * 100).toFixed(0)}% with the perp`, `用永续合约对冲 ${(v.hedge_ratio * 100).toFixed(0)}%`));
  if (size !== t.notional_quote) lines.push(
      lang === "zh"
        ? `你要求 ${fmtUsd(t.notional_quote)}；被${report.sizing.binding_cap ? tLabel("zh", "cap", report.sizing.binding_cap) : "限制性"}上限压低。`
        : `Asked for ${fmtUsd(t.notional_quote)}; the ${report.sizing.binding_cap?.replace("_", " ") ?? "binding"} cap cut it.`,
    );
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
export function ActOnIt({ report, lang = "en" }: { report: Report; lang?: Lang }) {
  const L = tr(lang);
  const [copied, setCopied] = useState(false);
  const symbol = spotSymbol(report);
  if (!symbol) return null;
  const refused = report.verdict.verdict === "NO_GO";

  async function copy() {
    const text = ticketText(report, symbol as string, lang);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt(L("Copy this ticket", "复制此下单单据"), text);
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
        {L(`Open ${symbol} on Bitget`, `在 Bitget 打开 ${symbol}`)}
      </a>
      {refused ? (
        <span className="text-[13px] text-muted-foreground">{L("The desk says no to this one, so it will not hand you the ticket.", "系统对这一笔的结论是不建议做，所以不会给你下单单据。")}</span>
      ) : (
        <button
          type="button"
          onClick={() => void copy()}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-status-good" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
          {copied ? L("Ticket copied", "单据已复制") : L("Copy the sized ticket", "复制按建议仓位生成的单据")}
        </button>
      )}
      <span className="text-[13px] text-muted-foreground">{L("Nightwatch never places an order.", "Nightwatch 从不替你下单。")}</span>
      {!refused ? <EntryPlanNote report={report} symbol={symbol} lang={lang} /> : null}
    </div>
  );
}

/** A prompt for an AI tool with Bitget Agent Hub installed, in dry-run: the model can
 *  preview the order through Bitget's own tools, and the human confirms. */
function agentHubPrompt(report: Report, symbol: string, lang: Lang): string | null {
  const L = tr(lang);
  const p = report.entry_plan;
  if (!p || !p.slices || p.limit_price == null || p.slice_notional == null) return null;
  const slices = p.slices === 1 ? L("one order", "一笔订单") : L(`${p.slices} equal slices`, `${p.slices} 等份分批`);
  const sized = report.forecast_id != null && report.forecast_id > 0 ? ` #${report.forecast_id}` : "";
  if (lang === "zh") {
    return (
      `请用 Bitget Agent Hub 的模拟（dry-run）模式，预览一笔 ${symbol} 的${p.side === "buy" ? "买入" : "卖出"}限价单：${Math.round(p.slice_notional).toLocaleString()} USDT，` +
      `价格 ${p.limit_price}，${slices}。先给我看预览，我确认之前不要下任何单。` +
      `（仓位由 Nightwatch${sized} 给出。）`
    );
  }
  return (
    `Using Bitget Agent Hub in dry-run mode, preview a limit ${p.side} of ${Math.round(p.slice_notional).toLocaleString()} USDT on ${symbol} ` +
    `at ${p.limit_price}, as ${slices}. Show me the preview and do not place anything until I confirm. ` +
    `(Sized by Nightwatch${sized}.)`
  );
}

/** Getting in: the cost of the whole size at once, and the slices that keep each one
 *  inside the cost budget when it does not fit. */
function EntryPlanNote({ report, symbol, lang }: { report: Report; symbol: string; lang: Lang }) {
  const L = tr(lang);
  const [copied, setCopied] = useState(false);
  const p = report.entry_plan;
  if (!p) return null;
  const prompt = agentHubPrompt(report, symbol, lang);
  let line: string;
  const buying = p.side === "buy";
  if (p.slices === 1) {
    line = L(
      `Getting in: ${buying ? "buying" : "selling"} the whole ${fmtUsd(p.notional)} USDT at once costs ${p.full_cost_bps?.toFixed(0)} bps, inside the ${p.budget_bps.toFixed(0)} bps budget - one limit order at ${p.limit_price} fills it.`,
      `入场：一次性${buying ? "买入" : "卖出"}全部 ${fmtUsd(p.notional)} USDT 的成本为 ${p.full_cost_bps?.toFixed(0)} bps，在 ${p.budget_bps.toFixed(0)} bps 的预算之内——在 ${p.limit_price} 挂一张限价单即可成交。`,
    );
  } else if (p.slices && p.slice_notional != null) {
    line = L(
      `Getting in: all ${fmtUsd(p.notional)} USDT at once would cost ${p.full_cost_bps != null ? `${p.full_cost_bps.toFixed(0)} bps` : "more than the book holds"}. In ${p.slices} slices of ${fmtUsd(p.slice_notional)} USDT, each costs about ${p.slice_cost_bps?.toFixed(0)} bps with a limit at ${p.limit_price} - ${p.note}.`,
      `入场：一次性买入全部 ${fmtUsd(p.notional)} USDT 的成本${p.full_cost_bps != null ? `为 ${p.full_cost_bps.toFixed(0)} bps` : "超出盘口所能承接的量"}。分 ${p.slices} 笔、每笔 ${fmtUsd(p.slice_notional)} USDT，限价 ${p.limit_price}，每笔成本约 ${p.slice_cost_bps?.toFixed(0)} bps——${p.note}。`,
    );
  } else {
    line = L(`Getting in: ${p.note}.`, `入场：${p.note}。`);
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
          {copied ? L("Prompt copied", "提示词已复制") : L("Copy a dry-run prompt for Bitget Agent Hub", "复制 Bitget Agent Hub 的模拟（dry-run）提示词")}
        </button>
      ) : null}
    </div>
  );
}
