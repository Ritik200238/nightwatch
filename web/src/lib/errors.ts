/**
 * Plain-language errors, kept pure so they can be tested without a browser.
 *
 * Why: the API answers a bad request with pydantic's JSON, and an unreachable box with
 * developer text. A visitor should read neither. These turn both into one short sentence
 * in the language the page is in.
 */

export type ErrLang = "en" | "zh";

const FIELDS: Record<string, [string, string]> = {
  notional_quote: ["Size", "仓位"],
  account_equity_quote: ["Account equity", "账户资金"],
  leverage: ["Leverage", "杠杆"],
  horizon_hours: ["Hours", "小时数"],
  stop_price: ["Stop", "止损"],
  hedge_ratio: ["Hedge ratio", "对冲比例"],
  ticker: ["Token", "代币"],
};

const UNIT: Record<string, string> = { notional_quote: " USDT", account_equity_quote: " USDT" };

function n(v: unknown): string {
  return typeof v === "number" ? v.toLocaleString("en-US") : String(v);
}

interface PydanticItem {
  type?: string;
  loc?: unknown[];
  msg?: string;
  ctx?: Record<string, unknown>;
}

/** One validation item to one sentence. Unknown shapes fall back to a generic line. */
export function validationLine(it: PydanticItem, lang: ErrLang): string {
  const field = String(it.loc?.[it.loc.length - 1] ?? "");
  const [en, zh] = FIELDS[field] ?? [field || "Input", field || "输入"];
  const name = lang === "zh" ? zh : en;
  const unit = UNIT[field] ?? (field === "leverage" ? "x" : "");
  const c = it.ctx ?? {};
  const lo = c.ge ?? c.gt;
  const hi = c.le ?? c.lt;
  switch (it.type) {
    case "less_than_equal":
    case "less_than":
      // Size has a floor of 1 as well, so the message gives the whole range.
      if (field === "notional_quote" || field === "account_equity_quote")
        return lang === "zh" ? `${name}须在 1 到 ${n(hi)} USDT 之间。` : `${name} must be between 1 and ${n(hi)} USDT.`;
      return lang === "zh" ? `${name}不能超过 ${n(hi)}${unit}。` : `${name} can be at most ${n(hi)}${unit}.`;
    case "greater_than":
    case "greater_than_equal":
      if (field === "notional_quote" || field === "account_equity_quote")
        return lang === "zh" ? `${name}须大于 0 USDT。` : `${name} must be more than 0 USDT.`;
      return lang === "zh" ? `${name}不能低于 ${n(lo)}${unit}。` : `${name} must be at least ${n(lo)}${unit}.`;
    case "missing":
      return lang === "zh" ? `请填写${name}。` : `${name} is required.`;
    case "string_too_long":
      return lang === "zh" ? `${name}太长了。` : `${name} is too long.`;
    case "too_long":
      return lang === "zh" ? `${name}条目太多了。` : `Too many ${name.toLowerCase()} entries.`;
    case "float_parsing":
    case "int_parsing":
    case "float_type":
    case "int_type":
      return lang === "zh" ? `${name}必须是数字。` : `${name} must be a number.`;
    case "enum":
      return lang === "zh" ? `${name}的取值无效。` : `${name} is not a valid choice.`;
    default:
      return lang === "zh" ? `${name}不符合要求，请检查后重试。` : `${name} is not valid. Please check it and try again.`;
  }
}

/** The busy-desk sentence, used wherever the API could not be reached in time. */
export function busyMessage(lang: ErrLang): string {
  return lang === "zh" ? "服务器正忙，正在重试…" : "The desk is busy, retrying…";
}

/** Still failing after the retry: say so without developer words. */
export function stillBusyMessage(lang: ErrLang): string {
  return lang === "zh" ? "服务器暂时很忙，请过一会儿再试。" : "The desk is busy right now. Please try again in a minute.";
}

const DEV_TEXT = /cannot reach the nightwatch api|is the backend running|no backend configured/i;

/** Turn whatever the API sent as `detail` into a sentence a visitor can act on. */
export function friendlyDetail(detail: unknown, status: number, lang: ErrLang): string {
  if (Array.isArray(detail) && detail.length) {
    const lines = detail.map((d) => validationLine((d ?? {}) as PydanticItem, lang));
    return [...new Set(lines)].join(" ");
  }
  if (typeof detail === "string") {
    // A JSON list that arrived stringified (older clients and the proxy both do this).
    const t = detail.trim();
    if (t.startsWith("[") && t.endsWith("]")) {
      try {
        const parsed = JSON.parse(t);
        if (Array.isArray(parsed) && parsed.length) return friendlyDetail(parsed, status, lang);
      } catch {
        /* not JSON: fall through */
      }
    }
    if (DEV_TEXT.test(detail)) return stillBusyMessage(lang);
    return detail;
  }
  if (status === 0 || status === 502 || status === 503 || status === 504) return stillBusyMessage(lang);
  return lang === "zh" ? "出了点问题，请重试。" : "Something went wrong. Please try again.";
}

/** Ticket checks that need no server: the same rules the API and the gate apply, in the
 *  visitor's language. Returns one message per field. `price` is the current price when
 *  the page knows it, which is what a stop is judged against. */
export function ticketProblems(
  v: { ticker: string; side: "long" | "short"; notional: number; equity: number | null; stop: number | null; hours: number | null; hoursNeeded: boolean; leverage: number | null },
  price: number | null,
  lang: ErrLang,
): Partial<Record<"ticker" | "notional" | "equity" | "stop" | "hours" | "leverage", string>> {
  const t = (en: string, zh: string) => (lang === "zh" ? zh : en);
  const e: Partial<Record<"ticker" | "notional" | "equity" | "stop" | "hours" | "leverage", string>> = {};
  if (!v.ticker) e.ticker = t("Pick a token.", "请选择代币。");
  if (!Number.isFinite(v.notional) || v.notional <= 0) e.notional = t("Enter a size above 0 USDT.", "请输入大于 0 的 USDT 金额。");
  else if (v.notional < 1 || v.notional > 10_000_000) e.notional = t("Size must be between 1 and 10,000,000 USDT.", "仓位须在 1 到 10,000,000 USDT 之间。");
  if (v.equity != null && (!(v.equity > 0) || v.equity > 1_000_000_000)) e.equity = t("Equity must be between 1 and 1,000,000,000 USDT.", "账户资金须在 1 到 1,000,000,000 USDT 之间。");
  if (v.stop != null && !(v.stop > 0)) e.stop = t("A stop must be a price above 0.", "止损必须是大于 0 的价格。");
  else if (v.stop != null && price != null && price > 0) {
    if (v.side === "long" && v.stop >= price) e.stop = t(`A stop for a long must be below the current price (${n(price)}).`, `做多的止损必须低于当前价格（${n(price)}）。`);
    if (v.side === "short" && v.stop <= price) e.stop = t(`A stop for a short must be above the current price (${n(price)}).`, `做空的止损必须高于当前价格（${n(price)}）。`);
  }
  if (v.hoursNeeded && !(v.hours && v.hours > 0)) e.hours = t("Enter how many hours.", "请输入小时数。");
  if (v.leverage != null && !(v.leverage >= 1 && v.leverage <= 125)) e.leverage = t("Leverage is between 1x and 125x.", "杠杆范围是 1 到 125 倍。");
  return e;
}
