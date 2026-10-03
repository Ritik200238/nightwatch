/**
 * Text written by the desk, the analyst or the agent, cleaned for a person to read.
 *
 * Why: the engine's words carry its own labels - [desk] source tags, REDUCE_TO, a cap's
 * code name, the name of a field. Those are for the number check and for the code, not
 * for the trader. The citations stay in their own data; the sentence loses the markers.
 */

const ZH_VERDICT: Record<string, string> = { REDUCE_TO: "建议减仓", NO_GO: "不建议做", GO: "可以做", HEDGE: "建议对冲", REVIEW: "需要复核" };
const CAP_EN: Record<string, string> = {
  risk_budget: "risk budget",
  concentration: "concentration",
  regime: "market state",
  exit_liquidity: "exit liquidity",
  stress: "stress",
  book_tail: "book tail",
};
const CAP_ZH: Record<string, string> = {
  risk_budget: "风险预算",
  concentration: "集中度",
  regime: "市场状态",
  exit_liquidity: "平仓流动性",
  stress: "压力测试",
  book_tail: "整体持仓尾部风险",
};

/** "[desk]", "[safest ways]": the section a figure came from, in square brackets. */
const SOURCE_TAG = /[ \t]*\[[A-Za-z][A-Za-z ]*\]/g;

export function stripSourceTags(text: string): string {
  return text.replace(SOURCE_TAG, "");
}

/** REDUCE_TO -> "REDUCE TO" (or its Chinese name), a cap's code name -> plain words, field names -> what they mean. */
export function plainText(text: string, lang: "en" | "zh" = "en"): string {
  let t = stripSourceTags(text ?? "");
  t = t.replace(/loss_p5_pct(?:\s*\((?:the\s+)?one-in-twenty loss\))?/g, lang === "zh" ? "二十分之一的亏损" : "one-in-twenty loss");
  t = t.replace(/\b(risk_budget|concentration|regime|exit_liquidity|stress|book_tail) cap (?:binds|holds)/g, (_m, k: string) =>
    lang === "zh" ? `${CAP_ZH[k]}上限生效` : `the ${CAP_EN[k]} limit holds the size down`,
  );
  t = t.replace(/\b(REDUCE_TO|NO_GO)\b/g, (m) => (lang === "zh" ? ZH_VERDICT[m] : m.replace("_", " ")));
  t = t.replace(/\b(risk_budget|exit_liquidity|book_tail)\b/g, (m) => (lang === "zh" ? CAP_ZH[m] : CAP_EN[m]));
  return t;
}

/** The hold options the ticket form sends to the API, as words a trader reads. */
export function holdLabel(kind: string, lang: "en" | "zh"): string {
  const en: Record<string, string> = {
    next_open: "Until the next US open",
    window_end: "Until the end of this session",
    through_weekend: "Through the weekend",
    hours: "A number of hours",
  };
  const zh: Record<string, string> = {
    next_open: "持有到下一个美股开盘",
    window_end: "持有到本交易时段结束",
    through_weekend: "持有过周末",
    hours: "指定小时数",
  };
  return (lang === "zh" ? zh : en)[kind] ?? kind.replace(/_/g, " ");
}

