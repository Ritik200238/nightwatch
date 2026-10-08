"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Figure as Stat, OpenSection as Section, PageHead, PROOF_STACK, PROOF_WIDTH, ScrollTable } from "@/components/proof-page";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type ChatCheck, type DataSource, type VerifyResponse } from "@/lib/api";
import { useLang } from "@/lib/lang";

const REPO = "https://github.com/Ritik200238/nightwatch";
const VIDEO = "https://youtu.be/7R6LNyro4oM";

type Row = { ask: [string, string]; answer: [string, string]; check: { href: string; label: [string, string]; external?: boolean }[] };

/** What the handbook asks for this track, and the one place that answers it. Wording is plain
 *  on purpose: each answer names something a reader can open, not a claim to take on trust. */
const ROWS: Row[] = [
  {
    ask: ["Decision Stress Testing, in order: retrieve similar past scenarios, show their distribution, run preset stress tests", "决策压力测试，按顺序：检索相似的历史情景、给出结果分布、运行预设压力测试"],
    answer: [
      "Type a trade; the report shows the past moments most like it, what followed them over the same hold, then preset stress cases (closed-window gaps, earnings gaps, volatility spike, thin book, unable to exit, real crash replays), then a sized verdict.",
      "输入一笔交易；报告依次给出最相似的历史时刻、相同持有期内随后发生了什么、预设压力情景（休市跳空、财报跳空、波动飙升、盘口变薄、无法平仓、真实崩盘重演），最后是带仓位的结论。",
    ],
    check: [
      { href: "/", label: ["Open the desk", "打开交易台"] },
      { href: `${REPO}#one-complete-research-task-start-to-finish`, label: ["A full worked example", "完整示例"], external: true },
    ],
  },
  {
    ask: ["A complete research task, question to actionable insight", "一次完整的研究任务：从问题到可执行结论"],
    answer: [
      "One typed sentence runs the whole chain and ends in a decision (GO, REDUCE TO, HEDGE, REVIEW or NO GO) with the live exit cost and the leverage level where liquidation becomes likely. The human still decides; no order is ever placed.",
      "一句话即可跑完整条链，并给出结论（GO、REDUCE TO、HEDGE、REVIEW 或 NO GO），附实时平仓成本和可能爆仓的杠杆水平。最终仍由人决定，不会下任何订单。",
    ],
    check: [
      { href: VIDEO, label: ["Demo video, 2:22", "演示视频（2:22）"], external: true },
      { href: `${REPO}#one-complete-research-task-start-to-finish`, label: ["Written walkthrough", "文字演示"], external: true },
    ],
  },
  {
    ask: ["Feature depth: number and effectiveness of data sources and skill integrations", "功能深度：数据源与技能集成的数量和有效性"],
    answer: [
      "Twenty-one data sources, each listed with its real row count and freshness: Bitget candles, order books, perp margin tiers, open interest and the US-stock data service, plus SEC filings, macro, options and news. Each source says what it can change in an answer. A read-only MCP server and a skill file let other agents call the same check.",
      "二十一个数据源，逐一列出真实行数与新鲜度：Bitget K 线、订单簿、永续保证金档位、持仓量和美股数据服务，以及 SEC 公告、宏观、期权和新闻。每个来源都写明它能改变答案的哪一部分。只读 MCP 服务器与技能文件让其他智能体也能调用同一检查。",
    ],
    check: [
      { href: "/sources", label: ["Live status of every feed", "每个数据源的实时状态"] },
      { href: `${REPO}#talk-to-it-however-you-want`, label: ["MCP and skill setup", "MCP 与技能接入"], external: true },
    ],
  },
  {
    ask: ["Research quality", "研究质量"],
    answer: [
      "Every verdict is written down, hash-chained and anchored in Bitcoin, then scored against what happened. The forecasts that went past their line are listed in public. Our own studies are published with the ones that failed, after correcting for testing many questions at once.",
      "每个结论都会被记录、做哈希链并锚定到比特币，之后与实际结果对照评分。越过自身警戒线的预测会公开列出。我们自己的研究连同失败的结果一并公开，并已校正了同时检验多个问题带来的偏差。",
    ],
    check: [
      { href: "/calibration", label: ["Scored forecasts", "已评分的预测"] },
      { href: "/wrong", label: ["Published misses", "公开的失误"] },
      { href: "/studies", label: ["Internal studies, failures included", "内部研究（含失败）"] },
      { href: "/api/verify", label: ["Verdict chain, recomputed on request", "结论链（按需重新计算）"], external: true },
    ],
  },
  {
    ask: ["Language fluency (LUI)", "语言交互（LUI）的流畅度"],
    answer: [
      "Trades can be typed in plain English or 中文, with leverage, stops, existing holdings and messy phrasing. The reader says what it understood, asks for any missing field instead of guessing, and its accuracy is tested blind with the misses published.",
      "可以用日常英文或中文输入交易，包括杠杆、止损、已有持仓和不规范的说法。系统会复述它的理解，缺少字段时会询问而不是猜测，并用盲测检验准确度，失误也会公开。",
    ],
    check: [
      { href: "/studies", label: ["Blind test of the chat reader", "聊天解析的盲测"] },
      { href: "/", label: ["Try it in either language", "用任一语言试试"] },
    ],
  },
  {
    ask: ["A clear thesis for a concrete user", "面向具体用户的清晰主张"],
    answer: [
      "Built for retail and semi-professional traders who hold tokenized US stocks on Bitget through the US close. The thesis: before capital is committed, judge a trade by what followed the most similar past moments, and let deterministic code, not the AI, produce every number.",
      "面向在美股收盘后仍持有 Bitget 代币化美股的散户与半专业交易者。主张：在投入资金之前，用最相似历史时刻之后发生的事来判断交易，并由确定性代码而不是 AI 产生每一个数字。",
    ],
    check: [{ href: `${REPO}#who-it-is-for-and-the-idea-behind-it`, label: ["Who it is for, and why", "适用对象与理由"], external: true }],
  },
];

