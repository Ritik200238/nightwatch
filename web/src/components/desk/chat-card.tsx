"use client";

import type { ReactNode } from "react";
import type { BaseRateCard, ChatCard, CompareCard, CompareRow, ShockCard, WaysCard } from "@/lib/api";
import { fmtBps, fmtPct, fmtUsd } from "@/lib/format";
import { useLang } from "@/lib/lang";

const VERDICT_ZH: Record<string, string> = { GO: "可以做", REDUCE_TO: "减仓", HEDGE: "对冲", REVIEW: "复核", NO_GO: "不建议做" };

function verdictTone(v: string): string {
  if (v === "GO") return "text-status-good";
  if (v === "NO_GO") return "text-status-critical";
  return "text-status-warning";
}

/** Money with a sign the eye can read: −2,000 for a loss, +500 for a gain. */
function money(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v < 0 ? "−" : v > 0 ? "+" : ""}${fmtUsd(Math.abs(v))}`;
}

/** A bar whose length is the share of the widest number on the card, so the bars read against
 *  each other. A missing number draws nothing rather than a zero. */
function Bar({ value, max, tone }: { value: number | null | undefined; max: number; tone: string }) {
  const w = value == null || !max ? 0 : Math.max(2, Math.min(100, (Math.abs(value) / max) * 100));
  return (
    <div className="h-2 w-full rounded-full bg-foreground/10" aria-hidden>
      <div className={`h-2 rounded-full ${tone}`} style={{ width: `${w}%` }} />
    </div>
  );
}

function Frame({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="mt-2 rounded-md border border-border bg-card px-3 py-2.5 text-[13px]" aria-label={label}>
      {children}
    </section>
  );
}

function Shock({ c }: { c: ShockCard }) {
  const { tx } = useLang();
  const loss = c.pnl_quote < 0;
  const bars: { label: string; value: number | null; tone: string }[] = [
    { label: tx(`At a ${Math.abs(c.move_pct).toLocaleString("en-US")}% move ${c.move_pct < 0 ? "down" : "up"}`, `${c.move_pct < 0 ? "下跌" : "上涨"} ${Math.abs(c.move_pct).toLocaleString("en-US")}% 时`), value: c.pnl_quote, tone: loss ? "bg-status-critical" : "bg-status-good" },
    { label: tx("1-in-20 loss (history)", "二十分之一的坏情况（历史）"), value: c.p5_quote, tone: "bg-status-warning" },
    { label: tx(c.worst_name ? `Worst stress: ${c.worst_name}` : "Worst stress", c.worst_name ? `最坏压力情景：${c.worst_name_zh ?? c.worst_name}` : "最坏压力情景"), value: c.worst_quote, tone: "bg-status-critical" },
  ];
  const shown = bars.filter((b) => b.value != null);
  const max = Math.max(1, ...shown.map((b) => Math.abs(b.value as number)));
  const past = c.past;
  return (
    <Frame label={tx("The shock against the report", "冲击与报告的对比")}>
      <p className="font-medium text-foreground">
        {tx(`${c.ticker ?? ""} ${c.side} · ${fmtUsd(c.size)} USDT`, `${c.ticker ?? ""} ${c.side === "long" ? "多头" : "空头"} · ${fmtUsd(c.size)} USDT`)}
      </p>
      <ul className="mt-2 space-y-2">
        {shown.map((b) => (
          <li key={b.label}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 text-muted-foreground">{b.label}</span>
              <span className="shrink-0 font-medium tabular-nums">{money(b.value)}</span>
            </div>
            <Bar value={b.value} max={max} tone={b.tone} />
          </li>
        ))}
      </ul>
      {past && (past.p5_move_pct != null || past.p1_move_pct != null) ? (
        <p className="mt-2 text-muted-foreground">
          {tx(`Past closed windows${past.windows ? ` (${past.windows})` : ""}: one in 20 moved worse than ${fmtPct(past.p5_move_pct, 1)}, one in 100 worse than ${fmtPct(past.p1_move_pct, 1)}.`, `过去的休市窗口${past.windows ? `（${past.windows} 个）` : ""}：二十分之一的比 ${fmtPct(past.p5_move_pct, 1)} 更差，百分之一的比 ${fmtPct(past.p1_move_pct, 1)} 更差。`)}{" "}
          {past.beyond === "1_in_100" ? <span className="font-medium text-status-critical">{tx("This shock is beyond the 1-in-100.", "这个冲击比百分之一更极端。")}</span> : null}
          {past.beyond === "1_in_20" ? <span className="font-medium text-status-warning">{tx("This shock is beyond the 1-in-20.", "这个冲击比二十分之一更极端。")}</span> : null}
          {!past.beyond && c.pnl_pct < 0 ? <span className="font-medium text-status-good">{tx("This shock is inside what the past windows did.", "这个冲击在过去窗口的范围之内。")}</span> : null}
        </p>
      ) : null}
    </Frame>
  );
}

const ROW_LABEL: Record<CompareRow["key"], [string, string]> = {
  verdict: ["Verdict", "结论"],
  size: ["Size (USDT)", "仓位（USDT）"],
  p5: ["1-in-20 loss", "二十分之一的坏情况"],
  worst: ["Worst stress (USDT)", "最坏压力情景（USDT）"],
  worst_pct: ["Worst stress (% of position)", "最坏压力情景（占仓位）"],
  exit: ["Exit cost", "平仓成本"],
};

function cell(row: CompareRow, v: string | number | null, lang: string): ReactNode {
  if (v == null) return "—";
  if (row.unit === "verdict") {
    const s = String(v);
    return <span className={`font-medium ${verdictTone(s)}`}>{lang === "zh" ? VERDICT_ZH[s] ?? s : s.replace(/_/g, " ")}</span>;
  }
  const n = Number(v);
  if (row.unit === "usd") return row.key === "worst" ? money(n) : fmtUsd(n);
  if (row.unit === "pct") return fmtPct(n, 1);
  return fmtBps(n, 0);
}

function Compare({ c }: { c: CompareCard }) {
  const { lang, tx } = useLang();
  if (!c.rows.length) return null;
  return (
    <Frame label={tx("Before and after", "改动前后")}>
      <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)] items-baseline gap-x-2 gap-y-1.5">
        <span />
        <span className="text-xs text-muted-foreground">{tx("Before", "之前")}</span>
        <span className="text-xs text-muted-foreground">{tx("After", "之后")}</span>
        {c.rows.map((r) => {
          // "Changed" is what the reader sees: 14.4 bps and 13.6 bps both read "14 bps" and must
          // not get an arrow beside an identical number.
          const shown = (v: string | number | null) => (v == null ? "" : r.unit === "verdict" ? String(v) : r.unit === "pct" ? Number(v).toFixed(1) : String(Math.round(Number(v))));
          const changed = shown(r.before) !== shown(r.after);
          const [en, zh] = ROW_LABEL[r.key];
          return (
            <div key={r.key} className="contents">
              <span className="text-muted-foreground">{tx(en, zh)}</span>
              <span className="tabular-nums">{cell(r, r.before, lang)}</span>
              <span className={`tabular-nums ${changed ? "font-semibold" : ""}`}>
                {cell(r, r.after, lang)}
                {changed && r.unit !== "verdict" && typeof r.before === "number" && typeof r.after === "number" ? <span aria-hidden> {r.after > r.before ? "↑" : "↓"}</span> : null}
              </span>
            </div>
          );
        })}
      </div>
    </Frame>
  );
}

function Rate({ label, hits, n, share, tone }: { label: string; hits: number; n: number; share: number; tone: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="min-w-0 text-muted-foreground">{label}</span>
        <span className="shrink-0 font-medium tabular-nums">
          {hits} / {n} · {(share * 100).toFixed(share < 0.1 ? 1 : 0)}%
        </span>
      </div>
      <Bar value={share} max={1} tone={tone} />
    </div>
  );
}

function BaseRate({ c }: { c: BaseRateCard }) {
  const { tx } = useLang();
  const what = tx(`${c.up ? "rose" : "fell"} ${c.move_pct.toLocaleString("en-US")}% or more`, `${c.up ? "上涨" : "下跌"} ${c.move_pct.toLocaleString("en-US")}% 或以上`);
  const tone = c.up ? "bg-status-good" : "bg-status-critical";
  return (
    <Frame label={tx("How often it happened", "历史上发生的频率")}>
      <p className="font-medium text-foreground">{tx(`${c.ticker} ${what}`, `${c.ticker} ${what}`)}</p>
      <div className="mt-2 space-y-2">
        {c.windows ? <Rate label={tx(`Past ${c.weekend ? "weekends" : "overnight closes"} since ${c.windows.since}`, `${c.windows.since} 以来的${c.weekend ? "周末" : "隔夜休市"}`)} hits={c.windows.hits} n={c.windows.n} share={c.windows.share} tone={tone} /> : null}
        {c.conditional ? <Rate label={tx("Moments most like now", "与现在最相似的时刻")} hits={c.conditional.hits} n={c.conditional.n} share={c.conditional.share} tone="bg-status-warning" /> : null}
      </div>
      {c.windows ? <p className="mt-2 text-muted-foreground">{tx(`The biggest was ${fmtPct(c.windows.biggest_pct, 1)}.`, `最大的一次是 ${fmtPct(c.windows.biggest_pct, 1)}。`)}</p> : null}
    </Frame>
  );
}

function Ways({ c }: { c: WaysCard }) {
  const { lang, tx } = useLang();
  return (
    <Frame label={tx("The same idea, several ways", "同一个想法的几种做法")}>
      <ul className="space-y-2">
        {c.rows.map((r) => {
          const picked = r.label === c.pick;
          return (
            <li key={r.label} className={`rounded-md border px-2.5 py-2 ${picked ? "border-status-good/60 bg-status-good/5" : "border-border"}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                <span className="min-w-0 font-medium text-foreground">{lang === "zh" ? r.label_zh ?? r.label : r.label}</span>
                <span className={`shrink-0 font-medium ${verdictTone(r.verdict)}`}>{lang === "zh" ? VERDICT_ZH[r.verdict] ?? r.verdict : r.verdict.replace(/_/g, " ")}</span>
              </div>
              <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-muted-foreground sm:grid-cols-4">
                <div>
                  <dt className="text-xs">{tx("Size", "仓位")}</dt>
                  <dd className="tabular-nums text-foreground">{fmtUsd(r.size)}</dd>
                </div>
                <div>
                  <dt className="text-xs">{tx("1-in-20 loss", "二十分之一")}</dt>
                  <dd className="tabular-nums text-foreground">{r.p5_quote != null ? `${money(r.p5_quote)} (${fmtPct(r.p5_pct, 1)})` : "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs">{tx("Worst stress", "最坏压力")}</dt>
                  <dd className="tabular-nums text-foreground">{money(r.worst_quote)}</dd>
                </div>
                <div>
                  <dt className="text-xs">{tx("Exit cost", "平仓成本")}</dt>
                  <dd className="tabular-nums text-foreground">{r.exit_bps != null ? fmtBps(r.exit_bps, 0) : "—"}</dd>
                </div>
              </dl>
              {picked ? <p className="mt-1 text-xs font-medium text-status-good">{tx("Safest at your size", "按你的仓位最安全")}</p> : null}
            </li>
          );
        })}
      </ul>
    </Frame>
  );
}

/** The picture under a chat answer: a few bars or rows of the answer's own numbers. */
export function ChatCardView({ card }: { card: ChatCard }) {
  switch (card.kind) {
    case "shock":
      return <Shock c={card} />;
    case "compare":
      return <Compare c={card} />;
    case "base_rate":
      return <BaseRate c={card} />;
    case "ways":
      return <Ways c={card} />;
    default:
      return null;
  }
}
