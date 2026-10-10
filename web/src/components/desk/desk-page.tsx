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
import { BookContrast } from "@/components/report/book-contrast";
import { ReportView } from "@/components/report/report-view";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLang } from "@/lib/lang";
import { WeekStrip } from "./week-strip";
import { scrollIntoViewOnSmall, scrollToAnswer } from "@/lib/scroll";
import { snapshotFlag, snapshotNoticeFor, readableTime } from "@/lib/snapshot";
import { snapshot } from "@/snapshot";
import { ApiError, api, type MissesResponse, type Report, type TicketInput, type UniverseEntry } from "@/lib/api";
import { fmtDateL } from "@/lib/i18n";
import { loadChat, loadReportId, saveReportId } from "@/lib/desk-session";

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
  const [tab, setTab] = useState("chat");
  // A canned run for the chat to play once: the id makes each click a new run.
  const [script, setScript] = useState<{ id: number; steps: string[] } | null>(null);
  const deepLinked = useRef(false);
  // Set when a fresh answer is on its way; the effect below scrolls to it once it has rendered.
  const scrollPending = useRef(false);
  const [heroDraft, setHeroDraft] = useState("");
  const [heroUsed, setHeroUsed] = useState(false);
  // True only while a ticket-form (or example) analysis is in flight, so the form can show its own progress.
  const [formRunning, setFormRunning] = useState(false);
  // The account the trader typed in the form or picked from the ladder. Never a default: the
  // chat sends it with every message, and an invented account hides the account-size row.
  const [equity, setEquity] = useState<number | null>(null);
  const { positions, setPositions } = useOpenPositions();
  const heroUp = !report && !heroUsed;
  // The saved example is formatted in the reader's time zone, which the server cannot know, so it
  // is drawn only after hydration; drawing it on the server made every non-UTC browser log a mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const exampleReport = (snapshot?.reports.TSLA as unknown as Report | undefined) ?? null;

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

  // The one-click "same trade, different book" demo: a canned ticket run alone and on an example book.
  const [contrast, setContrast] = useState<{ id: number } | null>(null);
  function runContrastDemo() {
    setHeroUsed(true);
    setHeroDraft("");
    setReport(null);
    setError(null);
    setContrast({ id: Date.now() });
    scrollIntoViewOnSmall(resultRef.current);
  }

  function runScenario(steps: string[]) {
    setHeroUsed(true);
    setContrast(null);
    setTab("chat");
    setHeroDraft("");
    setScript({ id: Date.now(), steps });
  }

  const [restoring, setRestoring] = useState(false);
  // A refresh or the Back button brings back the report that was on screen, from its stored copy.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    if (new URLSearchParams(window.location.search).has("q")) return;
    const savedChat = loadChat<unknown>();
    if (savedChat && savedChat.messages && savedChat.messages.length > 0) {
      setHeroUsed(true);
    }
    // A what-if on screen has no stored copy (its id was dropped), but the chat still knows the
    // stored report the conversation is about: bring that back rather than the example.
    const id = loadReportId() ?? savedChat?.contextId ?? null;
    if (id == null) return;
    setHeroUsed(true);
    setRestoring(true);
    let live = true;
    void api
      .report(id)
      .then((r) => {
        if (!live) return;
        setReport((cur) => cur ?? r);
        setFromChat(true);
      })
      .catch(() => {})
      .finally(() => {
        if (live) setRestoring(false);
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (!report || !scrollPending.current) return;
    scrollPending.current = false;
    // Two frames: the report and anything the chat does in the same tick have settled by then.
    let id2 = 0;
    const id1 = requestAnimationFrame(() => {
      id2 = requestAnimationFrame(() => scrollToAnswer(resultRef.current));
    });
    return () => {
      cancelAnimationFrame(id1);
      cancelAnimationFrame(id2);
    };
  }, [report]);
  useEffect(() => {
    if (report) saveReportId((report.forecast_id as number | null) ?? null);
  }, [report]);

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

  function demoTicket(): TicketInput {
    return {
      ticker: "TSLA",
      side: "long",
      notional_quote: 20000,
      account_equity_quote: 200000,
      horizon_kind: "next_open",
      horizon_hours: null,
      stop_price: null,
      thesis: tx("Strength into the close carries through the night.", "收盘前的强势会延续到夜盘。"),
      invalidation: tx("Wrong if it drops 3% before the open.", "开盘前跌 3% 就说明判断错了。"),
    };
  }

  async function run(ticket: TicketInput, remember = true) {
    setBusy(true);
    setFormRunning(true);
    setError(null);
    setLastTicket(ticket);
    // The built-in example carries its own account; that is the example's, not the trader's.
    if (remember) setEquity(ticket.account_equity_quote ?? null);
    setFromChat(false);
    scrollIntoViewOnSmall(resultRef.current);
    try {
      // The book travels with the ticket so the report can judge both.
      const got = await api.analyze({ ...ticket, open_positions: positions });
      if (snapshotFlag.get() !== null) {
        // The proxy answered from its saved copy because the live server is down. That is an
        // example, not this trade, so it is said in words and the report on screen stays.
        setError(snapshotNoticeFor(snapshotFlag.get() as string, lang));
      } else {
        setContrast(null);
        scrollPending.current = true;
        setReport(got);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : tx("The analysis failed.", "分析失败。"));
    } finally {
      setBusy(false);
      setFormRunning(false);
    }
  }

  return (
    // min-w-0 on both columns: a grid track is auto-sized by default, so one wide table
    // in the report stretches the whole column past the viewport and takes the sidebar
    // with it. With it, the tables' own overflow-x-auto wrappers do the scrolling.
    <div className="flex flex-col gap-4 sm:gap-6">
    {!report && !heroUsed ? (
      <Hero
        draft={heroDraft}
        setDraft={setHeroDraft}
        busy={busy}
        onSend={(text) => {
          setHeroUsed(true);
          runScenario([text]);
        }}
        onContrast={runContrastDemo}
        onExample={() => {
          setHeroUsed(true);
          setHeroDraft("");
          void run(demoTicket(), false);
        }}
        exampleDisabled={busy || !universe}
        onForm={() => {
          setHeroUsed(true);
          setTab("form");
        }}
      />
    ) : null}
    {/* The Bitget list is long and says nothing about the trade, so while the
        hero is up it goes below the example verdict instead of pushing the verdict off the first screen. */}
    <div className={heroUp ? "order-last" : ""}>
      <ProofStrip stocks={universe ? universe.filter((u) => u.has_data).length : null} />
    </div>
    {/* While the hero is up there is one input on the page (the hero's); the Chat/Ticket rail
        appears once a trade has been asked for, or when the reader asks for the form. */}
    <div className={heroUp ? "grid w-full gap-6" : "grid gap-6 lg:grid-cols-[380px_1fr]"}>
      <aside className={`min-w-0 space-y-4 lg:sticky lg:top-6 lg:self-start ${heroUp ? "hidden" : ""}`}>
        {/* While the hero is up it carries the h1, the pitch and the demo trades; the rail
            repeats none of them, and takes over once the hero is gone. */}
        {report || heroUsed ? (
        <div>
          <h1 className={`text-balance text-lg font-semibold tracking-tight ${lang === "zh" ? "[word-break:keep-all] [overflow-wrap:anywhere]" : ""}`}>{tx("Stress-test a trade", "给交易做压力测试")}</h1>
          <p className="text-sm text-muted-foreground">{tx("Tokenized US stocks trade 24/7. Find out what past moments like now did, what could go wrong, and whether you can get out — before you place it.", "代币化美股全天候交易。下单之前，先看看历史上与现在相似的时刻发生了什么、可能出什么问题、以及能不能顺利平仓。")}</p>
          {/* On a phone the explainer on the right sits under this whole form, so a first
              visitor scrolls past twelve fields before learning what the desk does. */}
          {!report ? (
            <p className="mt-2 text-sm text-muted-foreground lg:hidden">
              {tx("Describe a trade (form or chat, English or 中文) → the desk shows what past moments like now did, stress-tests it, prices the exit on Bitget's live book → you get a sized verdict: ", "描述一笔交易（表单或聊天，English 或中文）→ 交易台展示与现在相似的历史时刻后来怎样，做压力测试，并按 Bitget 实时盘口计算平仓成本 → 给出带仓位的结论：")}
              <span className="font-medium text-foreground">{tx("GO", "可以做")}</span>, <span className="font-medium text-foreground">{tx("REDUCE TO", "减仓")}</span>,{" "}
              <span className="font-medium text-foreground">{tx("HEDGE", "对冲")}</span>, <span className="font-medium text-foreground">{tx("REVIEW", "复核")}</span> {tx("or", "或")}{" "}
              <span className="font-medium text-foreground">{tx("NO GO", "不建议做")}</span>{tx(". You decide.", "。决定权在你。")}
            </p>
          ) : null}
        </div>
        ) : null}
        {report || heroUsed ? <ScenarioChips disabled={busy} onPick={runScenario} onContrast={runContrastDemo} /> : null}
        <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
          <TabsList className="w-full max-sm:h-12!">
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
                <TicketForm universe={universe} busy={busy} working={formRunning} error={error} onRetry={lastTicket ? () => void run(lastTicket) : undefined} onSubmit={run} />
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
                <p className="text-[13px] text-muted-foreground">{universeError}</p>
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
            <Chat accountEquity={equity} busy={busy} setBusy={setBusy} script={script} onRestore={() => setHeroUsed(true)} onNewChat={() => { setReport(null); setError(null); saveReportId(null); }} onReport={(r) => {
                setContrast(null);
                setReport(r);
                setFromChat(true);
                scrollPending.current = true;
              }}
            />
          </TabsContent>
        </Tabs>
      </aside>

      <section ref={resultRef} className="min-w-0 scroll-mt-4" aria-live="polite" aria-busy={busy || restoring}>
        {(busy || restoring) && !report ? <ReportSkeleton /> : null}
        {error && tab !== "form" ? (
          <div role="alert" className="mb-5 space-y-1 rounded-lg border border-destructive/30 p-4 text-sm">
            <p className="font-medium">{tx("Couldn't run the analysis", "无法运行分析")}</p>
            <p className="text-[13px] text-muted-foreground">{error}</p>
            {lastTicket ? (
              <Button variant="secondary" size="sm" className="mt-2" onClick={() => void run(lastTicket)} disabled={busy}>
                {tx("Try again", "重试")}
              </Button>
            ) : null}
          </div>
        ) : null}
        {contrast && !report ? (
          <div className="space-y-3 border-t border-border pt-5">
            <h2 className="text-base font-semibold">{tx("Same trade, different book", "同一笔交易，不同的组合")}</h2>
            <p className="text-sm text-muted-foreground">
              {tx("Long 20k TSLA overnight, once on its own and once on top of 60k TSLA + 40k NVDA. Same moment, same data; only the book differs.", "做多 2 万美元 TSLA 过夜：一次单独做，一次叠加在 6 万 TSLA + 4 万 NVDA 之上。同一时刻、同样的数据，只有组合不同。")}
            </p>
            <BookContrast key={contrast.id} ticket={demoTicket()} lang={lang} auto />
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
                void run({ ...base, ...patch, as_of: report.as_of }, patch.account_equity_quote !== undefined);
              }}
            />
          </div>
        ) : !busy && !restoring && !error && !contrast && !heroUsed && exampleReport ? (
          mounted ? (<div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed border-border bg-muted/40 px-3 py-2">
              {/* The time is formatted in the reader's locale and zone, which the server cannot know;
                  React is told the difference is expected rather than re-rendering the page. */}
              <p className="text-sm text-muted-foreground" suppressHydrationWarning>
                {tx(`Example from ${readableTime(snapshot!.generated_at)} — press to run it live now`, `示例，生成于 ${fmtDateL(snapshot!.generated_at, "zh")} — 点击立即实时运行`)}
              </p>
              <Button size="sm" disabled={busy || !universe} onClick={() => void run(demoTicket(), false)}>
                {tx("Run this trade live", "实时运行这笔交易")}
              </Button>
            </div>
            <ReportView report={exampleReport} lang={lang} hideTake />
          </div>) : null
        ) : !busy && !restoring && !error && !contrast ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border p-6 sm:p-8 text-center">
            <p className="text-base font-semibold">{tx("What happens to your position while the US market is shut?", "美股休市期间，你的仓位会怎样？")}</p>
            <ol className="max-w-prose space-y-2 text-left text-sm leading-relaxed text-muted-foreground">
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
              onClick={() => void run(demoTicket(), false)}
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

