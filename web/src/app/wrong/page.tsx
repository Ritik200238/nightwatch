"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { LoadingRecord, PageHead, PlainBox, PROOF_WIDTH, ScrollTable } from "@/components/proof-page";
import { Term } from "@/components/term";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type MissesResponse, type VerifyResponse } from "@/lib/api";
import { useLang } from "@/lib/lang";
import { fmtPct, fmtUsd } from "@/lib/format";
import { fmtTimeL } from "@/lib/i18n";

/** Mistakes found in the desk itself, newest first. Each one changed a number a trader
 *  was shown; the fix is in the repository's history and the evidence in the notes. */
const FOUND_ZH: { when: string; what: string; fix: string }[] = [
  { when: "9月29日", what: "做空的仓位是按错误的一侧历史来计算的。“二十分之一”的亏损取自股价下跌，而下跌对做空是盈利，所以风控关卡、仓位上限和杠杆检查都是按做空最好的那些夜晚来评判的。", fix: "现在做空按股价上涨来计算：校准后的第 95 百分位，翻转后使用。报告会说明哪个方向会亏钱。" },
  { when: "9月29日", what: "那条亏损线在平静的夜晚仍然偏乐观：所有已评分的重演都是做多，换成做空重演后，最平静的三分之一有 7.8% 突破了该线，而不是 5%。", fix: "同样的 2,345 个夜晚改按做空重演。做空的亏损线现在取旧线与按做空自身结果拟合的新线中较保守的一个：整体 4.7%，最平静的三分之一为 5.7%，准确度不变。" },
  { when: "9月29日", what: "Bitget 的美股数据（分析师评级、内部人交易、实时股价）在所有实时报告里悄悄缺失。Bitget 服务器拒绝了本服务器 IPv4 地址上的新会话，报告便直接省略了这一部分。", fix: "API 现在改走 IPv6 连接；数据来源面板会显示当前有多少代币拥有这些数据。" },
  { when: "9月29日", what: "在工作日问“周末”，被当成到周一的六天持有，比交易台评分过的任何持有期都长，而回复里没有说明。", fix: "报告现在会说明它测量的是哪个周末，并给出该股票过去周五到周一的周末表现。" },
  { when: "9月29日", what: "文档里引用的研究数字，实时研究页面已不再支持：“24 个代币里一个都没有”变成了一个，t 统计量的符号也变了。", fix: "文档现在引用实时运行的结果，并且有一个脚本会在两者再次不一致时报错。" },
  { when: "9月29日", what: "一位中文用户写“我想周末拿点特斯拉”，每一轮都被问“做多还是做空？”，始终得不到回答。", fix: "“拿”“入手”“上车”“抄底”现在都会被理解为做多，追问时也会复述已经掌握的信息。" },
  { when: "9月28日", what: "做空从未被压力测试。所有预设都是下跌，所以 TSLA 做空的“百年一遇跳空”显示为 +7.4% 的盈利。", fix: "预设现在取自对仓位不利的那一侧尾部；同一个做空现在显示 −6.8%。" },
  { when: "更早", what: "原始历史的尾部太窄：有 8.5% 的结果低于所说的“二十分之一”线，而不是 5%。", fix: "每条尾部都按仅用已到期预测拟合的系数放宽；样本外已回到 5%。" },
  { when: "更早", what: "所有持有期共用一个尾部系数，掩盖了两个相反的误差：隔夜的尾部太窄，周末的尾部大约宽了一倍，导致周末仓位被白白削减了 43%。", fix: "每个持有期现在都有自己的系数。" },
];

