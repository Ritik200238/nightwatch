"use client";

import { useEffect, useState } from "react";
import type { Report } from "@/lib/api";
import { type Lang, tr } from "@/lib/i18n";

type Seg = { from: number; to: number };

function clock(ms: number, lang: Lang): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const hms = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return d > 0 ? `${d}${lang === "zh" ? "天 " : "d "}${hms}` : hms;
}

function etLabel(ms: number, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: lang !== "zh",
  }).format(new Date(ms));
}

function hoursLabel(h: number): string {
  return h >= 10 ? `${Math.round(h)}` : `${Math.round(h * 10) / 10}`;
}

/** Now to the end of the hold on the US market clock: the stretches with no US price discovery
 *  shaded, each open and close inside the hold marked, and a live countdown to the next regular
 *  open (or to the close, while it is open). The sessions come from the backend's NYSE calendar. */
export function MarketClock({ report, lang = "en" }: { report: Report; lang?: Lang }) {
  const L = tr(lang);
  const tl = report.timeline;
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!tl || !tl.sessions.length) return null;

  const t0 = Date.parse(tl.as_of);
  const t1 = Date.parse(tl.hold_end);
  const span = t1 - t0;
  if (!(span > 0)) return null;
  const sessions = tl.sessions.map((s) => ({ open: Date.parse(s.open), close: Date.parse(s.close) }));

  // Open stretches inside the hold; everything else in the hold is the market shut.
  const open: Seg[] = sessions
    .map((s) => ({ from: Math.max(s.open, t0), to: Math.min(s.close, t1) }))
    .filter((s) => s.to > s.from);
  const openMs = open.reduce((a, s) => a + (s.to - s.from), 0);
  const closedH = (span - openMs) / 3_600_000;
  const holdH = span / 3_600_000;
  const closed: Seg[] = [];
  let cursor = t0;
  for (const s of open) {
    if (s.from > cursor) closed.push({ from: cursor, to: s.from });
    cursor = s.to;
  }
  if (cursor < t1) closed.push({ from: cursor, to: t1 });

  const pct = (ms: number) => `${(((ms - t0) / span) * 100).toFixed(2)}%`;
  const marks: { at: number; kind: "open" | "close" }[] = [];
  for (const s of sessions) {
    if (s.open > t0 && s.open < t1) marks.push({ at: s.open, kind: "open" });
    if (s.close > t0 && s.close < t1) marks.push({ at: s.close, kind: "close" });
  }

  let live: string | null = null;
  let openNow = false;
  if (now != null) {
    const inside = sessions.find((s) => s.open <= now && now < s.close);
    if (inside) {
      openNow = true;
      live = L(`US market open now. Closes in ${clock(inside.close - now, lang)}`, `美股当前开市。距收盘 ${clock(inside.close - now, lang)}`);
    } else {
      const nxt = sessions.find((s) => s.open > now);
      if (nxt) live = L(`US market opens in ${clock(nxt.open - now, lang)}`, `距美股开盘 ${clock(nxt.open - now, lang)}`);
    }
  }

  const noOpen = open.length === 0;
  return (
    <section className="rounded-lg border border-border bg-card px-3 py-2.5 text-sm" aria-label={L("The hold on the US market clock", "持仓期间的美股时钟")}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="font-medium text-foreground">{L("The hold on the US market clock", "持仓期间的美股时钟")}</p>
        {live ? (
          <p className={`tabular text-[13px] font-medium ${openNow ? "text-status-good" : "text-status-warning"}`} aria-live="off">
            {live}
          </p>
        ) : null}
      </div>
      <div className="relative mt-3 h-3 overflow-hidden rounded-full bg-status-good/25" role="img" aria-label={L(`${hoursLabel(closedH)} of the ${hoursLabel(holdH)} hours have the US market shut`, `${hoursLabel(holdH)} 小时的持仓里有 ${hoursLabel(closedH)} 小时美股休市`)}>
        {closed.map((s) => (
          <span key={s.from} className="absolute inset-y-0 bg-status-warning/60" style={{ left: pct(s.from), width: `${(((s.to - s.from) / span) * 100).toFixed(2)}%` }} />
        ))}
        {marks.map((m) => (
          <span key={`${m.kind}-${m.at}`} className="absolute inset-y-0 w-0.5 bg-foreground/70" style={{ left: pct(m.at) }} />
        ))}
      </div>
      <div className="relative mt-1 h-4 text-[11px] text-muted-foreground">
        <span className="absolute left-0">{L("analysed", "分析时")}</span>
        <span className="absolute right-0">{L("hold ends", "持仓结束")}</span>
      </div>
      <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[13px] text-muted-foreground">
        <li>
          <span className="tabular font-medium text-foreground">{etLabel(t0, lang)} ET</span> {L("analysed", "分析时")}
        </li>
        {marks.map((m) => (
          <li key={`l-${m.kind}-${m.at}`}>
            <span className="tabular font-medium text-foreground">{etLabel(m.at, lang)} ET</span> {m.kind === "open" ? L("US open", "美股开盘") : L("US close", "美股收盘")}
          </li>
        ))}
        <li>
          <span className="tabular font-medium text-foreground">{etLabel(t1, lang)} ET</span> {L("hold ends", "持仓结束")}
        </li>
      </ul>
      <p className="mt-1.5 text-[13px] text-muted-foreground">
        {noOpen
          ? L(`The US market is shut for the whole ${hoursLabel(holdH)} hours: no US price discovery at all while you hold.`, `这 ${hoursLabel(holdH)} 小时里美股全程休市：持仓期间没有任何美股价格发现。`)
          : L(`The US market is shut for ${hoursLabel(closedH)} of the ${hoursLabel(holdH)} hours (shaded). News that lands then is priced only when it opens.`, `${hoursLabel(holdH)} 小时中有 ${hoursLabel(closedH)} 小时美股休市（阴影部分）。这期间的消息要等开盘才会被定价。`)}
      </p>
    </section>
  );
}
