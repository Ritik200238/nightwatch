"use client";

import type { CorporateEvent, Report } from "@/lib/api";
import { type Lang, tr } from "@/lib/i18n";

/** One event in a sentence, with where it came from. Plain facts only. */
function describe(e: CorporateEvent, lang: Lang): string {
  const L = tr(lang);
  const src = `${e.source_label}${e.announced ? L(`, declared ${e.announced}`, `，公告日 ${e.announced}`) : ""}`;
  if (e.kind === "dividend") {
    const amt = e.amount != null ? `${e.amount} ${e.currency ?? "USD"}` : "";
    const pct = e.amount_pct_of_price != null ? L(` (about ${e.amount_pct_of_price.toFixed(2)}% of the price)`, `（约占股价 ${e.amount_pct_of_price.toFixed(2)}%）`) : "";
    return L(`Ex-dividend ${amt} a share on ${e.date}${pct}`, `${e.date} 除息，每股 ${amt}${pct}`) + ` [${src}]`;
  }
  if (e.kind === "split") {
    return L(`${e.ratio ?? ""} split effective ${e.date}`, `${e.date} 拆股生效，比例 ${e.ratio ?? ""}`) + ` [${src}]`;
  }
  return `${e.date} ${e.detail ?? e.kind} [${e.source_label}]`;
}

/** Ex-dividend dates, splits and Bitget notices around the hold, from the stored
 *  calendar. Says "none known" rather than guessing, and says the rToken handling is
 *  not verified when something falls inside the hold. */
export function CorporateEventsNote({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const c = report.corporate_events;
  if (!c) return null;
  const inside = c.in_hold ?? [];
  const notices = c.notices ?? [];
  if (!c.covered) {
    return (
      <p className="mt-3 text-[13px] text-muted-foreground">
        {L("Dividends and splits: not checked, the calendar has not been synced yet.", "分红与拆股：未检查，日历尚未同步。")}
      </p>
    );
  }
  const warn = inside.length > 0 || notices.some((n) => n.kind === "suspension");
  return (
    <div className={`mt-3 border-l-2 pl-3 text-sm ${warn ? "border-status-warning" : "border-border"}`}>
      <span className="font-medium text-foreground">{L("Dividends and splits: ", "分红与拆股：")}</span>
      {inside.length ? (
        <span className="text-muted-foreground">
          {L("inside this hold, ", "持仓期内：")}
          {inside.map((e) => describe(e, lang)).join("; ")}.
          {c.handling ? ` ${L(c.handling, "Bitget 对 rToken 持有人如何调整，目前无法核实；持有前请先看 Bitget 自己的公告。")}` : ""}
        </span>
      ) : (
        <span className="text-muted-foreground">
          {L("none inside this hold in the stored calendar.", "已存储的日历里，持仓期内没有。")}
          {c.next_after ? ` ${L("Next: ", "之后最近：")}${describe(c.next_after, lang)}.` : ""}
        </span>
      )}
      {notices.length ? (
        <span className="mt-1 block text-muted-foreground">
          {L("Recent Bitget notice: ", "Bitget 近期公告：")}
          {notices.map((n) => `${n.date} ${n.detail ?? n.kind}`).join("; ")}
        </span>
      ) : null}
    </div>
  );
}
