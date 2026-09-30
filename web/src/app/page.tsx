"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Chat } from "@/components/desk/chat";
import { OpenPositions, useOpenPositions } from "@/components/desk/open-positions";
import { ProofStrip } from "@/components/desk/proof-strip";
import { ScenarioChips } from "@/components/desk/scenarios";
import { Sources } from "@/components/desk/sources";
import { TicketForm } from "@/components/desk/ticket-form";
import { Working } from "@/components/desk/working";
import { ReportView } from "@/components/report/report-view";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLang } from "@/lib/lang";
import { scrollIntoViewOnSmall } from "@/lib/scroll";
import { ApiError, api, type Report, type TicketInput, type UniverseEntry } from "@/lib/api";

export default function DeskPage() {
  const { lang, setLang, tx } = useLang();
  const resultRef = useRef<HTMLElement>(null);
  const [universe, setUniverse] = useState<UniverseEntry[] | null>(null);
  const [universeError, setUniverseError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  // True when the report came out of the chat, whose thread already carries the analyst's take.
  const [fromChat, setFromChat] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTicket, setLastTicket] = useState<TicketInput | null>(null);
  const [tab, setTab] = useState("form");
  // A canned run for the chat to play once: the id makes each click a new run.
  const [script, setScript] = useState<{ id: number; steps: string[] } | null>(null);
  const deepLinked = useRef(false);
  const [equity, setEquity] = useState<number | null>(200000);
  const { positions, setPositions } = useOpenPositions();

  async function loadUniverse() {
    setUniverseError(null);
    try {
      setUniverse(await api.universe(true));
    } catch (e) {
      setUniverseError(e instanceof Error ? e.message : tx("Could not load the token list.", "无法加载代币列表。"));
    }
  }

  useEffect(() => {
    void loadUniverse();
  }, []);

  function runScenario(steps: string[]) {
    setTab("chat");
    setScript({ id: Date.now(), steps });
  }

  // /?q=<text> runs that text once through the chat; repeat q for a follow-up question.
  useEffect(() => {
    if (deepLinked.current) return;
    deepLinked.current = true;
    const params = new URLSearchParams(window.location.search);
    const steps = params.getAll("q").map((q) => q.trim().slice(0, 500)).filter(Boolean);
    if (!steps.length) return;
    window.history.replaceState(null, "", window.location.pathname);
    runScenario(steps);
  }, []);

  async function run(ticket: TicketInput) {
    setBusy(true);
    setError(null);
    setLastTicket(ticket);
    setEquity(ticket.account_equity_quote ?? null);
    setFromChat(false);
    scrollIntoViewOnSmall(resultRef.current);
    try {
      // The book travels with the ticket so the report can judge both.
      setReport(await api.analyze({ ...ticket, open_positions: positions }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : tx("The analysis failed.", "分析失败。"));
    } finally {
      setBusy(false);
    }
  }

  return (
    // min-w-0 on both columns: a grid track is auto-sized by default, so one wide table
    // in the report stretches the whole column past the viewport and takes the sidebar
    // with it. With it, the tables' own overflow-x-auto wrappers do the scrolling.
    <div className="space-y-6">
    <ProofStrip stocks={universe?.length ?? null} />
    <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
      <aside className="min-w-0 space-y-4 lg:sticky lg:top-6 lg:self-start">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{tx("Stress-test a trade", "给交易做压力测试")}</h1>
          <p className="text-sm text-muted-foreground">{tx("Tokenized US stocks trade 24/7. Find out what past moments like now did, what could go wrong, and whether you can get out — before you place it.", "代币化美股全天候交易。下单之前，先看看历史上与现在相似的时刻发生了什么、可能出什么问题、以及能不能顺利平仓。")}</p>
          {/* On a phone the explainer on the right sits under this whole form, so a first
              visitor scrolls past twelve fields before learning what the desk does. */}
          {!report ? (
            <p className="mt-2 text-sm text-muted-foreground lg:hidden">
              {tx("Describe a trade (form or chat, English or 中文) → the desk shows what past moments like now did, stress-tests it, prices the exit on Bitget's live book → you get a sized verdict: ", "描述一笔交易（表单或聊天，English 或中文）→ 交易台展示与现在相似的历史时刻后来怎样，做压力测试，并按 Bitget 实时盘口计算平仓成本 → 给出带仓位的结论：")}
              <span className="font-medium text-foreground">{tx("GO", "可以做")}</span>, <span className="font-medium text-foreground">{tx("REDUCE", "减仓")}</span>,{" "}
              <span className="font-medium text-foreground">{tx("HEDGE", "对冲")}</span>, <span className="font-medium text-foreground">{tx("REVIEW", "复核")}</span> {tx("or", "或")}{" "}
              <span className="font-medium text-foreground">{tx("NO GO", "不建议做")}</span>{tx(". You decide.", "。决定权在你。")}
            </p>
          ) : null}
        </div>
        <ScenarioChips disabled={busy} onPick={runScenario} />
        <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
          <TabsList className="w-full">
            <TabsTrigger value="form" className="flex-1">
              {tx("Ticket", "表单")}
            </TabsTrigger>
            <TabsTrigger value="chat" className="flex-1">
              {tx("Chat", "聊天")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="form" className="pt-3">
            {universe ? (
              <div className="space-y-5">
                <TicketForm universe={universe} busy={busy} onSubmit={run} />
                <div className="border-t border-border pt-4">
                  <OpenPositions universe={universe} positions={positions} onChange={setPositions} />
                </div>
                <div className="border-t border-border pt-4">
                  <Sources />
                </div>
              </div>
            ) : universeError ? (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
                <p className="font-medium">{tx("Couldn't load the token list", "无法加载代币列表")}</p>
                <p className="text-xs text-muted-foreground">{universeError}</p>
                <Button variant="secondary" size="sm" className="mt-2" onClick={() => void loadUniverse()}>
                  {tx("Try again", "重试")}
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            )}
          </TabsContent>
          <TabsContent value="chat" className="pt-3">
            <Chat accountEquity={equity} busy={busy} setBusy={setBusy} script={script} onReport={(r) => {
                setReport(r);
                setFromChat(true);
                scrollIntoViewOnSmall(resultRef.current);
              }}
            />
          </TabsContent>
        </Tabs>
      </aside>

      <section ref={resultRef} className="min-w-0 scroll-mt-4" aria-live="polite" aria-busy={busy}>
        {busy && !report ? <ReportSkeleton /> : null}
        {error ? (
          <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
            <p className="font-medium">{tx("Couldn't run the analysis", "无法运行分析")}</p>
            <p className="text-xs text-muted-foreground">{error}</p>
            {lastTicket ? (
              <Button variant="secondary" size="sm" className="mt-2" onClick={() => void run(lastTicket)} disabled={busy}>
                {tx("Try again", "重试")}
              </Button>
            ) : null}
          </div>
        ) : null}
        {report ? (
          <div className={busy ? "opacity-60 transition-opacity" : ""}>
            <ReportView
              report={report}
              lang={lang}
              hideTake={fromChat}
              onRerun={(patch) => {
                // The same trade at the same moment, with one thing changed. A report from
                // chat has no form ticket behind it, so its own ticket is the base.
                const base = lastTicket ?? (report.ticket as unknown as TicketInput);
                void run({ ...base, ...patch, as_of: report.as_of });
              }}
            />
          </div>
        ) : !busy && !error ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-8 text-center">
            <p className="text-base font-semibold">{tx("What happens to your position while the US market is shut?", "美股休市期间，你的仓位会怎样？")}</p>
            <ol className="max-w-prose space-y-1 text-left text-sm text-muted-foreground">
              <li>
                <span className="font-medium text-foreground">1.</span> {tx("Describe the trade - in the form, or in plain words in chat (English or 中文).", "描述这笔交易——用表单，或者在聊天里用大白话（English 或中文）。")}
              </li>
              <li>
                <span className="font-medium text-foreground">2.</span> {tx("The desk finds the past moments most like now and shows what followed, then stress-tests the position and prices the exit on the live order book.", "交易台找出与现在最相似的历史时刻并展示后来发生了什么，然后对仓位做压力测试，并按实时盘口计算平仓成本。")}
              </li>
              <li>
                <span className="font-medium text-foreground">3.</span> {tx("You get a sized verdict in money - GO, REDUCE to a smaller size, HEDGE with the perp, REVIEW (something missing) or NO GO - your own plan checked against the data, and an AI analyst's read of it. You decide.", "你会得到一个以金额表示的结论——可以做、减到更小的仓位、用永续合约对冲、需要复核（缺少信息）或不建议做——你自己的计划会对照数据检查，还有 AI 分析师的解读。决定权在你。")}
              </li>
            </ol>
            <Button
              className="mt-2 h-auto max-w-full whitespace-normal py-2 text-center"
              disabled={busy}
              onClick={() =>
                void run({
                  ticker: "TSLA",
                  side: "long",
                  notional_quote: 20000,
                  account_equity_quote: 200000,
                  horizon_kind: "next_open",
                  horizon_hours: null,
                  stop_price: null,
                  thesis: tx("Strength into the close carries through the night.", "收盘前的强势会延续到夜盘。"),
                  invalidation: tx("Wrong if it drops 3% before the open.", "开盘前跌 3% 就说明判断错了。"),
                })
              }
            >
              {tx("See it on a real trade: $20k of TSLA held to the next open", "看一笔真实交易：持有 2 万美元 TSLA 到下次开盘")}
            </Button>
            <Link href="/tonight" className="text-sm text-muted-foreground underline underline-offset-2 hover:text-foreground">
              {tx("Or check everything you already hold before the market reopens", "或者在开盘前检查你已有的全部持仓")}
            </Link>
          </div>
        ) : null}
      </section>
    </div>
    </div>
  );
}

function ReportSkeleton() {
  return (
    <div className="space-y-4">
      <Working />
      <Skeleton className="h-36 w-full rounded-lg" aria-hidden />
      <Skeleton className="h-28 w-full rounded-lg" />
      <Skeleton className="h-72 w-full rounded-lg" />
      <Skeleton className="h-64 w-full rounded-lg" />
    </div>
  );
}