const FOUND: { when: string; what: string; fix: string; open?: boolean }[] = [
  {
    when: "29 Sep",
    what: "Shorts were sized on the wrong side of history. The one-in-twenty loss was read from the stock falling, which is a short's gain, so the gate, the size cap and the leverage check all judged shorts on their good nights.",
    fix: "A short is now sized on the stock rising: the calibrated 95th percentile, turned over. The report says which way hurts.",
  },
  {
    when: "29 Sep",
    what: "That loss line was still optimistic on quiet nights: every scored replay had been a long, and replayed as shorts the quietest third breached 7.8% of the time against 5%.",
    fix: "The same 2,345 nights were replayed as shorts. A short's line is now the more cautious of the old one and one fitted on shorts' own outcomes: 4.7% overall, 5.7% on the quietest third, same accuracy.",
  },
  {
    when: "29 Sep",
    what: "Bitget's US-stock data (analyst ratings, insider trades, the live stock price) was silently missing from every live report. Bitget's server refused new sessions over this server's IPv4 address and the report just left the section out.",
    fix: "The API now reaches it over IPv6; the data-sources panel shows how many tokens currently have it.",
  },
  {
    when: "29 Sep",
    what: "\"Over the weekend\" asked on a weekday was run as a six-day hold to Monday, longer than any hold the desk has scored, and the reply did not say so.",
    fix: "The report now says which weekend it measured and gives what past Friday-to-Monday weekends did for that stock.",
  },
  {
    when: "29 Sep",
    what: "The written docs quoted study numbers the live Studies page no longer supported: \"not one of 24 tokens\" had become one, and a t-statistic had changed sign.",
    fix: "The docs quote the live run, and a script fails when they drift apart again.",
  },
  {
    when: "29 Sep",
    what: "A Chinese trader who wrote 我想周末拿点特斯拉 (hold some Tesla over the weekend) was asked \"long or short?\" on every turn and never got an answer.",
    fix: "拿, 入手, 上车 and 抄底 read as a long, and a clarifying question says back what it already has.",
  },
  {
    when: "28 Sep",
    what: "Shorts were never stress-tested. Every preset was a fall, so a TSLA short's \"1-in-100 gap\" showed as a +7.4% gain.",
    fix: "Presets come from the tail that hurts the position; the same short now shows −6.8%.",
  },
  {
    when: "Earlier",
    what: "The raw history's tails were too narrow: 8.5% of outcomes fell below the stated one-in-twenty line instead of 5%.",
    fix: "Every tail is widened by factors fitted only on forecasts that had already matured; out of sample it is back to 5%.",
  },
  {
    when: "Earlier",
    what: "One tail factor for every holding period hid two opposite errors: overnight tails too narrow, weekend tails about twice too wide, so weekend positions were being cut by 43% for nothing.",
    fix: "Each holding period has its own factor.",
  },
];

