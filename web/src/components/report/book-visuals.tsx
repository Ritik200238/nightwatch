"use client";

import type { ReactNode } from "react";
import type { Report } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import { type Lang, tr } from "@/lib/i18n";

type Tone = "good" | "critical" | "muted";

const TONE: Record<Tone, string> = { good: "text-status-good", critical: "text-status-critical", muted: "text-muted-foreground" };

/** One before -> after tile. A rise is bad for all three (loss size, concentration): coloured critical, a fall good. */
function Tile({ label, before, after, fmt, unit = "" }: { label: string; before: number; after: number; fmt: (v: number) => string; unit?: string }) {
  const d = after - before;
  const flat = Math.abs(d) < 1e-9 || fmt(before) === fmt(after);
  const tone: Tone = flat ? "muted" : d > 0 ? "critical" : "good";
  return (
    <li className="border-t border-border pt-2">
      <span className="block text-xs text-muted-foreground">{label}</span>
      <span className="tabular mt-0.5 block text-[15px] leading-tight">
        <span className="text-muted-foreground">{fmt(before)}</span>
        <span className="mx-1 text-muted-foreground" aria-hidden>
          →
        </span>
        <span className={`font-semibold ${TONE[tone]}`}>{fmt(after)}</span>
        {unit ? <span className="ml-1 text-xs text-muted-foreground">{unit}</span> : null}
      </span>
      <span className={`tabular block text-xs ${TONE[tone]}`}>
        {flat ? "±0" : `${d > 0 ? "+" : "−"}${fmt(Math.abs(d))}`}
      </span>
    </li>
  );
}

/** For a ticket with open positions: the book before and after this trade (the one-in-twenty loss,
 *  the worst crash replay, the largest single name), then each position's share of capital beside
 *  its share of that one-in-twenty loss. Everything is read from ``report.portfolio``. */
export function BookVisuals({ report, lang = "en" }: { report: Report; lang?: Lang }) {
  const L = tr(lang);
  const p = report.portfolio;
  if (!p || !(p.before.gross_quote > 0)) return null;

  const tiles: ReactNode[] = [];
  const tb = p.before.tail_loss_quote;
  const ta = p.after.tail_loss_quote;
  if (tb != null && ta != null) {
    tiles.push(<Tile key="tail" label={L("One-in-twenty loss", "二十分之一的亏损")} before={Math.abs(tb)} after={Math.abs(ta)} fmt={(v) => fmtUsd(v)} unit="USDT" />);
  }
  const crashes = p.stress?.crashes ?? [];
  const held = crashes.map((c) => c.held_quote).filter((v): v is number => v != null);
  const asked = crashes.map((c) => c.asked_quote).filter((v): v is number => v != null);
  if (held.length && asked.length) {
    tiles.push(<Tile key="crash" label={L("Worst crash replay", "最坏暴跌回放")} before={Math.abs(Math.min(...held))} after={Math.abs(Math.min(...asked))} fmt={(v) => fmtUsd(v)} unit="USDT" />);
  }
  const lb = p.before.largest_pct_of_gross;
  const la = p.after.largest_pct_of_gross;
  if (lb != null && la != null) {
    tiles.push(
      <Tile
        key="name"
        label={L(`Largest single name (${p.before.largest_name ?? "—"} → ${p.after.largest_name ?? "—"})`, `最大单一标的（${p.before.largest_name ?? "—"} → ${p.after.largest_name ?? "—"}）`)}
        before={lb}
        after={la}
        fmt={(v) => `${v.toFixed(0)}%`}
        unit={L("of book", "占组合")}
      />,
    );
  }

  // Who carries the bad case: capital share vs. share of the book's tail loss, same windows as the tail.
  const rows = (p.attribution?.contributions ?? []).filter((c) => c.component_share != null);
  const added = p.after.gross_quote > p.before.gross_quote + 1e-9;
  const lastIdx = (p.attribution?.contributions.length ?? 0) - 1;
  const contribs = p.attribution?.contributions ?? [];

  if (!tiles.length && !rows.length) return null;
  return (
    <section className="border-t border-border pt-4 text-sm" aria-label={L("Your book before and after this trade", "这笔交易前后的组合")}>
      {tiles.length ? (
        <>
          <p className="font-medium text-foreground">{L("Your book, before → after this trade", "你的组合：这笔交易前 → 后")}</p>
          <ul className={`mt-2 grid grid-cols-1 gap-1.5 ${tiles.length >= 3 ? "sm:grid-cols-3" : tiles.length === 2 ? "sm:grid-cols-2" : ""}`}>{tiles}</ul>
        </>
      ) : null}
      {rows.length ? (
        <div className={tiles.length ? "mt-3" : ""}>
          <p className="font-medium text-foreground">{L("Share of capital vs. share of the bad case", "资金占比 vs. 坏情况亏损占比")}</p>
          <ul className="mt-2 space-y-2">
            {contribs.map((c, i) => {
              if (c.component_share == null) return null;
              const cap = c.share_of_gross * 100;
              const risk = c.component_share * 100;
              const heavier = risk > cap + 1;
              const isNew = added && i === lastIdx;
              return (
                <li key={`${c.ticker}-${i}`}>
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="font-medium text-foreground">
                      {c.ticker} <span className="font-normal text-muted-foreground">{c.side === "long" ? L("long", "多") : L("short", "空")}</span>
                      {isNew ? <span className="ml-1.5 text-[13px] font-normal text-muted-foreground">{L("this trade", "本次交易")}</span> : null}
                    </span>
                    <span className="tabular text-muted-foreground">
                      {cap.toFixed(0)}% {L("of capital", "资金")} <span aria-hidden>→</span>{" "}
                      <span className={`font-semibold ${heavier ? "text-status-critical" : risk < cap - 1 ? "text-status-good" : "text-foreground"}`}>{risk.toFixed(0)}% {L("of risk", "风险")}</span>
                    </span>
                  </div>
                  <div className="mt-1 space-y-0.5" role="img" aria-label={L(`${c.ticker}: ${cap.toFixed(0)}% of capital, ${risk.toFixed(0)}% of the bad-case loss`, `${c.ticker}：占资金 ${cap.toFixed(0)}%，占坏情况亏损 ${risk.toFixed(0)}%`)}>
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-muted-foreground/60" style={{ width: `${Math.min(100, Math.max(0, cap))}%` }} />
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                      <div className={`h-full rounded-full ${heavier ? "bg-status-critical" : "bg-status-warning"}`} style={{ width: `${Math.min(100, Math.max(0, risk))}%` }} />
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-[13px] text-muted-foreground">
            {L(
              `Grey is the share of capital, coloured the share of the book's one-in-twenty loss, read from the same ${p.attribution?.n_windows.toLocaleString("en-US")} past windows. A hedge can show below zero risk.`,
              `灰色为资金占比，彩色为占组合二十分之一亏损的比例，取自同样的 ${p.attribution?.n_windows.toLocaleString("en-US")} 个历史窗口。对冲仓位的风险占比可能为负。`,
            )}
          </p>
        </div>
      ) : null}
    </section>
  );
}