function sentence(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

/** Gate rule names as the server prints them ("market posture"), as short plain labels. */
const RULE_LABEL: Record<string, { en: string; zh: string }> = {
  "market posture": { en: "Market looks hostile", zh: "市场环境不利" },
  "written plan": { en: "Plan is incomplete", zh: "计划不完整" },
  stop: { en: "Stop", zh: "止损" },
  "position size": { en: "Position size", zh: "仓位大小" },
  "risk budget": { en: "Risk budget", zh: "风险预算" },
  "exit liquidity": { en: "Exit liquidity", zh: "平仓流动性" },
  liquidation: { en: "Liquidation", zh: "强平" },
  "data quality": { en: "Data quality", zh: "数据质量" },
  "circuit breaker": { en: "Circuit breaker", zh: "熔断" },
  "revenge cooldown": { en: "Cooldown", zh: "冷静期" },
  "book tail": { en: "Whole-book tail risk", zh: "整体持仓尾部风险" },
};

/** One verdict reason as a plain one-line sentence. The server writes "market posture:
 *  hostile regime (size multiplier 0.50); ..." - a rule name and a machine clause - which
 *  reads as a leaked variable at headline size. Known shapes are rewritten; anything else
 *  keeps its words with the first letter capitalised. */
export function plainReason(text: string, lang: "en" | "zh" = "en"): string {
  const t = plainText(text, lang).trim();
  const m = /^([a-z][a-z ]*?):\s*(.+)$/.exec(t);
  if (!m) return sentence(t);
  const key = m[1].trim();
  const rest = m[2].trim();
  const label = RULE_LABEL[key];
  if (key === "market posture") {
    const mult = /size multiplier ([\d.]+)/.exec(rest);
    if (/hostile regime/.test(rest) && mult) {
      const x = Number(mult[1]);
      if (Number.isFinite(x)) {
        const pct = Math.round(x * 100);
        if (lang === "zh") return pct === 50 ? "市场环境不利：仓位减半" : `市场环境不利：仓位降至 ${pct}%`;
        return pct === 50 ? "Market looks hostile: entries are halved" : `Market looks hostile: entries are cut to ${pct}%`;
      }
    }
    if (/regime unknown/.test(rest)) return lang === "zh" ? "无法判断市场状态：历史数据不足" : "Market state unknown: not enough history";
  }
  if (key === "written plan") {
    const miss = /^missing (.+)$/.exec(rest);
    if (miss) {
      const parts = miss[1].split(/,\s*/);
      if (lang === "zh") return `计划不完整：缺少${parts.map((p) => (p === "thesis" ? "理由" : p === "invalidation" ? "失效条件" : p)).join("和")}`;
      return `Plan is incomplete: add your ${parts.join(" and ")}`;
    }
  }
  if (label) return `${lang === "zh" ? label.zh : label.en}${lang === "zh" ? "：" : ": "}${lang === "zh" ? rest : sentence(rest)}`;
  return sentence(t);
}

/** A sizing cap's explanation. The server writes it in English; the shapes it uses are fixed. */
export function capDetail(detail: string, lang: "en" | "zh"): string {
  if (lang !== "zh") return detail;
  let m: RegExpExecArray | null;
  if ((m = /^worst severe preset ([+-]?[\d.]+)% of notional; (?:approximately )?the largest size (?:whose loss stays|within) (?:inside )?([\d.]+)% of equity$/.exec(detail)))
    return `最严重的压力情景为仓位的 ${m[1]}%；亏损不超过账户权益 ${m[2]}% 的最大仓位`;
  if ((m = /^largest size whose worst severe loss stays inside ([\d.]+)% of equity$/.exec(detail))) return `最严重压力情景的亏损不超过账户权益 ${m[1]}% 的最大仓位`;
  if ((m = /^largest size whose book-wide one-in-twenty loss stays inside ([\d.]+)% of equity$/.exec(detail))) return `整体持仓二十分之一的亏损不超过账户权益 ${m[1]}% 的最大仓位`;
  if ((m = /^largest size the live book absorbs within (\d+) bps$/.exec(detail))) return `实时盘口在 ${m[1]} bps 以内能承接的最大仓位`;
  if ((m = /^regime size multiplier ([\d.]+) on the requested size$/.exec(detail))) return `按市场状态对申请仓位乘以 ${m[1]}`;
  if ((m = /^max ([\d.]+)% of equity in one name, and ([\d,]+) of it is already held$/.exec(detail))) return `单一标的最多占账户权益 ${m[1]}%，其中已持有 ${m[2]}`;
  if ((m = /^max ([\d.]+)% of equity in one name$/.exec(detail))) return `单一标的最多占账户权益 ${m[1]}%`;
  if (detail === "no order book") return "没有盘口数据";
  if (detail === "needs equity") return "需要账户权益";
  if (detail === "needs equity and a stop or analog distribution") return "需要账户权益，以及止损或历史相似分布";
  if (detail === "no stress presets available") return "没有可用的压力预设";
  if (detail === "needs equity to bound the stress loss") return "需要账户权益才能限定压力亏损";
  return detail;
}

/** The circuit breaker's one-line reasons, whose shapes are fixed server-side. */
export function breakerReason(r: string, lang: "en" | "zh"): string {
  if (lang !== "zh") return r;
  let m: RegExpExecArray | null;
  if ((m = /^(.+) loss ([\d,.-]+) has reached the ([\d,.]+) limit \((\d+) trades\)$/.exec(r))) return `${m[1]} 亏损 ${m[2]} 已达 ${m[3]} 限额（${m[4]} 笔交易）`;
  if ((m = /^(.+) loss ([\d,.-]+) is (\d+%) of the ([\d,.]+) limit$/.exec(r))) return `${m[1]} 亏损 ${m[2]}，占 ${m[4]} 限额的 ${m[3]}`;
  if ((m = /^(\d+) losing trades in a row$/.exec(r))) return `连续亏损 ${m[1]} 笔`;
  if (r === "account equity not given, so only the losing streak is checked") return "未提供账户权益，所以只检查连续亏损";
  if (r === "no trades marked as taken yet") return "还没有标记为已执行的交易";
  if (r === "no taken trade has matured yet") return "已执行的交易都还没到期";
  if ((m = /^within every loss limit(?:; (.+) at ([\d,.-]+))?$/.exec(r))) return m[1] ? `在所有亏损限额之内；${m[1]} 为 ${m[2]}` : "在所有亏损限额之内";
  return r;
}