export default function JudgesPage() {
  const { tx, lang } = useLang();
  const zh = lang === "zh";
  const [chain, setChain] = useState<VerifyResponse | null>(null);
  const [chat, setChat] = useState<ChatCheck | null>(null);
  const [sources, setSources] = useState<DataSource[] | null>(null);

  useEffect(() => {
    let live = true;
    void api.verify().then((r) => live && setChain(r)).catch(() => undefined);
    void api.chatCheck().then((r) => live && setChat(r)).catch(() => undefined);
    void api.sources().then((r) => live && setSources(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  return (
    <div className={`${PROOF_WIDTH} ${PROOF_STACK}`}>
      <PageHead
        title={tx("For judges", "给评审")}
        intro={tx(
          "What this track asks for, and the page that answers each point. Nothing here asks you to take our word for it.",
          "这个赛道要求什么，以及回答每一项的页面。这里没有任何需要你直接相信我们的内容。",
        )}
      />

      <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
        <Stat
          label={tx("Verdicts on the chain", "链上的结论数")}
          value={chain ? chain.checked.toLocaleString() : "…"}
          hint={chain ? (chain.ok ? tx("no break", "无断裂") : tx("break found", "发现断裂")) : undefined}
          tone={chain ? (chain.ok ? "good" : "critical") : "muted"}
        />
        <Stat
          label={tx("Anchored in Bitcoin", "已锚定到比特币")}
          value={chain && chain.anchors != null ? `${chain.anchored_in_bitcoin ?? 0} / ${chain.anchors}` : "…"}
          hint={tx("daily heads", "每日链头")}
        />
        <Stat
          label={tx("Chat reader, blind test", "聊天解析盲测")}
          value={chat?.available ? `${chat.cases_ok} / ${chat.cases}` : "…"}
          hint={chat?.available ? tx(`${chat.fields_ok} of ${chat.fields} fields`, `${chat.fields_ok} / ${chat.fields} 个字段`) : undefined}
        />
        <Stat label={tx("Data sources", "数据源")} value={sources ? String(sources.length) : "…"} hint={tx("each with its live status", "均显示实时状态")} />
      </div>

      <Section title={tx("The handbook, point by point", "逐项对照评审要求")} subtitle={tx("Each row ends in something you can open.", "每一行都对应一个可以直接打开的页面。")}>
        <ScrollTable>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[26%]">{tx("What is asked", "要求")}</TableHead>
                <TableHead>{tx("How Nightwatch answers", "Nightwatch 的回答")}</TableHead>
                <TableHead className="w-[24%]">{tx("Check it", "查看")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ROWS.map((r) => (
                <TableRow key={r.ask[0]} className="align-top">
                  <TableCell className="whitespace-normal font-medium">{zh ? r.ask[1] : r.ask[0]}</TableCell>
                  <TableCell className="whitespace-normal text-muted-foreground">{zh ? r.answer[1] : r.answer[0]}</TableCell>
                  <TableCell className="whitespace-normal">
                    <ul className="space-y-1">
                      {r.check.map((c) => (
                        <li key={c.href}>
                          {c.external ? (
                            <a href={c.href} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center underline underline-offset-2 hover:text-foreground">
                              {zh ? c.label[1] : c.label[0]}
                            </a>
                          ) : (
                            <Link href={c.href} className="inline-flex min-h-10 items-center underline underline-offset-2 hover:text-foreground">
                              {zh ? c.label[1] : c.label[0]}
                            </Link>
                          )}
                        </li>
                      ))}
                    </ul>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ScrollTable>
      </Section>

      <Section title={tx("What it does not claim", "我们不声称什么")}>
        <ul className="t-body max-w-prose list-disc space-y-2 pl-5 text-muted-foreground">
          <li>{tx("It does not predict direction. We measured that and found no edge, so it sizes risk instead.", "它不预测方向。我们测过，没有发现优势，所以它只做风险定仓。")}</li>
          <li>{tx("It has no real-money record and no proven user base. The usage page shows what the demo has seen.", "它没有真金白银的记录，也没有经证实的用户群。用量页面显示的是演示站点所见到的情况。")}</li>
          <li>{tx("It never places an order. The human decides.", "它从不下单。决定权在人。")}</li>
          <li>
            {tx(
              "Bitget's own US-stock data service has returned errors since 5 Oct. The sources page says so, and reports say the data is unavailable instead of guessing.",
              "Bitget 自己的美股数据服务自 10 月 5 日起一直返回错误。数据源页面已注明，报告会写明数据不可用，而不是猜测。",
            )}
          </li>
        </ul>
      </Section>

      <Section title={tx("Run the checks yourself", "自己动手验证")}>
        <p className="t-body max-w-prose text-muted-foreground">{tx("One command recomputes the public claims from the live API:", "一条命令即可根据实时接口重新计算公开的结论：")}</p>
        <pre className="mt-3 overflow-x-auto rounded-md border border-border bg-muted/40 p-3 text-[13px]">python scripts/verify_live.py</pre>
        <p className="t-body mt-3 text-muted-foreground">
          <a href={`${REPO}/blob/main/scripts/verify_live.py`} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center underline underline-offset-2 hover:text-foreground">
            {tx("Source on GitHub", "GitHub 上的源码")}
          </a>
        </p>
      </Section>
    </div>
  );
}
