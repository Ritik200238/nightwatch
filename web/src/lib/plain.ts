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
  regime: "market-conditions",
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
  // The engine's own shorthand, in the words a trader would use.
  t = t.replace(/\banalog (?:5th-percentile|p5) loss\b/g, lang === "zh" ? "相似历史时刻的二十分之一亏损" : "one-in-twenty loss from past moments");
  t = t.replace(/\bregime (cap|limit)\b/g, lang === "zh" ? "市场状态上限" : "market-conditions limit");
  return t;
}

/** One gate rule's reason, which the server writes in English, in the reader's language.
 *  English is only cleaned of shorthand; Chinese is translated from the fixed shapes the gate uses. */
export function ruleReason(reason: string, lang: "en" | "zh" = "en"): string {
  const t = plainText(reason, lang);
  if (lang !== "zh") return t;
  let m: RegExpExecArray | null;
  const basis = (b: string) => (/^(?:distance to stop|stop distance)$/.test(b.trim()) ? "到止损的距离" : b.trim());
  if ((m = /^thesis and invalidation stated(?: \(but the invalidation is (\d+)% away, too far to bind\))?$/.exec(t))) return m[1] ? `已写明理由和“错在哪里”（但这条线距现价 ${m[1]}%，太远，起不到约束作用）` : "已写明理由和“错在哪里”";
  if ((m = /^missing (.+)$/.exec(t))) {
    const parts = m[1].split(/,\s*/).map((p) => (p === "thesis" ? "理由" : p === "invalidation" ? "“错在哪里”" : p));
    return `缺少${parts.join("和")}`;
  }
  if ((m = /^no stop (?:given|order); sized on the 5th percentile \(([+-][\d.]+)%\) instead(?:; your 'wrong if' line is (\d+)% away, but it is an invalidation, not a stop order)?$/.exec(t)))
    return `没有止损单；按第 5 百分位（${m[1]}%）定仓位${m[2] ? `；你的“错在哪里”那条线距现价 ${m[2]}%，它是判断失效的条件，不是止损单` : ""}`;
  if (t === "no stop price and no analog distribution to size on") return "没有止损价，也没有历史分布可用来定仓位";
  if (t === "stop is on the wrong side of entry") return "止损设在了入场价的错误一侧";
  if ((m = /^stop ([\d.]+)% away is tighter than ([\d.]+)% — inside normal hourly noise for this token$/.exec(t))) return `止损距现价 ${m[1]}%，比 ${m[2]}% 更近，落在这只代币正常的小时波动之内`;
  if ((m = /^stop ([\d.]+)% away - check it is a price for this token$/.exec(t))) return `止损距现价 ${m[1]}%，请确认这是这只代币的价格`;
  if ((m = /^stop ([\d.]+)% away is wider than ([\d.]+)%$/.exec(t))) return `止损距现价 ${m[1]}%，比 ${m[2]}% 更宽`;
  if ((m = /^stop ([\d.]+)% from entry$/.exec(t))) return `止损距入场价 ${m[1]}%`;
  if (t === "account equity not provided") return "没有提供账户规模";
  if ((m = /^position is ([\d.]+)% of equity \(limit ([\d.]+)%\)$/.exec(t))) return `仓位占账户 ${m[1]}%（上限 ${m[2]}%）`;
  if ((m = /^position is ([\d.]+)% of equity$/.exec(t))) return `仓位占账户 ${m[1]}%`;
  if (t === "cannot compute risk: no stop and no analog distribution") return "无法计算风险：没有止损，也没有历史分布";
  if ((m = /^risk ([\d,]+) \((.+)\) but equity unknown$/.exec(t))) return `风险 ${m[1]}（${basis(m[2])}），但不知道账户规模`;
  if ((m = /^risk ([\d.]+)% of equity \((.+)\) exceeds ([\d.]+)%$/.exec(t))) return `风险占账户 ${m[1]}%（${basis(m[2])}），超过上限 ${m[3]}%`;
  if ((m = /^risk ([\d.]+)% of equity \((.+)\)$/.exec(t))) return `风险占账户 ${m[1]}%（${basis(m[2])}）`;
  if ((m = /^losing exit (.+) inside the (\d+)h cooldown$/.exec(t))) return `${m[1]} 有一笔亏损平仓，仍在 ${m[2]} 小时冷静期内`;
  if (t === "no recent losing exit") return "最近没有亏损平仓";
  if (t === "inputs complete") return "输入数据完整";
  if ((m = /^minor flags: (.+)$/.exec(t))) return `轻微提示：${m[1]}`;
  if ((m = /^analysis inputs degraded: (.+)$/.exec(t))) return `分析输入数据不完整：${m[1]}`;
  if ((m = /^hostile regime \(size multiplier ([\d.]+)\); selective entries only$/.exec(t))) return `市场环境不利（仓位乘数 ${m[1]}），只做有选择的入场`;
  if (t === "regime unknown: not enough history") return "无法判断市场状态：历史数据不足";
  if ((m = /^regime (.+)$/.exec(t))) return `市场状态：${m[1]}`;
  if (t === "the live book cannot absorb this size at any price") return "实时盘口在任何价格都接不住这个仓位";
  if (t === "no order book available to cost the exit") return "没有盘口数据，无法估算平仓成本";
  if ((m = /^exit would cost (\d+) bps \(limit (\d+)\)$/.exec(t))) return `平仓成本约 ${m[1]} bps（上限 ${m[2]}）`;
  if ((m = /^exit costs (\d+) bps on the live book$/.exec(t))) return `按实时盘口，平仓成本约 ${m[1]} bps`;
  if ((m = /^no stored history for (.+); the book's tail is measured without it$/.exec(t))) return `${m[1]} 没有历史数据；整体尾部风险不含它`;
  if (t === "the book's history is measured; its limit is applied to the size") return "整体持仓的历史已计入；它的上限已用于仓位";
  return breakerReason(t, "zh");
}

/** The report's caveats are written in English by the engine; the shapes it uses are fixed. */
export function warningText(w: string, lang: "en" | "zh" = "en"): string {
  const t = plainText(w, lang);
  if (lang !== "zh") return t;
  let m: RegExpExecArray | null;
  const outage = (s: string) => s.replace(/ since (\d\d:\d\d) UTC/, " 自 $1 UTC").replace(/\(HTTP (\d+)\)/, "（HTTP $1）");
  if ((m = /^Bitget's US-stock data \(analysts, insiders, live quote\) is unavailable(.*); this report has no street section$/.exec(t)))
    return `Bitget 美股数据（分析师、内部人、实时报价）不可用${outage(m[1])}；本报告没有这部分内容`;
  if ((m = /^Bitget's US-stock data \(analysts, insiders, live quote\) is last good (.+?) ago(.*); it is context, not live, and is left out of the live-price checks$/.exec(t)))
    return `Bitget 美股数据（分析师、内部人、实时报价）最近一次有效数据在 ${m[1]} 前${outage(m[2])}；它只作背景参考，不是实时数据，也不参与实时价格检查`;
  if (t === "no order book available: exit cost and liquidity caps are unknown") return "没有盘口数据：平仓成本和流动性上限未知";
  if (t === "sensitivity sweep failed; the verdict above is unaffected") return "敏感性扫描失败；上面的结论不受影响";
  if (t === "not enough hourly history for a Monte Carlo over the horizon") return "小时级历史不足，无法在持有期内做蒙特卡洛模拟";
  if ((m = /^analog cohort for the (.+) horizon is below the minimum sample; verdict falls back to the stop for risk$/.exec(t))) return `${m[1]} 持有期的相似历史样本低于最低要求；结论改用止损来衡量风险`;
  if ((m = /^analog search refused: (.+)$/.exec(t))) return `相似历史检索未运行：${m[1]}`;
  if ((m = /^the native close fair value is built on \(([\d.]+)\) is ([+-]\d+) bps from Bitget's figure for the same close; one of them is wrong, so read the basis with care$/.exec(t)))
    return `公允价值所用的原生收盘价（${m[1]}）与 Bitget 对同一收盘价的数字相差 ${m[2]} bps；其中一个有误，解读价差时请小心`;
  if ((m = /^Bitget's calendar puts the next (\S+) earnings on (\S+) and Nasdaq's on (\S+) \((\d+) days? apart\); one of them is an estimate, so check the date before a hold that spans either$/.exec(t)))
    return `Bitget 日历把 ${m[1]} 下次财报定在 ${m[2]}，纳斯达克定在 ${m[3]}（相差 ${m[4]} 天）；其中一个是估算，持有期跨越任一日期前请先核对`;
  if ((m = /^The (\S+) perp looks crowded: (.+)\. A liquidation cascade has more to feed on; this did not change the size$/.exec(t)))
    return `${m[1]} 永续合约看起来过于拥挤：${m[2]}。连环强平的燃料更多；这没有改变仓位`;
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

/** The fixed sentences the verdict adds under a passing gate (advisories, the cap line), in Chinese.
 *  Null when the sentence is not one of them, so the caller falls through to its other shapes. */
function advisoryZh(t: string): string | null {
  let m: RegExpExecArray | null;
  if (t === "requested size is within every cap" || t === "Requested size is within every cap") return "所请求的仓位在所有上限之内";
  if ((m = /^(?:no stop given|no stop order|No stop given|No stop order): risk is sized on the calibrated 5th percentile, ([+-][\d.]+)% over the horizon(?:; your 'wrong if' line is (\d+)% away, but it is an invalidation, not a stop order)?$/.exec(t)))
    return `${/^no stop order/i.test(t) ? "没有止损单" : "没有设止损"}：风险按校准后的第 5 百分位（持有期内 ${m[1]}%）定仓位${m[2] ? `；你的“错在哪里”那条线距现价 ${m[2]}%，它是判断失效的条件，不是止损单` : ""}`;
  if ((m = /^Size held at ([\d,]+) USDT: (.+) \(requested ([\d,]+)\)\.?$/.exec(t))) {
    const why: Record<string, string> = {
      "the loss if the stop is hit would exceed the share of equity you allow at risk": "止损被触发时的亏损会超过你允许的风险占比",
      "more than that would put too much of your equity in one name": "再多就会让太大比例的账户权益集中在一个标的上",
      "the current market regime calls for a smaller position than requested": "当前市场状态要求比所请求的更小的仓位",
      "the worst severe stress scenario would cost more than the allowed share of equity at a larger size": "仓位再大，最严重压力情景的亏损会超过允许的账户权益占比",
      "a larger size would push the whole book's one-in-twenty loss past the allowed share of equity": "仓位再大，整体持仓二十分之一的亏损会超过允许的账户权益占比",
    };
    const book = /^the live order book can absorb only that much within the (\d+) bps exit-cost budget$/.exec(m[2]);
    const reason = book ? `实时盘口在 ${book[1]} bps 的平仓成本预算内只能承接这么多` : why[m[2]];
    if (reason) return `仓位限制在 ${m[1]} USDT：${reason}（你要求的是 ${m[3]}）`;
  }
  if (t === "thin trading: over a quarter of the last day had no trades, so volatility and the analogs lean on filled bars") return "成交稀薄：过去一天超过四分之一的时间没有成交，波动率和相似历史时刻依赖补齐的K线";
  if (t === "quieter than this token usually is at this time of week, which is a liquidity change rather than a weekend") return "比这只代币在一周中这个时段通常的状态更安静，这是流动性的变化，而不是周末效应";
  if (t === "the native stock has not printed for three days; fair value is older than usual") return "原生股票已三天没有成交；公允价值比平时更旧";
  if ((m = /^it moves with the rest of your book \(mean correlation ([\d.]+)\): this adds size, not diversification$/.exec(t))) return `它与你其余持仓同向波动（平均相关性 ${m[1]}）：这只是加大仓位，不是分散风险`;
  return null;
}

/** The "What would change it" notes, which the server writes in English from fixed shapes. */
export function sensitivityNote(note: string, lang: "en" | "zh" = "en"): string {
  if (lang !== "zh") return note;
  let m: RegExpExecArray | null;
  if ((m = /^no size is a GO while (.+) is unresolved$/.exec(note))) {
    const rule = (k: string) => RULE_LABEL[k.trim().replace(/_/g, " ")]?.zh ?? k.trim();
    return `在${m[1].split(",").map(rule).join("、")}还没解决之前，任何仓位都不是 GO`;
  }
  if ((m = /^no size is a GO: the (.+) cap stays below the request at every size$/.exec(note))) return `没有任何仓位可以做：在每个仓位下，${CAP_ZH[m[1].replace(/ /g, "_")] ?? m[1]}上限都低于所请求的仓位`;
  if ((m = /^the requested ([\d,]+) is a GO; room up to ([\d,]+)$/.exec(note))) return `所请求的 ${m[1]} 可以做；最多可到 ${m[2]}`;
  if ((m = /^a GO up to ([\d,]+), (\d+)% below the request$/.exec(note))) return `最高 ${m[1]} 可以做，比所请求的低 ${m[2]}%`;
  if ((m = /^the stop would have to come in from ([\d.]+)% to ([\d.]+)% for this size to fit the risk budget$/.exec(note))) return `止损需要从 ${m[1]}% 收近到 ${m[2]}%，这个仓位才符合风险预算`;
  return note;
}

/** The first line of "The case against this", from the verdict the desk reached. */
export function secondOpinionHead(head: string, lang: "en" | "zh" = "en"): string {
  if (lang !== "zh") return head;
  let m: RegExpExecArray | null;
  if (head === "The desk says no. If you disagree, this is what would have to be true:") return "系统的结论是不建议做。如果你不同意，下面这些情况必须成立：";
  if (head === "The desk cannot decide yet. What is already known:") return "系统暂时还无法下结论。目前已知的是：";
  if ((m = /^The desk says (.+)\. The strongest case against it:$/.exec(head))) {
    const v: Record<string, string> = { go: "可以做", "reduce to": "建议减仓", hedge: "建议对冲", review: "需要复核" };
    return `系统的结论是${v[m[1]] ?? m[1]}。最有力的反对理由：`;
  }
  return head;
}

/** One past call from "what happened last time", written by the journal in a fixed shape. */
export function lessonText(text: string, lang: "en" | "zh" = "en"): string {
  if (lang !== "zh") return text;
  const m = /^(\S+) (long|short) over (\d+)h from (\d+ \w+): (.*)$/.exec(text);
  if (!m) return text;
  const [, ticker, side, h, whenEn, rest] = m;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const dm = /^(\d+) (\w{3})/.exec(whenEn);
  const when = dm && MONTHS.includes(dm[2]) ? `${MONTHS.indexOf(dm[2]) + 1} 月 ${dm[1]} 日` : whenEn;
  let body = rest;
  let extra = "";
  let money = "";
  let r: RegExpExecArray | null;
  if ((r = /^(.*?)( It went through that level intraday, worst point (.+?), then came back\.| Worst point inside the window (.+?)\.)?( The desk cut the size from ([\d,]+) to ([\d,]+), which (avoided|cost) about ([\d,]+) USDT\.)?$/.exec(rest))) {
    body = r[1];
    if (r[3]) extra = `盘中曾跌穿这个水平，最差点 ${r[3]}，之后又回来了。`;
    else if (r[4]) extra = `窗口内最差点 ${r[4]}。`;
    if (r[5]) money = `系统把仓位从 ${r[6]} 降到 ${r[7]}，${r[8] === "avoided" ? "避免了" : "多亏了"}约 ${r[9]} USDT。`;
  }
  let b: RegExpExecArray | null;
  if ((b = /^it closed (\S+), below the (\S+) we sized against\.$/.exec(body))) body = `收于 ${b[1]}，低于当时定仓所依据的 ${b[2]}。`;
  else if ((b = /^it closed (\S+), above the (\S+) upper bound\.$/.exec(body))) body = `收于 ${b[1]}，高于 ${b[2]} 的上界。`;
  else if ((b = /^it closed (\S+), inside the (\S+) to (\S+) band\.$/.exec(body))) body = `收于 ${b[1]}，处于 ${b[2]} 到 ${b[3]} 的区间之内。`;
  else if ((b = /^the engine refused to forecast \(too few similar moments\)\. It closed (\S+)\.$/.exec(body))) body = `系统拒绝给出预测（相似时刻太少）。实际收于 ${b[1]}。`;
  else return text;
  return `${ticker} ${side === "long" ? "做多" : "做空"}，持有 ${h} 小时，自 ${when} 起：${body}${extra ? ` ${extra}` : ""}${money ? ` ${money}` : ""}`;
}

/** One verdict reason as a plain one-line sentence. The server writes "market posture:
 *  hostile regime (size multiplier 0.50); ..." - a rule name and a machine clause - which
 *  reads as a leaked variable at headline size. Known shapes are rewritten; anything else
 *  keeps its words with the first letter capitalised. */
export function plainReason(text: string, lang: "en" | "zh" = "en"): string {
  const t = plainText(text, lang).trim();
  if (lang === "zh") {
    const z = advisoryZh(t);
    if (z) return z;
  }
  const m = /^([a-z][a-z_ ]*?):\s*(.+)$/.exec(t);
  if (!m) return sentence(t);
  const key = m[1].trim().replace(/_/g, " ");
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
      const both = parts.includes("thesis") && parts.includes("invalidation");
      if (lang === "zh") {
        return both ? "计划不完整：缺少你的理由和“错在哪里”那一句" : parts.includes("thesis") ? "计划不完整：缺少你的理由" : "计划不完整：缺少“错在哪里”那一句";
      }
      return both
        ? "Plan is incomplete: your reason and 'wrong if' line are missing"
        : parts.includes("thesis")
          ? "Plan is incomplete: your reason is missing"
          : "Plan is incomplete: your 'wrong if' line is missing";
    }
  }
  // The words after the rule name are the gate's own English clause; in Chinese they go through the same
  // translation the gate list uses, so "position size: account equity not provided" is not half English.
  if (label) return `${lang === "zh" ? label.zh : label.en}${lang === "zh" ? "：" : ": "}${lang === "zh" ? ruleReason(rest, "zh") : sentence(rest)}`;
  return sentence(t);
}

/** A sizing cap's explanation. The server writes it in English; the shapes it uses are fixed. */
export function capDetail(detail: string, lang: "en" | "zh"): string {
  if (lang !== "zh") return plainText(detail, "en").replace(/\bregime multiplier\b/, "market-conditions multiplier");
  let m: RegExpExecArray | null;
  if ((m = /^([\d.]+)% of equity at risk over a ([\d.]+)% (analog p5 loss|stop distance)$/.exec(detail)))
    return `账户权益的 ${m[1]}% 作为风险，按${m[3] === "stop distance" ? "到止损的距离" : "相似历史时刻的二十分之一亏损"} ${m[2]}% 计算`;
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
