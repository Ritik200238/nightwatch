/** Report-page localisation: English (default) and Simplified Chinese.
 *
 *  Two tools, both keyed by `lang`:
 *   - `STRINGS` / `t(lang, key)` for the shared vocabulary that recurs across the page
 *     (verdict names, cap and gate-rule names, market-hour buckets, lesson labels).
 *   - `tr(lang)` returns `(en, zh) => string` for template sentences, so an English
 *     sentence and its Chinese counterpart sit side by side and share the same numbers.
 *
 *  Text the server writes (reasons, failure-mode titles, warnings, lens definitions) is
 *  shown as sent. Numbers are formatted identically in both languages.
 */

export type Lang = "en" | "zh";

export type Verdict = "GO" | "REDUCE_TO" | "HEDGE" | "NO_GO" | "REVIEW";

export const STRINGS = {
  en: {
    verdictName: { GO: "GO", REDUCE_TO: "REDUCE TO", HEDGE: "HEDGE", NO_GO: "NO GO", REVIEW: "REVIEW" },
    verdictHeadline: {
      GO: "Go at the requested size",
      REDUCE_TO: "Reduce the size",
      HEDGE: "Hedge instead of cutting",
      NO_GO: "Do not take this trade as specified",
      REVIEW: "Review before deciding",
    },
    verdictMeaning: {
      GO: "every check passed at the size you asked for",
      REDUCE_TO: "the idea passes, but only at the smaller size shown",
      HEDGE: "keep the size, and hedge part of it with the stock's Bitget perpetual",
      REVIEW: "something is missing or unclear (a stop, a plan, your account size); say it and it re-runs",
      NO_GO: "a hard limit refuses it as asked, and the reason says which one",
    },
    cap: {
      regime: "Regime",
      risk_budget: "Risk Budget",
      concentration: "Concentration",
      exit_liquidity: "Exit Liquidity",
      stress: "Stress",
      book_tail: "Book Tail",
    },
    rule: {
      book_tail: "Book Tail",
      circuit_breaker: "Circuit Breaker",
      data_quality: "Data Quality",
      exit_liquidity: "Exit Liquidity",
      liquidation: "Liquidation",
      market_posture: "Market Posture",
      position_size: "Position Size",
      revenge_cooldown: "Revenge Cooldown",
      risk_budget: "Risk Budget",
      stop: "Stop",
      written_plan: "Written Plan",
    },
    bucket: {
      us_regular: "US session",
      us_pre: "US pre-market",
      us_post: "US after-hours",
      weeknight: "Weeknight",
      friday_night: "Friday night",
      weekend: "Weekend",
      sunday_night: "Sunday night",
      holiday: "US holiday",
    },
    lesson: {
      worse_than_stress: "worse than the stress case",
      bad_tail: "bad tail",
      as_expected: "as expected",
      good_tail: "good tail",
      better_than_forecast: "better than forecast",
      no_distribution: "no forecast",
    },
    severity: { extreme: "extreme", severe: "severe" } as Record<string, string>,
    impact: { high: "high", medium: "medium", low: "low", none: "none", unread: "not yet read" } as Record<string, string>,
    feed: {
      features: "computed features", bitget_candles: "Bitget candles", orderbook: "Bitget order book", bitget_perp: "Bitget perp and funding",
      bitget_margin_tiers: "Bitget margin tiers", yahoo_bars: "Yahoo stock bars", nasdaq_earnings: "Nasdaq earnings", fred_macro: "FRED macro",
      rss_news: "RSS news", sec_edgar: "SEC EDGAR", bitget_mcp: "Bitget US-stock MCP", bitget_open_interest: "Bitget perp open interest", cboe_options: "Cboe options quotes", bitget_wallet_rwa: "Bitget Wallet RWA listing", bitget_signal: "Bitget signal skill", corporate_events: "Dividends, splits and Bitget notices",
    } as Record<string, string>,
    breaker: { NORMAL: "normal", COOLDOWN: "cooldown", HALTED: "halted" } as Record<string, string>,
    side: { long: "long", short: "short", buy: "buy", sell: "sell" } as Record<string, string>,
    feature: {
      basis_index_bps: "gap to fair value",
      basis_index_z: "how stretched that gap is",
      basis_index_d6h_bps: "how fast the gap moves",
      basis_native_bps: "gap to the last close",
      rv_24h: "day's volatility",
      rv_168h: "week's volatility",
      vol_pctl_90d: "volatility for this stock",
      trend_sma_pct: "trend",
      sma_slope_5d_pct: "trend's slope",
      liq_ratio: "trading activity",
      no_trade_share_24h: "how often it didn't trade",
      native_close_age_h: "time since the stock traded",
      hours_to_earnings: "time to earnings",
      hours_since_earnings: "time since earnings",
      macro_events_72h: "macro releases ahead",
      hours_to_fomc: "time to the Fed",
      news_count_24h: "news flow",
      vix_pctl_1y: "the VIX",
      curve_pctl_1y: "yield curve",
      dollar_20d_chg_pct: "the dollar",
      ten_year_20d_chg_bps: "10-year yield",
    } as Record<string, string>,
    takeHeadings: ["The call", "What matters most tonight", "What would change my mind", "What I'd watch"],
  },
  zh: {
    verdictName: { GO: "可以做", REDUCE_TO: "建议减仓", HEDGE: "建议对冲", NO_GO: "不建议做", REVIEW: "需要复核" },
    verdictHeadline: {
      GO: "可按你要求的仓位去做",
      REDUCE_TO: "建议减小仓位",
      HEDGE: "建议对冲，不必减仓",
      NO_GO: "按当前设定不建议做这笔交易",
      REVIEW: "先复核再决定",
    },
    verdictMeaning: {
      GO: "按你要求的仓位，所有检查都通过",
      REDUCE_TO: "想法本身成立，但只能做到所示的较小仓位",
      HEDGE: "仓位不变，用这只股票在 Bitget 的永续合约对冲一部分",
      REVIEW: "缺少或不清楚某些信息（止损、计划、账户规模）；补上后会重新计算",
      NO_GO: "触碰了硬性限制，按你的要求不能做，原因里会说明是哪一条",
    },
    cap: {
      regime: "市场状态",
      risk_budget: "风险预算",
      concentration: "集中度",
      exit_liquidity: "平仓流动性",
      stress: "压力测试",
      book_tail: "组合尾部风险",
    },
    rule: {
      book_tail: "组合尾部风险",
      circuit_breaker: "熔断",
      data_quality: "数据质量",
      exit_liquidity: "平仓流动性",
      liquidation: "强平",
      market_posture: "市场态势",
      position_size: "仓位大小",
      revenge_cooldown: "报复性交易冷静期",
      risk_budget: "风险预算",
      stop: "止损",
      written_plan: "书面计划",
    },
    bucket: {
      us_regular: "美股常规交易时段",
      us_pre: "美股盘前",
      us_post: "美股盘后",
      weeknight: "工作日夜间",
      friday_night: "周五夜间",
      weekend: "周末",
      sunday_night: "周日夜间",
      holiday: "美国节假日",
    },
    lesson: {
      worse_than_stress: "比压力情形更差",
      bad_tail: "尾部亏损",
      as_expected: "符合预期",
      good_tail: "尾部盈利",
      better_than_forecast: "好于预测",
      no_distribution: "无预测",
    },
    severity: { extreme: "极端", severe: "严重" } as Record<string, string>,
    impact: { high: "高", medium: "中", low: "低", none: "无", unread: "尚未解读" } as Record<string, string>,
    feed: {
      features: "计算特征", bitget_candles: "Bitget K 线", orderbook: "Bitget 订单簿", bitget_perp: "Bitget 永续与资金费率",
      bitget_margin_tiers: "Bitget 保证金档位", yahoo_bars: "Yahoo 正股行情", nasdaq_earnings: "Nasdaq 财报日历", fred_macro: "FRED 宏观数据",
      rss_news: "RSS 新闻", sec_edgar: "SEC EDGAR 文件", bitget_mcp: "Bitget 美股 MCP", bitget_open_interest: "Bitget 永续未平仓量", cboe_options: "Cboe 期权行情", bitget_wallet_rwa: "Bitget Wallet 代币化股票信息", bitget_signal: "Bitget 信号技能", corporate_events: "分红、拆股与 Bitget 公告",
    } as Record<string, string>,
    breaker: { NORMAL: "正常", COOLDOWN: "冷静期", HALTED: "已暂停" } as Record<string, string>,
    side: { long: "做多", short: "做空", buy: "买入", sell: "卖出" } as Record<string, string>,
    feature: {
      basis_index_bps: "与公允价值的差距",
      basis_index_z: "该差距被拉伸的程度",
      basis_index_d6h_bps: "差距变化的速度",
      basis_native_bps: "与上次收盘价的差距",
      rv_24h: "日波动率",
      rv_168h: "周波动率",
      vol_pctl_90d: "该股票的波动率水平",
      trend_sma_pct: "趋势",
      sma_slope_5d_pct: "趋势斜率",
      liq_ratio: "交易活跃度",
      no_trade_share_24h: "无成交的比例",
      native_close_age_h: "距股票上次成交的时间",
      hours_to_earnings: "距财报的时间",
      hours_since_earnings: "财报后经过的时间",
      macro_events_72h: "即将发布的宏观数据",
      hours_to_fomc: "距美联储会议的时间",
      news_count_24h: "新闻量",
      vix_pctl_1y: "VIX 恐慌指数",
      curve_pctl_1y: "收益率曲线",
      dollar_20d_chg_pct: "美元",
      ten_year_20d_chg_bps: "10 年期国债收益率",
    } as Record<string, string>,
    takeHeadings: ["结论", "今晚最重要的", "什么会改变我的看法", "我会盯着什么"],
  },
} as const;

