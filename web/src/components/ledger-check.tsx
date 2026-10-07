"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type LedgerResponse, type LedgerRow } from "@/lib/api";
import { useLang } from "@/lib/lang";
import { fmtPct } from "@/lib/format";

const MIN_N = 20;
const HEADER = ["id", "kind", "as_of", "ticker", "side", "horizon_h", "verdict", "stated_p5_pct", "outcome_pct", "missed", "receipt"] as const;

function toCsv(rows: LedgerRow[]): string {
  const cell = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [HEADER.join(","), ...rows.map((r) => HEADER.map((h) => cell(r[h])).join(","))].join("\n") + "\n";
}

/** The raw record behind the headline numbers: every scored forecast as a downloadable
 * file, and the tickers where the stated line was crossed most often, so a reader can see
 * where the desk is weakest instead of only where it is average. */
export function LedgerCheck() {
  const { tx } = useLang();
  const [ledger, setLedger] = useState<LedgerResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.ledger().then(setLedger).catch(() => setFailed(true));
  }, []);

  const weakest = useMemo(() => {
    if (!ledger) return [];
    const by = new Map<string, { n: number; missed: number }>();
    for (const r of ledger.rows) {
      const g = by.get(r.ticker) ?? { n: 0, missed: 0 };
      g.n += 1;
      g.missed += r.missed ? 1 : 0;
      by.set(r.ticker, g);
    }
    return [...by.entries()]
      .filter(([, g]) => g.n >= MIN_N)
      .map(([ticker, g]) => ({ ticker, ...g, rate: g.missed / g.n }))
      .sort((a, b) => b.rate - a.rate)
      .slice(0, 6);
  }, [ledger]);

  const download = () => {
    if (!ledger) return;
    const url = URL.createObjectURL(new Blob([toCsv(ledger.rows)], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "nightwatch-scored-forecasts.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  if (failed) return <p className="text-sm text-muted-foreground">{tx("The record could not be loaded just now. Try again in a minute.", "暂时无法加载记录，请稍后再试。")}</p>;
  if (!ledger) return <p className="text-sm text-muted-foreground">{tx("Loading the record…", "正在加载记录…")}</p>;

  return (
    <div className="space-y-4 text-sm">
      <p className="max-w-prose text-muted-foreground">
        {tx(
          `All ${ledger.scored.toLocaleString()} scored forecasts, one row each: the one-in-twenty line stated at the time, what then happened, and whether it went past. Live tickets carry their receipt. Recount the totals above yourself, or sort it any way you like.`,
          `全部 ${ledger.scored.toLocaleString()} 条已评分的预测，每条一行：当时所述的二十分之一线、之后实际发生了什么、是否越线。实时单附带凭证。你可以自己重算上面的总数，或按任意方式排序。`,
        )}
      </p>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <button
          type="button"
          onClick={download}
          className="relative inline-flex min-h-10 items-center rounded-md border border-border px-3 text-sm font-medium hover:bg-muted"
        >
          {tx("Download the scored forecasts (CSV)", "下载已评分的预测（CSV）")}
        </button>
        <a href="/api/ledger" target="_blank" rel="noreferrer" className="relative inline-flex min-h-10 items-center underline underline-offset-2">
          /api/ledger
        </a>
      </div>
      {weakest.length ? (
        <div>
          <p className="font-medium">{tx("Where the line was crossed most often", "越线最频繁的标的")}</p>
          <p className="t-caption mb-2 max-w-prose">
            {tx(`Tickers with at least ${MIN_N} scored forecasts. The target is ${fmtPct(ledger.target_rate * 100, 0, false)}; a higher rate means the stated line was too optimistic for that name.`, `至少有 ${MIN_N} 条已评分预测的标的。目标为 ${fmtPct(ledger.target_rate * 100, 0, false)}；比例更高说明该标的所述的线过于乐观。`)}
          </p>
          <ul className="grid grid-cols-1 divide-y divide-border border-y border-border sm:grid-cols-2 sm:gap-x-12 sm:divide-y-0">
            {weakest.map((w) => (
              <li key={w.ticker} className="flex items-baseline justify-between gap-3 py-2 sm:border-b sm:border-border">
                <span className="font-mono">{w.ticker}</span>
                <span className="tabular-nums text-muted-foreground">
                  {w.missed} / {w.n} · {fmtPct(w.rate * 100, 1, false)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
