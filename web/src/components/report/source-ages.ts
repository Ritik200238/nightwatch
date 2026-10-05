import { fmtHoursL, type Lang, t as tl, tr } from "@/lib/i18n";

/** How long before the report's moment, in plain units: minutes under an hour, then the
 *  usual hours / days. */
function ago(hours: number, lang: Lang): string {
  const h = Math.max(0, hours);
  const zh = lang === "zh";
  if (h < 1) return zh ? `${Math.max(1, Math.round(h * 60))} 分钟前` : `${Math.max(1, Math.round(h * 60))} min ago`;
  return zh ? `${fmtHoursL(h, lang)}前` : `${fmtHoursL(h, lang)} ago`;
}

const WHAT_ZH: Record<string, string> = {
  "newest candle": "最新 K 线",
  "newest candle or funding": "最新 K 线或资金费率",
  "newest bar": "最新行情",
  "latest release already out": "已发布的最近一次数据",
  "newest headline": "最新新闻",
  "latest filing": "最近一份文件",
};

/** One source on the report's sources line, with its age said plainly.
 *
 *  `last_ts` is a data date whose meaning differs by feed (a calendar's first-seen time, the
 *  latest macro release already out, a quiet ticker's newest headline), so reading it as "how
 *  fresh is this feed" misleads. Where the server says when it last pulled the feed, that is
 *  shown as "checked", with what `last_ts` is beside it; the feed's data date is left off
 *  where it only says when a row first appeared. Everything is measured to the report's own
 *  moment, so an old report reads as it did then. */
export function sourceLine(s: Record<string, unknown>, asOf: string, lang: Lang): string {
  const L = tr(lang);
  const name = tl(lang, "feed", String(s.kind));
  const at = Date.parse(asOf);
  const hoursBefore = (iso: unknown): number | null => {
    const t = typeof iso === "string" ? Date.parse(iso) : NaN;
    return Number.isNaN(t) || Number.isNaN(at) ? null : (at - t) / 3_600_000;
  };
  const status = typeof s.status === "string" ? s.status : null;
  // The server's note already reads "unavailable since 08:00 UTC (HTTP 503)".
  if (status === "unavailable") return `${name} (${lang === "zh" ? "不可用" : typeof s.note === "string" ? s.note : "unavailable"})`;
  const last = hoursBefore(s.last_ts);
  if (status === "last_good") {
    return `${name} (${last != null ? L(`last good ${ago(last, lang)}`, `最近一次有效数据 ${ago(last, lang)}`) : L("last good, age unknown", "最近一次有效数据，时间未知")})`;
  }
  const checked = hoursBefore(s.checked_at);
  const what = typeof s.last_what === "string" ? s.last_what : null;
  if (checked != null) {
    const parts = [L(`checked ${ago(checked, lang)}`, `${ago(checked, lang)}已检查`)];
    if (last != null && what && what !== "row first seen") parts.push(`${lang === "zh" ? (WHAT_ZH[what] ?? what) : what} ${ago(last, lang)}`);
    return `${name} (${parts.join(lang === "zh" ? "，" : "; ")})`;
  }
  // Feeds the desk does not pull itself (the book, MCP, options, open interest): the data's own time.
  return last != null ? `${name} (${lang === "zh" ? `${fmtHoursL(Math.max(0, last), lang)}前` : `${fmtHoursL(Math.max(0, last), lang)} old`})` : name;
}
