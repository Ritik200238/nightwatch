"use client";

import type { Report, TicketInput } from "@/lib/api";
import { verdictText } from "@/lib/verdict-style";
import { type Lang, tr } from "@/lib/i18n";

const VERDICT_ZH: Record<string, string> = { GO: "可以做", REDUCE_TO: "减仓", HEDGE: "对冲", REVIEW: "复核", NO_GO: "不建议做" };

/** What each gate rule asks of the trader when an account size alone cannot clear it. */
const NEEDS: Record<string, { en: string; zh: string }> = {
  written_plan: { en: 'a reason and a "wrong if" line', zh: "写下理由和“错在哪里”" },
  stop: { en: "a stop at a sensible distance", zh: "一个距离合理的止损" },
  market_posture: { en: "calmer markets (the regime is hostile now)", zh: "市场转好（当前市场状态不利）" },
  data_quality: { en: "fresher data", zh: "更新的数据" },
  exit_liquidity: { en: "a deeper order book", zh: "更深的盘口" },
  liquidation: { en: "less leverage", zh: "更低的杠杆" },
  revenge_cooldown: { en: "a cool-down after your recent loss", zh: "亏损后的冷静期结束" },
  circuit_breaker: { en: "your loss limit to reset", zh: "亏损限额重置" },
  book_tail: { en: "a smaller book risk", zh: "降低整体持仓风险" },
};

function k(x: number): string {
  return x >= 1000 && x % 1000 === 0 ? `${(x / 1000).toLocaleString("en-US")}k` : x.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function tone(v: string): string {
  return verdictText(v);
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
  const needs = [...new Set((top.blocking ?? []).map((r) => NEEDS[r]).filter(Boolean).map((n) => (lang === "zh" ? n.zh : n.en)))];
  const end =
    edge != null
      ? L(`It is a GO at ${asked.toLocaleString("en-US")} from an account of about ${Math.round(edge).toLocaleString("en-US")} USDT.`,
          `账户约 ${Math.round(edge).toLocaleString("en-US")} USDT 起，${asked.toLocaleString("en-US")} USDT 即可通过。`)
      : top.binding_cap === "exit_liquidity" && top.recommended_notional != null
        ? L(`No account size makes ${asked.toLocaleString("en-US")} a GO: the live order book only supports about ${Math.round(top.recommended_notional).toLocaleString("en-US")} USDT.`,
            `任何账户规模都无法让 ${asked.toLocaleString("en-US")} USDT 通过：当前盘口只能承接约 ${Math.round(top.recommended_notional).toLocaleString("en-US")} USDT。`)
        : needs.length
          ? L(`Even on a larger account it still needs: ${needs.join("; ")}.`, `即使账户更大，仍需：${needs.join("；")}。`)
          : L(`No account size makes ${asked.toLocaleString("en-US")} a GO.`, `任何账户规模都无法让 ${asked.toLocaleString("en-US")} USDT 通过。`);
  return (
    <section className="border-t border-border pt-4 text-sm" aria-label={L("The same trade by account size", "按账户规模看这笔交易")}>
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