// Each chip is a full ticket the desk can parse (ticker, side, size, horizon); `send` may
// carry a written plan the label leaves out so the verdict is not just "plan missing".
// `short` is only what the chip shows, so a row of them fits one line on a phone.
// Each also states an account (the same 200k as the TSLA example) and a reason with a
// "wrong if" line: without them the gate asks for the account and the written plan, and
// every chip came back REVIEW. Each line is a move inside the stock's own one-in-twenty
// move over that hold, so it can bind, and past holds do cross it (see tests/test_starter_chips.py).
// `sendZh` is the same trade in Chinese, sent on the Chinese page: same size, leverage,
// account, reason, line and hold, checked field by field in tests/test_starter_chips.py.
const HERO_CHIPS: { en: string; zh: string; short: string; shortZh: string; send?: string; sendZh?: string }[] = [
  { en: "Long NVDA over the weekend, account 200k — is 15k safe?", zh: "周末做多 NVDA，账户 20 万，1.5 万安全吗？", short: "NVDA weekend 15k", shortZh: "周末 NVDA 1.5 万", send: "Long NVDA over the weekend, 15k, account 200k, because I think the uptrend holds into Monday, wrong if it drops 4% over the weekend. Is it safe?", sendZh: "周末做多 NVDA 1.5万U，账户 20 万，理由是我认为上升趋势会延续到周一，如果周末下跌超过 4% 就算错，安全吗？" },
  { en: "5x long TSLA overnight, account 200k?", zh: "5 倍杠杆做多 TSLA 过夜，账户 20 万？", short: "5x TSLA overnight", shortZh: "5 倍 TSLA 过夜", send: "5x long 10k TSLA overnight, account 200k, because I think the strength carries through the night, wrong if it drops 3% before the open. Is it safe?", sendZh: "5 倍杠杆做多 TSLA 1万U 过夜，账户 20 万，理由是我认为强势会延续整晚，如果开盘前下跌超过 3% 就算错，安全吗？" },
  { en: "周末做多特斯拉 2万U，账户 20 万，安全吗？", zh: "周末做多特斯拉 2万U，账户 20 万，安全吗？", short: "周末做多特斯拉", shortZh: "周末做多特斯拉", send: "周末做多 TSLA 2万U，账户 20 万，理由是我认为强势会延续到周一，如果周末下跌超过 4% 就算错，安全吗？" },
];

