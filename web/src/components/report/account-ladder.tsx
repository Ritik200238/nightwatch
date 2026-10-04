"use client";

import type { Report, TicketInput } from "@/lib/api";
import { type Lang, tr } from "@/lib/i18n";

const VERDICT_ZH: Record<string, string> = { GO: "可以做", REDUCE_TO: "减仓", HEDGE: "对冲", REVIEW: "复核", NO_GO: "不建议做" };

function k(x: number): string {
  return x >= 1000 && x % 1000 === 0 ? `${(x / 1000).toLocaleString("en-US")}k` : x.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function tone(v: string): string {
  if (v === "GO") return "text-status-good";
  if (v === "NO_GO") return "text-status-critical";
  return "text-status-warning";
}

/** A REVIEW that only waits for the account size, answered anyway: the same trade judged at a
 *  few account sizes by the same rules, the smallest account that makes it a GO, and one click
 *  to re-run it at any of them. The verdict on the report stays REVIEW. */
export function AccountLadder({ report, lang = "en", onRerun }: { report: Report; lang?: Lang; onRerun?: (patch: Partial<TicketInput>) => void }) {
  const L = tr(lang);
  const sens = report.sensitivity;
  const ladder = sens?.account_ladder ?? [];
  if (!ladder.length || report.ticket.account_equity_quote) return null;
  const asked = report.ticket.notional_quote;
  const edge = sens?.min_go_equity ?? null;
  const top = ladder[ladder.length - 1];
  const end =
    edge != null
      ? L(`It is a GO at ${asked.toLocaleString("en-US")} from an account of about ${Math.round(edge).toLocaleString("en-US")} USDT.`,
          `账户约 ${Math.round(edge).toLocaleString("en-US")} USDT 起，${asked.toLocaleString("en-US")} USDT 即可通过。`)
      : top.binding_cap === "exit_liquidity" && top.recommended_notional != null
        ? L(`No account size makes ${asked.toLocaleString("en-US")} a GO: the live order book only supports about ${Math.round(top.recommended_notional).toLocaleString("en-US")} USDT.`,
            `任何账户规模都无法让 ${asked.toLocaleString("en-US")} USDT 通过：当前盘口只能承接约 ${Math.round(top.recommended_notional).toLocaleString("en-US")} USDT。`)
        : L(`No account size makes ${asked.toLocaleString("en-US")} a GO.`, `任何账户规模都无法让 ${asked.toLocaleString("en-US")} USDT 通过。`);
  return (
    <section className="rounded-lg border border-border bg-card px-3 py-2.5 text-sm" aria-label={L("The same trade by account size", "按账户规模看这笔交易")}>
      <p className="font-medium text-foreground">{L("No account size given, so here is the same trade at a few:", "你没有给出账户规模，这里是同一笔交易在几种账户规模下的结论：")}</p>
      <ul className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        {ladder.map((p) => {
          const word = lang === "zh" ? VERDICT_ZH[p.verdict] ?? p.verdict : p.verdict.replace(/_/g, " ");
          const size = p.verdict === "REDUCE_TO" && p.recommended_notional != null ? ` ${Math.round(p.recommended_notional).toLocaleString("en-US")}` : "";
          return (
            <li key={p.equity}>
              <button
                type="button"
                disabled={!onRerun}
                onClick={() => onRerun?.({ account_equity_quote: p.equity })}
                title={L(`Re-run this trade with a ${k(p.equity)} USDT account`, `按 ${k(p.equity)} USDT 账户重新计算`)}
                className="w-full rounded-md border border-border px-2 py-1.5 text-left hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-default disabled:hover:bg-transparent"
              >
                <span className="block text-xs text-muted-foreground">{L(`${k(p.equity)} account`, `${k(p.equity)} 账户`)}</span>
                <span className={`font-medium ${tone(p.verdict)}`}>
                  {word}
                  {size}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[13px] text-muted-foreground">
        {end} {onRerun ? L("Press one to re-run the trade with that account.", "点击任一项，按该账户重新计算。") : null}
      </p>
    </section>
  );
}
