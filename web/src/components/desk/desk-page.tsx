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
import { scrollIntoViewOnSmall } from "@/lib/scroll";
import { snapshotFlag, snapshotNoticeFor, readableTime } from "@/lib/snapshot";
import { snapshot } from "@/snapshot";
import { ApiError, api, type MissesResponse, type Report, type TicketInput, type UniverseEntry } from "@/lib/api";
import { fmtDateL } from "@/lib/i18n";
import { loadReportId, saveReportId } from "@/lib/desk-session";

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
  const [heroDraft, setHeroDraft] = useState("");
  const [heroUsed, setHeroUsed] = useState(false);
  // True only while a ticket-form (or example) analysis is in flight, so the form can show its own progress.
  const [formRunning, setFormRunning] = useState(false);
  // The account the trader typed in the form or picked from the ladder. Never a default: the
  // chat sends it with every message, and an invented account hides the account-size row.
  const [equity, setEquity] = useState<number | null>(null);
  const { positions, setPositions } = useOpenPositions();
  const heroUp = !report && !heroUsed;
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

  // A refresh or the Back button brings back the report that was on screen, from its stored copy.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    if (new URLSearchParams(window.location.search).has("q")) return;
    const id = loadReportId();
    if (id == null) return;
    setHeroUsed(true);
    let live = true;
    void api
      .report(id)
      .then((r) => {
        if (!live) return;
        setReport((cur) => cur ?? r);
        setFromChat(true);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
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
    <div className={heroUp ? "mx-auto grid w-full max-w-5xl gap-6" : "grid gap-6 lg:grid-cols-[380px_1fr]"}>
      <aside className={`min-w-0 space-y-4 lg:sticky lg:top-6 lg:self-start ${heroUp ? "hidden" : ""}`}>
        {/* While the hero is up it carries the h1, the pitch and the demo trades; the rail
            repeats none of them, and takes over once the hero is gone. */}
        {report || heroUsed ? (
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{tx("Stress-test a trade", "给交易做压力测试")}</h1>
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
                scrollIntoViewOnSmall(resultRef.current);
              }}
            />
          </TabsContent>
        </Tabs>
      </aside>

      <section ref={resultRef} className="min-w-0 scroll-mt-4" aria-live="polite" aria-busy={busy}>
        {busy && !report ? <ReportSkeleton /> : null}
        {error && tab !== "form" ? (
          <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
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
          <div className="space-y-3 rounded-lg border border-border p-4">
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
        ) : !busy && !error && !contrast && exampleReport ? (
          <div className="space-y-3">
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
          </div>
        ) : !busy && !error && !contrast ? (
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
const HERO_CHIPS: { en: string; zh: string; short: string; shortZh: string; send?: string }[] = [
  { en: "Long NVDA over the weekend — is 15k safe?", zh: "周末做多 NVDA，1.5 万安全吗？", short: "NVDA weekend 15k", shortZh: "周末 NVDA 1.5 万", send: "Long NVDA over the weekend, 15k, thesis: earnings momentum, wrong if it closes below 170 — is it safe?" },
  { en: "5x long TSLA overnight?", zh: "5 倍杠杆做多 TSLA 过夜？", short: "5x TSLA overnight", shortZh: "5 倍 TSLA 过夜", send: "5x long 10k TSLA overnight — safe?" },
  { en: "周末做多特斯拉 2万U 安全吗？", zh: "周末做多特斯拉 2万U 安全吗？", short: "周末做多特斯拉", shortZh: "周末做多特斯拉", send: "周末做多 TSLA 2万U，安全吗？" },
];

const CHIP = "inline-flex min-h-10 items-center sm:min-h-8 rounded-full border border-border px-3 py-1 text-[13px] hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

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
    <ul className="mt-3 hidden min-h-8 flex-wrap gap-2 sm:flex" aria-label={tx("Proof", "证据")}>
      {has ? (
        <>
          <li>
            {/* The same /misses number the page it links to shows as "Live verdicts scored": verdicts whose hold has ended and whose outcome is known. */}
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

const HERO_STEPS: { en: string; zh: string; subEn: string; subZh: string }[] = [
  { en: "Similar past moments", zh: "相似的历史时刻", subEn: "the nights most like now", subZh: "与现在最像的那些夜晚" },
  { en: "What happened after", zh: "之后发生了什么", subEn: "real outcomes, best to worst", subZh: "真实结果，从好到坏" },
  { en: "Stress tests", zh: "压力测试", subEn: "gaps, crashes, thin books", subZh: "跳空、暴跌、盘口变薄" },
  { en: "Sized verdict", zh: "带仓位的结论", subEn: "GO, REDUCE, HEDGE or NO GO", subZh: "可以做、减仓、对冲或不做" },
];

function Hero({ draft, setDraft, busy, onSend, onContrast, onExample, exampleDisabled, onForm }: { draft: string; setDraft: (s: string) => void; busy: boolean; onSend: (t: string) => void; onContrast: () => void; onExample: () => void; exampleDisabled: boolean; onForm: () => void }) {
  const { lang, tx } = useLang();
  const text = draft.trim();
  return (
    <section className="rounded-xl border border-border bg-card p-4 sm:p-6" aria-label={tx("Describe a trade", "描述一笔交易")}>
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{tx("Stress-test the trade before you place it.", "下单之前，先给这笔交易做压力测试。")}</h1>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
        {tx("A pre-trade desk for tokenized US stocks on Bitget. ", "Bitget 上代币化美股的交易前工作台。")}
        <span className="hidden sm:inline">
          {tx(
            "It prices your exit on the live order book and sizes the trade in money. Every verdict is scored in public.",
            "按实时订单簿计算平仓成本，并以金额给出仓位。每个结论都会公开评分。",
          )}
        </span>
      </p>
      <form
        className="mt-4 flex flex-col gap-2 sm:flex-row"
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
            // Enter sends, Shift+Enter breaks the line; ignore Enter while an IME is composing.
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (text && !busy) onSend(text);
            }
          }}
          placeholder={tx("e.g. long NVDA over the weekend, 15k", "例如：周末做多 NVDA，1.5 万")}
          disabled={busy}
          className="min-w-0 flex-1 h-14 resize-none rounded-lg border border-input bg-background px-4 py-3 text-base focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none sm:h-14 sm:py-3.5 sm:text-lg"
        />
        <Button type="submit" disabled={busy || !text} className="h-12 px-6 text-base sm:h-14">
          {tx("Get the verdict", "获取结论")}
        </Button>
      </form>
      <ul className="mt-3 flex flex-wrap gap-2">
        {HERO_CHIPS.map((c) => (
          <li key={c.en} className="shrink-0">
            <button
              type="button"
              disabled={busy}
              title={lang === "zh" ? c.zh : c.en}
              onClick={() => onSend(c.send ?? c.en)}
              className={`${CHIP} whitespace-nowrap text-muted-foreground disabled:opacity-50`}
            >
              {lang === "zh" ? c.shortZh : c.short}
            </button>
          </li>
        ))}
        <li className="shrink-0">
          <button type="button" disabled={exampleDisabled} onClick={onExample} title={tx("Run the example trade below live, right now", "立即实时运行下面的示例交易")} className={`${CHIP} whitespace-nowrap border-foreground/40 font-medium disabled:opacity-50`}>
            {tx("Run the TSLA example live", "实时运行 TSLA 示例")}
          </button>
        </li>
        <li className="shrink-0">
          <button type="button" disabled={busy} onClick={onContrast} title={tx("Run one trade alone and on a concentrated book, side by side", "把同一笔交易单独运行，并叠加在集中的组合上，并排对比")} className={`${CHIP} whitespace-nowrap text-muted-foreground disabled:opacity-50`}>
            {tx("Same trade, different book", "同一笔交易，不同组合")}
          </button>
        </li>
      </ul>
      {/* Hidden on a phone: the example verdict below says the same thing, and these boxes pushed it a screen down. */}
      <ol className="mt-4 hidden grid-cols-4 gap-2 sm:grid" aria-label={tx("How it works", "工作方式")}>
        {HERO_STEPS.map((st, i) => (
          <li key={st.en} className="rounded-lg border border-border bg-muted/30 px-2.5 py-1.5 sm:px-3 sm:py-2">
            <p className="text-[13px] font-medium leading-tight">
              <span className="tabular mr-1 text-muted-foreground">{i + 1}</span>
              {lang === "zh" ? st.zh : st.en}
            </p>
            <p className="mt-0.5 hidden text-xs leading-snug text-muted-foreground sm:block">{lang === "zh" ? st.subZh : st.subEn}</p>
          </li>
        ))}
      </ol>
      <HeroProof />
      <p className="mt-2 text-[13px] text-muted-foreground">
        {tx("Prefer fields? ", "更喜欢填表？")}
        <button type="button" onClick={onForm} className="underline underline-offset-2 hover:text-foreground">
          {tx("Use the ticket form", "使用表单")}
        </button>
      </p>
    </section>
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
