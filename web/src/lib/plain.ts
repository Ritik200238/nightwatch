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