const WHAT_IF_CHIPS: { en: string; zh: string; short: string; shortZh: string; send?: string }[] = [
  { en: "What if TSLA gaps down 8% at open?", zh: "如果 TSLA 开盘跳空低开 8% 会怎样？", short: "TSLA gap -8% open", shortZh: "TSLA 开盘低开 8%", send: "What if TSLA gaps down 8% at the open? How wide is the tail loss?" },
  { en: "Can I exit 20k NVDA at 3 AM on Bitget?", zh: "凌晨 3 点能在 Bitget 平掉 2 万 NVDA 吗？", short: "Exit 20k NVDA at 3 AM", shortZh: "凌晨 3 点平仓 NVDA", send: "Can I exit 20k NVDA at 3 AM on Bitget's live order book?" },
  { en: "Is 10x leverage safe for TSLA into the weekend?", zh: "周末 10 倍杠杆做多 TSLA 安全吗？", short: "10x leverage weekend", shortZh: "周末 10 倍杠杆", send: "Is 10x leverage safe for TSLA into the weekend? Where does liquidation sit?" },
];

const CHIP = "inline-flex min-h-10 items-center sm:min-h-8 rounded-full border border-border px-3.5 py-1 text-[13px] hover:border-foreground/40 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none transition-colors";

/** Three proof chips from the same live endpoints the track-record pages read. */
function HeroProof() {
  const { tx } = useLang();
  const [misses, setMisses] = useState<MissesResponse | null>(null);
  useEffect(() => {
    let live = true;
    void api.misses().then((m) => live && setMisses(m)).catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  const tk = misses?.totals?.ticket;
  const scored = tk?.scored ?? 0;
  const has = scored > 0;
  const rate = Math.round((tk?.rate ?? 0) * 100);
  const target = Math.round((misses?.target_rate ?? 0.05) * 100);
  return (
    <ul className="flex min-h-8 flex-wrap gap-2" aria-label={tx("Proof", "证据")}>
      {has ? (
        <>
          <li>
            <Link href="/wrong" className={CHIP} title={tx("Live verdicts whose hold has ended and whose outcome is recorded. Open verdicts are not in this number; /usage counts the answers given to visitors.", "持有期已结束、结果已记录的实时结论。未到期的不在其中；/usage 统计的是给访客的回答。")}>
              <span className="tabular mr-1 font-semibold">{scored.toLocaleString()}</span> {tx("live verdicts scored (hold over)", "个实时结论已评分（持有期已过）")}
            </Link>
          </li>
          <li>
            <Link href="/wrong" className={CHIP}>
              <span className="tabular mr-1 font-semibold">{rate}%</span> {tx(`went past their line vs ${target}% target`, `越过了自己划的线（目标 ${target}%）`)}
            </Link>
          </li>
        </>
      ) : null}
      <li>
        <Link href="/status" className={CHIP}>
          <span aria-hidden className="mr-2 h-2 w-2 rounded-full bg-status-good" />
          {tx("live Bitget order book", "Bitget 实时订单簿")}
        </Link>
      </li>
    </ul>
  );
}

function Hero({ draft, setDraft, busy, onSend, onContrast, onExample, exampleDisabled, onForm }: { draft: string; setDraft: (s: string) => void; busy: boolean; onSend: (t: string) => void; onContrast: () => void; onExample: () => void; exampleDisabled: boolean; onForm: () => void }) {
  const { lang, tx } = useLang();
  const text = draft.trim();
  return (
    <section className="pb-4 pt-4 sm:pt-8" aria-label={tx("Describe a trade", "描述一笔交易")}>
      <div className="grid gap-6 rounded-2xl border border-white/10 bg-[#080e20] p-5 text-slate-100 sm:p-8 lg:grid-cols-[1.15fr_1fr] lg:items-center lg:gap-10">
        <div>
        <p className="mb-4 text-[11px] font-medium uppercase tracking-[0.18em] text-amber-200/80">
          {tx("NIGHTWATCH · PRE-TRADE DECISION STRESS TESTING FOR BITGET", "NIGHTWATCH · BITGET 交易前决策压力测试")}
        </p>
        <h1 className={`text-balance text-3xl font-semibold leading-[1.08] tracking-[-0.03em] text-slate-50 sm:text-5xl lg:text-[3.5rem] ${lang === "zh" ? "[word-break:keep-all] [overflow-wrap:anywhere]" : ""}`}>
          {tx("Stress-test the trade before you place it.", "下单之前，先给这笔交易做压力测试。")}
        </h1>
        <div className="mt-5 max-w-3xl space-y-3 text-[15px] leading-relaxed text-slate-300 sm:text-base">
          <p>
            {tx(
              "A pre-trade decision workbench for tokenized US stocks and leveraged trades on Bitget. The deterministic Python engine finds similar past market moments, builds an empirical forecast distribution (p5 to p95), runs stress scenarios, and prices your exit on Bitget's live order book. The Qwen model explains the trade; deterministic code computes every number.",
              "Bitget 上代币化美股与杠杆交易的交易前决策工作台。确定性 Python 引擎检索历史上相似的市场时刻，构建实证预测分布（p5 至 p95），运行预设压力测试，并在 Bitget 实时订单簿上计算平仓成本。Qwen 模型只负责理解与解释，每个数字均由确定性代码严谨计算。"
            )}
          </p>
          <p className="hidden text-slate-400 sm:block">
            {tx(
              "Trading after hours or over the weekend? Type your trade in plain words — English or 中文 — like \"long 10k TSLA tonight 5x\" or \"hold NVDA over the weekend, stop 170\". Nightwatch never places orders and never touches your money: you get a sized GO / REDUCE / HEDGE / REVIEW / NO GO verdict before you risk capital.",
              "在盘后或周末交易？用日常语言描述你的交易——支持英文或中文——例如“今晚 5 倍做多 1 万 TSLA”或“周末做多 NVDA，止损 170”。Nightwatch 绝不下单，也不触碰你的资金：在冒资金风险前，为你给出带仓位建议的 GO / REDUCE / HEDGE / REVIEW / NO GO 结论。"
            )}
          </p>
        </div>

        </div>
        <WeekStrip />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] font-medium">
        <Link href="/calibration" className="inline-flex min-h-10 items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
          {tx("Track record & calibration →", "战绩与校准 →")}
        </Link>
        <Link href="/wrong" className="inline-flex min-h-10 items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
          {tx("What we got wrong →", "我们错在哪 →")}
        </Link>
        <Link href="/studies" className="inline-flex min-h-10 items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
          {tx("Closed-market studies →", "休市研究 →")}
        </Link>
        <Link href="/tonight" className="inline-flex min-h-10 items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
          {tx("Tonight's watch →", "今晚持仓监视 →")}
        </Link>
        <Link href="/sources" className="inline-flex min-h-10 items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
          {tx("Data feeds & live book →", "数据源与实时盘口 →")}
        </Link>
        <Link href="/judges" className="inline-flex min-h-10 items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
          {tx("For judges →", "给评审 →")}
        </Link>
      </div>

      <form
        className="mt-6 flex flex-col gap-3 sm:mt-7 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (text && !busy) onSend(text);
        }}
      >
        <label htmlFor="hero-input" className="sr-only">
          {tx("Describe a trade", "描述一笔交易")}
        </label>
        <textarea
          id="hero-input"
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (text && !busy) onSend(text);
            }
          }}
          placeholder={tx("e.g. long NVDA over the weekend, 15k, account 200k, stop 170", "例如：周末做多 NVDA，1.5 万，账户 20 万，止损 170")}
          disabled={busy}
          className="min-w-0 flex-1 h-14 resize-none rounded-xl border border-input bg-background/80 px-4 py-3.5 text-base sm:text-lg focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        />
        <Button type="submit" disabled={busy || !text} className="h-12 px-6 sm:h-14 font-semibold text-base rounded-xl">
          {tx("Get the verdict", "获取结论")}
        </Button>
      </form>

      {/* Prominent secondary actions right below form (above mobile fold) */}
      <div className="mt-4 flex flex-wrap items-center gap-2.5">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={exampleDisabled}
          onClick={onExample}
          title={tx("Run the example trade below live, right now", "立即实时运行下面的示例交易")}
          className="min-h-10 text-xs sm:text-sm font-medium"
        >
          {tx("Run the TSLA example live", "实时运行 TSLA 示例")}
        </Button>
        <button
          type="button"
          disabled={busy}
          onClick={onContrast}
          title={tx("Run one trade alone and on a concentrated book, side by side", "把同一笔交易单独运行，并叠加在集中的组合上，并排对比")}
          className="inline-flex min-h-10 items-center px-2 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground disabled:opacity-50"
        >
          {tx("Same trade, different book", "同一笔交易，不同组合")}
        </button>
        <button
          type="button"
          onClick={onForm}
          className="inline-flex min-h-10 items-center px-2 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
        >
          {tx("Use ticket form", "使用表单模式")}
        </button>
      </div>

      {/* Pipeline Highlight Card */}
      <div className="mt-6 rounded-xl border border-border/70 p-4 sm:p-5">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-foreground/80">
          {tx("Decision pipeline · 5 stages", "决策流水线 · 5 个阶段")}
        </p>
        <p className="mt-2 text-xs sm:text-[13px] leading-relaxed text-muted-foreground">
          {tx(
            "similar past moments → forward distribution (p5–p95) → preset stress tests → live Bitget order-book exit walk → sized verdict (GO / REDUCE / HEDGE / REVIEW / NO GO) · fully audited in public",
            "相似历史时刻 → 结果前向分布 (p5–p95) → 预设压力测试 → Bitget 实时盘口平仓推演 → 仓位结论 (GO / REDUCE / HEDGE / REVIEW / NO GO) · 结果全公开审计"
          )}
        </p>
      </div>

      {/* Categorized suggestions */}
      <div className="mt-7 space-y-5">
        <div>
          <p className="mb-2.5 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            {tx("Demo trades", "演示交易")}
          </p>
          <ul className="flex flex-wrap gap-2">
            {HERO_CHIPS.map((c) => (
              <li key={c.en} className="shrink-0">
                <button
                  type="button"
                  disabled={busy}
                  title={lang === "zh" ? c.zh : c.en}
                  onClick={() => onSend((lang === "zh" ? c.sendZh : undefined) ?? c.send ?? c.en)}
                  className={`${CHIP} whitespace-nowrap text-muted-foreground hover:border-foreground/40 hover:text-foreground disabled:opacity-50`}
                >
                  {lang === "zh" ? c.shortZh : c.short}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="mb-2.5 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            {tx("What-if & book analysis", "假设情景与组合分析")}
          </p>
          <ul className="flex flex-wrap gap-2">
            {WHAT_IF_CHIPS.map((c) => (
              <li key={c.en} className="shrink-0">
                <button
                  type="button"
                  disabled={busy}
                  title={lang === "zh" ? c.zh : c.en}
                  onClick={() => onSend(c.send ?? c.en)}
                  className={`${CHIP} whitespace-nowrap text-muted-foreground hover:border-foreground/40 hover:text-foreground disabled:opacity-50`}
                >
                  {lang === "zh" ? c.shortZh : c.short}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="mb-2.5 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            {tx("The desk's own record", "交易台自身战绩")}
          </p>
          <HeroProof />
        </div>
      </div>

      <p className="mt-5 text-xs text-muted-foreground/75">
        {tx("Type a trade above, or pick one of the suggestions.", "在上方输入交易，或点击上方任一建议。")}
      </p>
    </section>
  );
}

function ReportSkeleton() {
  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-border/80 bg-card/60 p-5 shadow-xs">
        <Working />
      </div>
      <div className="space-y-4 opacity-40">
        <Skeleton className="h-32 w-full rounded-xl" aria-hidden />
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    </div>
  );
}
