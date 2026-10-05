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
    .replace(/^furthest scheduled report$/, "最远的已排期财报")
    .replace(/^furthest dated event$/, "最远的已排期事件")
    .replace(/^furthest scheduled release$/, "最远的已排期发布")
    .replace(/^Bitget US-stock data: unavailable/, "Bitget 美股数据：不可用");
}