export type StringGroup = keyof (typeof STRINGS)["en"];

/** Look up an entry in a shared group; unknown keys come back as a readable fallback. */
export function t<G extends StringGroup>(lang: Lang, group: G, key: string): string {
  const table = STRINGS[lang][group] as unknown as Record<string, string>;
  const fallback = STRINGS.en[group] as unknown as Record<string, string>;
  return table[key] ?? fallback[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** `tr(lang)(english, chinese)`: pick the sentence for this language. */
export const tr =
  (lang: Lang) =>
  (en: string, zh: string): string =>
    lang === "zh" ? zh : en;

/** Duration in hours, as `fmtHours` writes it but with localised units. */
export function fmtHoursL(h: number | null | undefined, lang: Lang): string {
  if (h == null || Number.isNaN(h)) return "—";
  if (lang !== "zh") {
    if (h >= 720) return "> 30 d";
    if (h >= 48) return `${(h / 24).toFixed(1)} d`;
    return `${h.toFixed(h < 10 ? 1 : 0)} h`;
  }
  if (h >= 720) return "> 30 天";
  if (h >= 48) return `${(h / 24).toFixed(1)} 天`;
  return `${h.toFixed(h < 10 ? 1 : 0)} 小时`;
}

/** Timestamp in the reader's language (same fields, localised month and zone names). */
export function fmtTimeL(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(lang === "zh" ? "zh-CN" : undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
}

/** Date and time with the year, in the reader's language (zh-CN when Chinese). */
export function fmtDateTimeL(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
}

/** Calendar date only, in the reader's language (zh-CN when Chinese). */
export function fmtDateL(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  // A bare YYYY-MM-DD is a calendar day, not an instant: read it in UTC so no zone moves it.
  const dayOnly = /^d{4}-d{2}-d{2}$/.test(iso);
  return d.toLocaleDateString(lang === "zh" ? "zh-CN" : "en-GB", dayOnly ? { dateStyle: "medium", timeZone: "UTC" } : { dateStyle: "medium" });
}
