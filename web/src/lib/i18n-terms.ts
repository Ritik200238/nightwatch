/** Translators for the short, closed-vocabulary phrases the server sends and the client
 *  displays (state words, preset names, evidence sources). Free-form sentences the server
 *  writes are not handled here; anything not recognised comes back unchanged. */
import type { Lang } from "./i18n";

/** 1st, 2nd, 3rd, 4th ... 11th, 12th, 13th ... 21st, 61st. Chinese reads "第 N 百分位". */
export function ordinal(n: number, lang: Lang = "en"): string {
  if (lang === "zh") return `第${n}`;
  const v = Math.abs(Math.round(n));
  const mod100 = v % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  const suffix = v % 10 === 1 ? "st" : v % 10 === 2 ? "nd" : v % 10 === 3 ? "rd" : "th";
  return `${n}${suffix}`;
}

/** "the 61st percentile" / "第 61 百分位". */
export function percentileText(n: number, lang: Lang): string {
  return lang === "zh" ? `第 ${n} 百分位` : `${ordinal(n)} percentile`;
}

const WORDS: Record<string, string> = {
  // regime label
  favorable: "有利",
  mixed: "好坏参半",
  hostile: "不利",
  unknown: "未知",
  // volatility / trend / liquidity state
  calm: "平静",
  normal: "正常",
  turbulent: "动荡",
  sideways: "横盘",
  up: "上行",
  down: "下行",
  surging: "放量",
  thinning: "变薄",
  // book source
  live: "实时",
  recorded: "记录的",
};

/** A single state word (regime, volatility, trend, liquidity, book source). */
export function stateWord(lang: Lang, w: string | null | undefined): string {
  if (!w) return "—";
  return lang === "zh" ? (WORDS[w] ?? w) : w;
}

const CLUSTER: Record<string, string> = {
  calm: "平静",
  turbulent: "动荡",
  "ordinary vol": "波动正常",
  "token rich vs fair value": "代币价格高于公允价值",
  "token cheap vs fair value": "代币价格低于公允价值",
  "basis near normal": "价差接近正常",
  "above trend": "高于趋势",
  "below trend": "低于趋势",
  "flat trend": "趋势持平",
  thin: "流动性偏薄",
  unremarkable: "无明显特征",
};

/** The regime-map description, e.g. "calm, basis near normal, flat trend". */
export function regimeDescription(lang: Lang, d: string | null | undefined): string {
  if (!d) return "";
  if (lang !== "zh") return d;
  return d
    .split(", ")
    .map((p) => CLUSTER[p] ?? p)
    .join("，");
}

const SOURCES: Record<string, string> = {
  "stress presets": "压力预设",
  "stress presets + analogs": "压力预设和相似时刻",
  "analog cohort": "相似时刻样本",
  "baseline test": "基线检验",
  "order book": "盘口",
  "book archive": "盘口存档",
  "Monte Carlo": "蒙特卡洛模拟",
  portfolio: "持仓组合",
  "regime map": "市场状态图",
  "post-mortems": "复盘",
  liquidation: "强平",
  "sizing caps": "仓位上限",
  "size sweep": "仓位扫描",
  "hedge quote": "对冲报价",
  "failure modes": "失败模式",
  "position arithmetic": "仓位算术",
  "snapshot labels": "快照标签",
};

/** Where a claim came from ("analog cohort", "order book"...). */
export function sourceName(lang: Lang, s: string | null | undefined): string {
  if (!s) return "";
  if (lang !== "zh") return s;
  return s
    .split(" + ")
    .map((p) => SOURCES[p] ?? p)
    .join(" + ");
}

/** The basis the gate measured risk on. */
export function riskBasis(lang: Lang, b: string | null | undefined): string {
  if (!b) return "";
  if (lang !== "zh") return b;
  if (b === "distance to stop") return "到止损的距离";
  if (b === "analog 5th-percentile loss") return "相似时刻第 5 百分位亏损";
  return b;
}

/** Stress-preset names: "Replay: <crisis>", "Volatility spike ×3", "Closed-window gap, 95th percentile"... */
export function presetName(lang: Lang, name: string, nameZh?: string | null): string {
  if (lang !== "zh") return name;
  if (nameZh) return nameZh; // the backend's own Chinese name, from the same map the chat uses
  let m: RegExpMatchArray | null;
  if (name.startsWith("Replay: ")) return `重演：${name.slice(8)}`;
  if ((m = name.match(/^Closed-window gap, (\d+)(?:st|nd|rd|th) percentile$/))) return `休市期间跳空，第 ${m[1]} 百分位`;
  if ((m = name.match(/^Basis blowout, (\d+)(?:st|nd|rd|th) percentile of closed hours$/))) return `价差急剧扩大，休市时段第 ${m[1]} 百分位`;
  if ((m = name.match(/^Volatility spike ×(\d+)$/))) return `波动率飙升 ×${m[1]}`;
  if (name === "Earnings gap: worst observed") return "财报跳空：历史最坏";
  if (name === "Earnings gap: typical adverse") return "财报跳空：典型不利情形";
  if (name === "Liquidity drought (book depth ÷ 5)") return "流动性枯竭（盘口深度 ÷ 5）";
  if (name === "Cannot exit for 24h during an adverse move") return "不利行情中 24 小时无法平仓";
  if (name === "Funding spike on the hedge leg") return "对冲腿资金费率飙升";
  if (name === "reverse") return "反向";
  return name;
}
