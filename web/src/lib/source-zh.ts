/** Chinese names for the data feeds, keyed by the API's stable `key`. The server writes
 *  these rows in English; the page shows these when the language is 中文. A feed with no
 *  entry keeps its English text rather than showing nothing. */

import type { DataSource } from "./api";

const ZH: Record<string, { label: string; what: string; cadence: string }> = {
  bitget_bars: { label: "Bitget 行情", what: "代币和永续合约的 K 线、盘口、资金费率", cadence: "盘口每 30 秒，K 线每 5 分钟" },
  yahoo: { label: "Yahoo Finance", what: "美股正股自身的小时 K 线，用于公允价值和价差", cadence: "美股开市时每小时" },
  nasdaq: { label: "Nasdaq 财报日历", what: "财报日历：日期、盘前或盘后、预期值和实际值", cadence: "每 6 小时" },
  corporate: { label: "股息与拆股", what: "除息日和拆股（Nasdaq、Yahoo Finance）以及 Bitget 交易所公告", cadence: "每 12 小时" },
  fred: { label: "FRED 宏观数据", what: "FOMC、CPI、就业等数据发布时间；VIX、收益率曲线、美元、10 年期国债", cadence: "每 6 小时" },
  rss: { label: "新闻（RSS）", what: "按代币标注的新闻标题，用于第二意见", cadence: "每 30 分钟" },
  sec_edgar: { label: "SEC EDGAR 文件", what: "8-K、6-K、10-Q、10-K 文件，精确到被受理的那一秒", cadence: "每 4 小时" },
  bitget_oi: { label: "Bitget 永续合约未平仓量", what: "各代币 USDT 永续合约的未平仓量，及其 24 小时变化（对比本交易台自己记录的读数）", cadence: "按需读取，每个代币缓存 5 分钟" },
  cboe_options: { label: "Cboe 期权报价", what: "延迟约 15 分钟的标的期权链：平值隐含波动率给出市场预期的波动幅度，与本交易台自己的二十分之一损失并列显示", cadence: "后台每小时，每个代币缓存 30 分钟" },
  bitget_wallet_rwa: { label: "Bitget Wallet 代币化股票列表", what: "每只代币化股票是否在线、所在交易时段、暂停或提醒文字，以及单笔订单限额", cadence: "后台每小时，每个代币缓存 30 分钟" },
  bitget_mcp: { label: "Bitget 美股数据", what: "标的实时报价、分析师评级和目标价、内部人交易、市场恐慌与贪婪指数", cadence: "每个代币每小时，仅存于内存" },
  bitget_equity_calendar: { label: "Bitget：财报日历", what: "公司自己公布的下次财报日期，以及盘前还是盘后发布，并与 Nasdaq 日历交叉核对", cadence: "每个代币每小时最多一次，仅存于内存" },
  bitget_equity_fundamental_ratios: { label: "Bitget：估值比率", what: "最近一个报告期的市盈率、市净率、市销率、过去一年股息率和市值", cadence: "每个代币每小时最多一次，仅存于内存" },
  bitget_equity_fundamental_dividends: { label: "Bitget：股息", what: "下一次除息日和金额，或最近一次已发放的股息", cadence: "每个代币每小时最多一次，仅存于内存" },
  bitget_equity_estimates_consensus: { label: "Bitget：分析师一致预期", what: "分析师一致目标价及其最高值和最低值", cadence: "每个代币每小时最多一次，仅存于内存" },
  bitget_equity_profile: { label: "Bitget：公司简介", what: "行业、板块、交易所、CEO 和员工人数", cadence: "每个代币每小时最多一次，仅存于内存" },
  bitget_equity_price_quote: { label: "Bitget：实时报价", what: "标的股票的实时价格和前收盘价，价差和“代币与股票的差距”都依赖它", cadence: "每个代币每小时，仅存于内存" },
  bitget_equity_estimates_price_target: { label: "Bitget：分析师评级和目标价", what: "各家机构最新的评级和目标价（近 90 天）", cadence: "每个代币每小时，仅存于内存" },
  bitget_equity_ownership_insider_trading: { label: "Bitget：内部人交易", what: "近 90 天公开市场上的内部人买入和卖出", cadence: "每个代币每小时，仅存于内存" },
  bitget_sentiment_market_fear_greed: { label: "Bitget：市场恐慌与贪婪", what: "美股市场情绪指数：现在、一周前和一个月前", cadence: "每个代币每小时，仅存于内存" },
  bitget_signal: { label: "Bitget 信号技能", what: "来自技术分析工具的 4 小时 RSI，仅在与本交易台自己的 RSI 一致时显示", cadence: "每个代币每小时，仅存于内存" },
};

/** The row with its label, description and cadence in the chosen language. */
export function localSource(r: DataSource, zh: boolean): DataSource {
  const t = zh ? ZH[r.key] : undefined;
  return t ? { ...r, label: t.label, what: t.what, cadence: t.cadence } : r;
}

/** Common status words inside a feed's `latest_label`, which the server writes in English. */
export function localLatest(label: string | null, zh: boolean): string | null {
  if (!label || !zh) return label;
  return label
    .replace(/^([\d,]+) order-book snapshots$/, "$1 个盘口快照")
    .replace(/^([\d,]+) tokens read$/, "已读取 $1 个代币")
    .replace(/^([\d,]+) tokens with current street data$/, "$1 个代币有最新的分析师数据")
    .replace(/^none (read|fetched) yet$/, "尚未读取")
    .replace(/^unavailable/, "不可用")
    .replace(/ since (\d\d:\d\d) UTC/, " 自 $1 UTC")
    .replace(/\(HTTP (\d+)\)/, "（HTTP $1）")
    .replace(/; ([\d,]+) tokens serve older data$/, "；$1 个代币用的是较早的数据")
    .replace(/^([\d,]+) tokens with data; ([\d,]+) not answering$/, "$1 个代币有数据；$2 个没有响应")
    .replace(/^([\d,]+) tokens with data$/, "$1 个代币有数据")
    .replace(/^not answering for ([\d,]+) of ([\d,]+) tokens$/, "$2 个代币中有 $1 个没有响应")
    .replace(/^([\d,]+) tokens with an options chain$/, "$1 个代币有期权链")
    .replace(/^([\d,]+) of ([\d,]+) tools answering$/, "$2 个工具中有 $1 个有响应")
    .replace(/^not fetched yet$/, "尚未获取")
    .replace(/^not delivered yet$/, "尚未返回数据")
    .replace(/^answers, with nothing for these tokens$/, "服务有响应，但这些代币没有数据")
    .replace(/^furthest scheduled report$/, "最远的已排期财报")
    .replace(/^furthest dated event$/, "最远的已排期事件")
    .replace(/^furthest scheduled release$/, "最远的已排期发布")
    .replace(/^Bitget US-stock data: unavailable/, "Bitget 美股数据：不可用");
}