export default function WrongPage() {
  const { tx, lang } = useLang();
  const [misses, setMisses] = useState<MissesResponse | null>(null);
  const [chain, setChain] = useState<VerifyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.misses().then(setMisses).catch((e: unknown) => setError(e instanceof Error ? e.message : tx("Could not load the misses.", "无法加载未达标记录。")));
    api.verify().then(setChain).catch(() => setChain(null));
  }, []);

  const live = misses?.totals.ticket;
  const replay = misses?.totals.replay;

  return (
    <div className={`${PROOF_WIDTH} space-y-4`}>
      <PageHead
        tabs
        title={tx("What we got wrong", "我们错在哪")}
        intro={tx("A risk tool that only shows its hits is asking to be trusted. This page shows the other half: every live verdict where the loss went past the line, the mistakes we found in the desk itself, and a check anyone can run that no past verdict was edited.", "只展示命中的风险工具，是在要求你相信它。这个页面展示另一半：每一个亏损越过那条线的实时结论、我们在交易台自身发现的错误，以及任何人都能运行的检查，证明过去的结论没有被改动。")}
      />
      {live ? (
        <PlainBox>
          {tx(`The desk says its bad case (the `, `交易台说它的坏情形（即 `)}
          <Term k="p5">p5</Term>
          {tx(` line) should be crossed about 1 time in 20. Of ${live.scored.toLocaleString()} live verdicts scored so far, ${live.missed} crossed it (${fmtPct(live.rate * 100, 1, false)}). `, ` 线）大约二十次会被越过一次。到目前为止已评分的 ${live.scored.toLocaleString()} 个实时结论中，有 ${live.missed} 个越过了它（${fmtPct(live.rate * 100, 1, false)}）。`)}
          {live.scored < 20
            ? tx("That is too few to say much yet. ", "样本还太少，现在说明不了太多。")
            : live.rate > 0.075
              ? tx("That is more often than it should be, and it is shown below rather than hidden. ", "这比应有的频率高，我们把它们列在下面，而不是藏起来。")
              : tx("That is close to what an honest line would give. ", "这与诚实的线应有的结果接近。")}
          {tx("Every miss is listed with its receipt, and the mistakes we found in the desk itself are listed further down. A miss is a ", "每一次突破都附有凭证列出，我们在交易台自身发现的错误列在更下面。一次突破指的是一次 ")}
          <Term k="coverage">{tx("breach", "突破")}</Term>
          {tx(", and a few are expected.", "，出现少量是正常的。")}
        </PlainBox>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="font-medium">{tx("Couldn't load the misses", "无法加载未达标记录")}</p>
          <p className="text-[13px] text-muted-foreground">{error}</p>
        </div>
      ) : null}

      <Section
        title={tx("Live verdicts that went past their line", "亏损超过所述线的实时结论")}
        subtitle={tx("Scored the same way as the calibration page: the tail in force when the verdict was given, fitted only on forecasts that had already matured. Live and replayed are counted apart here; the calibration page pools them, so its single rate sits between the two. If the desk is honest, about 5% should miss.", "评分方式与校准页面相同：使用给出结论时生效的尾部，只用已到期的预测拟合。这里把实盘和回放分开统计；校准页面把两者合并，所以它的比例介于两者之间。如果交易台是诚实的，大约 5% 会突破。")}
      >
        {!misses && !error ? (
          <LoadingRecord blocks={[96]} />
        ) : misses ? (
          <>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <Stat label={tx("Live verdicts scored", "已评分的实时结论")} value={live ? live.scored.toLocaleString() : "0"} hint={tx("given to real users, then scored when the hold ended", "给了真实用户，持有结束后评分")} />
              <Stat
                label={tx("Went past the line", "突破了该线")}
                value={live ? `${live.missed} (${fmtPct(live.rate * 100, 1, false)})` : "—"}
                hint={tx("target about 5%", "目标约 5%")}
                tone={live && live.rate > 0.075 ? "critical" : undefined}
              />
              <Stat label={tx("Replayed forecasts scored", "已评分的重演预测")} value={replay ? replay.scored.toLocaleString() : "0"} hint={tx("the past, run as if live", "把过去当作实时来运行")} />
              <Stat label={tx("Went past the line", "突破了该线")} value={replay ? `${replay.missed} (${fmtPct(replay.rate * 100, 1, false)})` : "—"} hint={tx("target about 5%", "目标约 5%")} />
            </div>
            {misses.misses.length ? (
              <div className="mt-4">
                <ScrollTable>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{tx("When", "时间")}</TableHead>
                      <TableHead>{tx("Trade", "交易")}</TableHead>
                      <TableHead>{tx("Verdict", "结论")}</TableHead>
                      <TableHead className="text-right">{tx("Line stated", "所述的线")}</TableHead>
                      <TableHead className="text-right">{tx("What happened", "实际结果")}</TableHead>
                      <TableHead className="text-right">{tx("Lost past the line", "超出线的亏损")}</TableHead>
                      <TableHead>{tx("Receipt", "凭证")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {misses.misses.map((m) => (
                      <TableRow key={m.id}>
                        <TableCell className="whitespace-nowrap">{fmtTimeL(m.as_of, lang)}</TableCell>
                        <TableCell className="whitespace-nowrap">
                          {lang === "zh" ? (m.side === "long" ? "做多" : m.side === "short" ? "做空" : m.side) : m.side} {fmtUsd(m.notional)} {m.ticker} · {m.horizon_h.toFixed(0)}h
                        </TableCell>
                        <TableCell>{(m.verdict ?? "—").replace("_", " ")}</TableCell>
                        <TableCell className="tabular text-right">{fmtPct(m.stated_p5_pct, 1)}</TableCell>
                        <TableCell className="tabular text-right font-medium">{fmtPct(m.outcome_pct, 1)}</TableCell>
                        <TableCell className="tabular text-right">{fmtUsd(Math.abs(m.beyond_quote))} USDT</TableCell>
                        <TableCell className="font-mono text-[13px]">
                          {m.receipt ? (
                            <a href={`/api/verify/${m.id}`} target="_blank" rel="noreferrer" className="underline underline-offset-2" title={m.receipt}>
                              {m.receipt.slice(0, 10)}…
                            </a>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                </ScrollTable>
              </div>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">{tx("No live verdict has gone past its line yet.", "目前还没有实时结论亏损超过所述的线。")}</p>
            )}
            <p className="mt-3 text-[13px] text-muted-foreground">
              {tx("Most live verdicts come from people trying the desk, so many are small test trades. They are scored all the same.", "大多数实时结论来自试用交易台的人，所以很多是小额的测试交易。它们照样计入评分。")}
            </p>
          </>
        ) : null}
      </Section>

      <Section
        collapsible
        title={tx("Check that no verdict was changed afterwards", "检查没有结论事后被改动")}
        subtitle={tx("Every live verdict gets a receipt when it is given: a SHA-256 over what was asked and what the desk said, chained to the receipt before it. Change or delete any past verdict and every receipt after it stops matching.", "每个实时结论在给出时都会得到一张凭证：对所问内容和交易台的回答做 SHA-256，并与前一张凭证链接。改动或删除任何过去的结论，其后的所有凭证都会对不上。")}
        action={chain ? <Pill tone={chain.ok ? "good" : "critical"}>{chain.ok ? tx("chain intact", "链完好") : tx("chain broken", "链已断")}</Pill> : undefined}
      >
        {chain ? (
          <div className="space-y-2 text-sm">
            <p className="flex items-center gap-2">
              {chain.ok ? <CheckCircle2 className="h-4 w-4 text-status-good" aria-hidden /> : <XCircle className="h-4 w-4 text-destructive" aria-hidden />}
              {chain.ok
                ? tx(`Recomputed just now: all ${chain.checked.toLocaleString()} receipts match the verdicts they cover.`, `刚刚重新计算：全部 ${chain.checked.toLocaleString()} 张凭证都与其对应的结论一致。`)
                : tx(`Recomputed just now: receipt ${chain.first_break?.seq} breaks - ${chain.first_break?.reason}.`, `刚刚重新计算：第 ${chain.first_break?.seq} 张凭证断开——${chain.first_break?.reason}。`)}
            </p>
            <p className="break-all font-mono text-[13px] text-muted-foreground">{tx("Latest receipt: ", "最新凭证：")}{chain.head}</p>
            <p className="text-[13px] text-muted-foreground">
              {tx("Run it yourself: ", "自己运行：")}<a href="/api/verify" target="_blank" rel="noreferrer" className="underline underline-offset-2">/api/verify</a>{tx(", or", "，或者")}{" "}
              <code>/api/verify/&lt;id&gt;</code>{" "}
              {tx("for one verdict; every report shows its own receipt. What this proves and what it does not: the chain shows nothing was changed after its receipt was written. It is kept by the same server that writes the verdicts, so it cannot prove the whole chain was never rebuilt, and verdicts given before 29 September were chained that day. Replayed forecasts are not chained - they are rebuilt from the code and stored prices whenever the replay runs, and anyone can rebuild them the same way.", "用于单个结论；每份报告都显示自己的凭证。它能证明什么、不能证明什么：链只表明凭证写下之后没有任何东西被改动。它由写下结论的同一台服务器保管，所以无法证明整条链从未被重建；9 月 29 日之前给出的结论是在当天才串成链的。重演的预测不在链里——每次运行重演时都从代码和存储的价格重新构建，任何人都可以用同样方式重建。")}
            </p>
          </div>
        ) : (
          <LoadingRecord blocks={[64]} />
        )}
      </Section>

      <Section title={tx("Mistakes we found in the desk itself", "我们在交易台自身发现的错误")} subtitle={tx("Each one changed a number a trader was shown. Newest first; the open one is still open.", "每一个都改变过展示给交易者的某个数字。最新的在前；标为未解决的仍未解决。")}>
        <ul className="space-y-3">
          {FOUND.map((f0, fi) => {
            const f = lang === "zh" && FOUND_ZH[fi] ? { ...f0, ...FOUND_ZH[fi] } : f0;
            return (
            <li key={f0.what} className="rounded-lg border border-border p-3 text-sm">
              <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
                {f.when}
                {f.open ? <Pill tone="warning">{tx("open", "未解决")}</Pill> : <Pill tone="good">{tx("fixed", "已修复")}</Pill>}
              </p>
              <p className="mt-1">{f.what}</p>
              <p className="mt-1 text-muted-foreground">{f.fix}</p>
            </li>
            );
          })}
        </ul>
        <p className="mt-3 text-[13px] text-muted-foreground">
          {tx("The questions we asked about the method itself, and the five that came back “no”, are on the", "我们对方法本身提出的问题，以及其中五个答案为“否”的问题，都在")}{" "}
          <Link href="/studies" className="underline underline-offset-2">
            {tx("Studies", "研究")}
          </Link>{" "}
          {tx("page.", "页面。")}
        </p>
      </Section>
    </div>
  );
}
