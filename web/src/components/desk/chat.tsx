"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api, type ChatCard, type ChatStep, type Report } from "@/lib/api";
import { useLang } from "@/lib/lang";
import { isoIn, isSnapshotAnswer, snapshotFlag, snapshotNoticeFor } from "@/lib/snapshot";
import { plainText } from "@/lib/plain";
import { startAgent, useAgent } from "@/lib/agent-run";
import { loadChat, saveChat, saveReportId } from "@/lib/desk-session";
import { GuardNote } from "@/components/report/guard-note";
import { verdictText } from "@/lib/verdict-style";
import { ChatCardView } from "./chat-card";
import { Working } from "./working";
import { reducedMotion, scrollToMessageStart } from "@/lib/scroll";

interface Msg {
  role: "user" | "assistant";
  content: string;
  unverified?: string[];
  /** Which part of the report this answer was read out of, when it answered a question. */
  readFrom?: string;
  /** Who wrote it, when it was the model rather than the desk's own fields. */
  byline?: string;
  /** Sentences the number guard dropped from a model take. */
  removed?: number;
  /** The small picture of the answer's own numbers, when the desk drew one. */
  card?: ChatCard;
  /** The verdict of the report generated on this turn, if any. */
  reportVerdict?: string;
}

interface Props {
  accountEquity: number | null;
  busy: boolean;
  setBusy: (b: boolean) => void;
  onReport: (r: Report, lang: "en" | "zh") => void;
  /** Called once when a conversation from this tab is brought back, so the page can leave its start screen. */
  onRestore?: () => void;
  /** Called when the trader starts a new chat, so the page can drop the report the old one was about. */
  onNewChat?: () => void;
  /** A canned run: each step is sent as if typed, once, in order. */
  script?: { id: number; steps: string[] } | null;
}

const STARTERS = ["Hold $20k of TSLA through the weekend, stop at 350", "Short 5k NVDA for the next 12 hours", "Long 10k SPY until Monday open, thesis: strong Friday close"];
const STARTERS_ZH = ["持有 2 万美元 TSLA 过周末，止损 350", "做空 5000 美元 NVDA，持有 12 小时", "做多 1 万美元 SPY 到周一开盘，理由：周五收盘强势"];
const HAS_ZH = /[\u3400-\u9fff]/;

/** The server needs the recent turns and the report id, not the whole scroll-back; only this many
 *  of the newest messages are sent, so a long conversation never hits the request's size limit. */
const SEND_TAIL = 20;

/** Offered once a report is on screen, because until then there is nothing to ask about. */
const FOLLOW_UPS = ["Why?", "Explain it simply", "What's the safest way to hold it?", "What if it gaps down 10%?", "Compare it with SPY", "Short it instead", "Talk me out of it"];
const FOLLOW_UPS_ZH = ["为什么？", "简单解释一下", "最安全的持有方式是什么？", "如果跌 10% 呢？", "和 SPY 比呢？", "反过来做空呢？", "最坏会亏多少？"];
/** A short loses when the stock rises, so its shock and its flip point the other way. */
const SHORT_SWAPS: Record<string, string> = {
  "What if it gaps down 10%?": "What if it gaps up 10%?",
  "Short it instead": "Go long instead",
  "如果跌 10% 呢？": "如果涨 10% 呢？",
  "反过来做空呢？": "反过来做多呢？",
};

function followUps(lang: string, side: string | null): string[] {
  const base = lang === "zh" ? FOLLOW_UPS_ZH : FOLLOW_UPS;
  return side === "short" ? base.map((q) => SHORT_SWAPS[q] ?? q) : base;
}

/** What each kind of question was answered out of. Shown under the answer so the reader
 *  can go and check it rather than take the sentence on trust. */
const READ_FROM_ZH: Record<string, string> = {
  size: "仓位上限和仓位扫描",
  stop: "止损扫描",
  worst: "压力预设和模拟",
  exit: "盘口及其历史存档",
  history: "相似时刻样本和基线检验",
  lessons: "已评分的复盘",
  gate: "纪律关卡",
  against: "反方论据",
  hedge: "对冲报价",
  regime: "市场状态图",
  moments: "匹配到的历史时刻",
  trust: "尾部调整",
  now: "当前快照",
  what_if: "针对同一时刻重新运行交易台",
  plain: "相似时刻样本、失败模式、盘口和结论",
  decide: "结论和相似时刻样本",
  data: "实时数据源列表",
};
const READ_FROM: Record<string, string> = {
  size: "sizing caps and the size sweep",
  stop: "the stop sweep",
  worst: "stress presets and the simulation",
  exit: "the order book and its archive",
  history: "the analog cohort and the baseline test",
  lessons: "scored post-mortems",
  gate: "the discipline gate",
  against: "the case against",
  hedge: "the hedge quote",
  regime: "the regime map",
  moments: "the matched moments",
  trust: "the tail adjustment",
  now: "the snapshot",
  what_if: "a fresh run of the desk against the same moment",
  plain: "the analog cohort, the failure modes, the order book and the verdict",
  decide: "the verdict and the analog cohort",
  data: "the list of live sources",
};

function parseVerdictKey(m: Msg, hasReportOnScreen: boolean): string | null {
  if (m.reportVerdict) return m.reportVerdict;
  if (!hasReportOnScreen || m.role !== "assistant") return null;
  if (/(?:^|\n)VERDICT:\s*([A-Z_ ]+)/i.test(m.content)) {
    const match = m.content.match(/(?:^|\n)VERDICT:\s*([A-Z_ ]+)/i);
    return match ? match[1].trim().toUpperCase().replace(/\s+/g, "_") : null;
  }
  if (/^(?:REVIEW|需复核)[：:]/i.test(m.content)) return "REVIEW";
  if (/^(?:GO|可以做)[：:]/i.test(m.content)) return "GO";
  if (/^(?:NO GO|NO-GO|不建议做)[：:]/i.test(m.content)) return "NO_GO";
  if (/^(?:REDUCE TO|减仓|建议减仓)[：:]/i.test(m.content)) return "REDUCE_TO";
  if (/^(?:HEDGE|对冲|建议对冲)[：:]/i.test(m.content)) return "HEDGE";
  return null;
}

function verdictLabelFor(v: string, zh: boolean): string {
  if (!zh) return v.replace(/_/g, " ");
  switch (v) {
    case "GO": return "可以做";
    case "REDUCE_TO": return "建议减仓";
    case "HEDGE": return "建议对冲";
    case "REVIEW":
    case "REVIEW_REQUIRED": return "需要复核";
    case "NO_GO": return "不建议做";
    default: return v;
  }
}

export function Chat({ accountEquity, busy, setBusy, onReport, onRestore, onNewChat, script }: Props) {
  const { lang, setLang, tx } = useLang();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [expandedMap, setExpandedMap] = useState<Record<number, boolean>>({});
  // The report the conversation is currently about. Questions are answered from it.
  const [contextId, setContextId] = useState<number | null>(null);
  // Its side, so the suggested questions are the ones that hurt this position.
  const [side, setSide] = useState<string | null>(null);
  // Refs mirror the two above so a scripted run sees its own earlier steps.
  const messagesRef = useRef<Msg[]>([]);
  const contextRef = useRef<number | null>(null);
  const ranScript = useRef<number | null>(null);
  const [draft, setDraft] = useState("");
  const [steps, setSteps] = useState<ChatStep[]>([]);
  const [takePending, setTakePending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // null = not checked yet. The desk works without a model; only this tab needs one.
  const [ready, setReady] = useState<boolean | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const agent = useAgent(contextId, lang);
  const postedAgent = useRef<string | null>(null);

  // When the agent finishes, its summary joins the conversation once.
  useEffect(() => {
    const f = agent.run?.final;
    const tag = contextId != null ? `${contextId}:${lang}` : null;
    if (agent.run?.status !== "done" || !f || !tag || postedAgent.current === tag) return;
    postedAgent.current = tag;
    const n = agent.run.steps?.length ?? 0;
    const body = [f.summary, ...(f.findings ?? []).map((x) => `- ${x}`), f.verdict_restated].filter(Boolean).join("\n");
    setMessages((m) => [...m, { role: "assistant", content: body, removed: agent.run?.removed, byline: lang === "zh" ? `Nightwatch 代理 · Qwen · 在引擎上运行了 ${n} 项检查，数字已核对` : `Nightwatch agent · Qwen · ${n} checks run on the engine, numbers verified` }]);
  }, [agent.run, contextId, lang]);

  // What the next change to the transcript should do to the page. Set by send() only, so a restored
  // conversation or a late agent note never moves the reader. "end": the reader's own message, keep
  // it and the progress below it in view. "start": a plain reply, read from its first line. "none":
  // the answer is a new report and the page scrolls to that instead.
  const scrollMode = useRef<"end" | "start" | "none">("none");
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const mode = scrollMode.current;
    scrollMode.current = "none";
    if (mode === "end") {
      endRef.current?.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
    } else if (mode === "start") {
      const all = logRef.current?.querySelectorAll<HTMLElement>("[data-msg]");
      scrollToMessageStart(all && all.length ? all[all.length - 1] : null);
    }
  }, [messages.length]);

  // A refresh or the Back button brings the conversation back from this tab's storage; the
  // page reloads the report itself from /reports/<id>. A /?q= link starts a fresh conversation.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    const saved = new URLSearchParams(window.location.search).has("q") ? null : loadChat<Msg>();
    if (saved) {
      let restored = saved.messages;
      if (restored[restored.length - 1]?.role === "user") {
        // The page went away while that message was being answered; say so instead of leaving it hanging.
        restored = [...restored, { role: "assistant", content: tx("This page was reloaded while that message was being answered, so there is no answer to it. Send it again to run it.", "这条消息还没回答完页面就被刷新了，所以没有答案。请再发一次。") }];
      }
      messagesRef.current = restored;
      setMessages(restored);
      contextRef.current = saved.contextId;
      setContextId(saved.contextId);
      setSide(saved.side);
      onRestore?.();
    }
    setHydrated(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (hydrated) saveChat<Msg>({ messages, contextId, side });
  }, [hydrated, messages, contextId, side]);

  useEffect(() => {
    let cancelled = false;
    void api
      .health()
      .then((h) => !cancelled && setReady(h.chat_ready))
      .catch(() => !cancelled && setReady(null));
    return () => {
      cancelled = true;
    };
  }, []);

  /** The instant answer is the desk's own; a few seconds later the model's reading of
   *  the same report follows as a second message, the way an analyst would reply. */
  async function followWithTake(id: number, lang: "en" | "zh") {
    setTakePending(true);
    try {
      await pollTake(id, lang);
    } finally {
      setTakePending(false);
    }
  }

  async function pollTake(id: number, lang: "en" | "zh") {
    for (let i = 0; i < 40; i++) {
      try {
        const t = i === 0 ? await api.analystStart(id, lang) : await api.analystGet(id, lang);
        if (t.status === "done" && t.text) {
          const label = lang === "zh" ? "分析师的看法" : "Analyst's take";
          const debate = [t.for ? `${lang === "zh" ? "支持的理由" : "Case for"}: ${t.for}` : "", t.against ? `${lang === "zh" ? "反对的理由" : "Case against"}: ${t.against}` : "", t.reconcile ?? ""].filter(Boolean).join("\n");
          setMessages((m) => [...m, { role: "assistant", content: `${label}\n\n${debate ? `${debate}\n\n` : ""}${t.text}`, byline: lang === "zh" ? "由 Qwen 撰写 · 数字已与报告核对，推理是模型自己的，可能出错" : "Written by Qwen · numbers checked against the report; the reasoning is the model's and can be wrong", removed: t.removed }]);
          return;
        }
        if (t.status !== "pending") return;
      } catch {
        return;
      }
      await new Promise((r) => setTimeout(r, 3000));
    }
  }

  function commit(m: Msg[]) {
    messagesRef.current = m;
    setMessages(m);
  }

  /** Forget this conversation: the saved copy in this tab, the report it was about, and any error. */
  function newChat() {
    if (busy) return;
    commit([]);
    contextRef.current = null;
    setContextId(null);
    setSide(null);
    setSteps([]);
    setError(null);
    setDraft("");
    postedAgent.current = null;
    saveChat<Msg>({ messages: [], contextId: null, side: null });
    saveReportId(null);
    onNewChat?.();
  }

  async function send(text: string) {
    const content = text.trim();
    if (!content || busy) return;
    // Writing Chinese switches the whole page to Chinese; an English message leaves it as it is.
    const chatLang: "en" | "zh" = HAS_ZH.test(content) ? "zh" : lang;
    if (chatLang !== lang) setLang(chatLang);
    const next: Msg[] = [...messagesRef.current, { role: "user", content }];
    scrollMode.current = "end";
    commit(next);
    setDraft("");
    setError(null);
    setBusy(true);
    try {
      setSteps([]);
      const res = await api.chatStream(
        next.slice(-SEND_TAIL).map((m) => ({ role: m.role, content: m.content })),
        accountEquity,
        contextRef.current,
        (s) => setSteps((prev) => (prev.some((p) => p.stage === s.stage) ? prev : [...prev, s])),
        chatLang,
      );
      // A saved example served while the live server is down is a chat message only: it
      // must never replace the report on screen, which belongs to the trader's own trade.
      if (isSnapshotAnswer(res, snapshotFlag.get())) {
        scrollMode.current = "start";
        commit([...next, { role: "assistant", content: snapshotNoticeFor(snapshotFlag.get() ?? isoIn(res.reply), chatLang) }]);
        return;
      }
      const reportVerdict = res.report ? ((res.report.verdict?.verdict as string) ?? "REVIEW") : undefined;
      scrollMode.current = res.report ? "none" : "start";
      commit([
        ...next,
        {
          role: "assistant",
          content: res.reply,
          unverified: res.unverified_numbers,
          readFrom: res.answer_kind ? (chatLang === "zh" ? READ_FROM_ZH : READ_FROM)[res.answer_kind] : undefined,
          card: res.card,
          reportVerdict,
        },
      ]);
      // A follow-up answers about the report already on screen and leaves it there.
      if (res.report) {
        onReport(res.report, chatLang);
        const id = (res.report.forecast_id as number | null) ?? null;
        contextRef.current = id;
        setContextId(id);
        const reportSide = (res.report.ticket as { side?: string } | undefined)?.side;
        if (reportSide) setSide(reportSide);
        if (id != null && res.mode !== "what_if") void followWithTake(id, chatLang);
      }
    } catch (e) {
      // The error text follows the language the trader wrote in, not the page's last setting.
      const zhNow = HAS_ZH.test(content) || lang === "zh";
      const msg =
        e instanceof ApiError
          ? zhNow && e.status === 0
            ? "无法连接到 Nightwatch 服务，请稍后再发一次。"
            : zhNow && (e.status === 502 || e.status === 503) && /^[ -~]+$/.test(e.message)
              ? "服务暂时没有响应，请稍后再发一次。"
              : e.message
          : tx("Something went wrong.", "出错了。");
      setError(msg);
      scrollMode.current = "none";
      commit(next);
    } finally {
      setBusy(false);
      setSteps([]);
    }
  }

  useEffect(() => {
    if (!script || ranScript.current === script.id) return;
    ranScript.current = script.id;
    void (async () => {
      for (const step of script.steps) {
        await send(step);
        // A failed step leaves the error on screen; do not stack the next question on it.
        if (!contextRef.current) break;
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [script]);

  return (
    <div className="flex h-full min-h-[320px] flex-col">
      <div ref={logRef} className="flex-1 space-y-3 overflow-y-auto pr-1" role="log" aria-live="polite" aria-label={tx("Conversation", "对话")}>
        {ready === false ? (
          <div className="mb-3 border-l-2 border-border pl-3 text-sm">
            <p className="font-medium">{tx("Reading your words with rules, not a model", "用规则而不是模型来理解你的话")}</p>
            <p className="text-[13px] text-muted-foreground">
              {tx("This server has no Anthropic API key, so a parser handles the sentence instead. It understands the usual shape — “long 25k TSLA overnight, stop 340” — and every number in the answer is copied from the report. With a key the same conversation gets more range.", "这台服务器没有 Anthropic API 密钥，所以由解析器处理你的句子。它能理解常见的写法——“做多 2.5 万 TSLA 过夜，止损 340”——回答里的每个数字都取自报告。有密钥时，同样的对话能覆盖更多情况。")}
            </p>
          </div>
        ) : null}
        {messages.length === 0 ? (
          <div className="space-y-3 py-2">
            <p className="text-sm text-muted-foreground">{tx("Describe the trade in plain words. I will ask for anything missing, run the numbers, and explain them.", "用大白话描述这笔交易。缺什么我会问你，然后计算并解释结果。")}</p>
            <ul className="space-y-2">
              {(lang === "zh" ? STARTERS_ZH : STARTERS).map((s) => (
                <li key={s}>
                  <button type="button" onClick={() => void send(s)} disabled={busy} className="w-full rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50">
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {messages.map((m, i) => {
          const vKey = parseVerdictKey(m, contextId != null);
          const isCollapsed = Boolean(vKey) && !expandedMap[i];

          if (isCollapsed) {
            return (
              <div key={i} data-msg={i} className="mr-2 rounded-lg bg-muted px-3 py-2 text-sm scroll-mt-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 font-medium">
                    <span>{tx("Verdict:", "结论：")}</span>
                    <span className={`font-semibold ${verdictText(vKey!)}`}>{verdictLabelFor(vKey!, lang === "zh")}</span>
                    <span className="text-muted-foreground">— {tx("see the report", "见报告")}</span>
                  </p>
                  <button
                    type="button"
                    onClick={() => setExpandedMap((prev) => ({ ...prev, [i]: true }))}
                    className="inline-flex min-h-7 items-center text-xs text-muted-foreground hover:text-foreground underline decoration-muted-foreground/60 underline-offset-2"
                  >
                    {tx("Show full answer", "展开完整回答")}
                  </button>
                </div>
              </div>
            );
          }

          return (
            <div key={i} data-msg={i} className={`scroll-mt-4 ${m.role === "user" ? "ml-6 rounded-lg bg-primary/10 px-3 py-2 text-sm" : "mr-2 rounded-lg bg-muted px-3 py-2 text-sm"}`}>
              {vKey ? (
                <div className="mb-2 flex items-center justify-between border-b border-border/40 pb-1.5">
                  <span className="text-xs font-medium text-muted-foreground">
                    {tx("Verdict:", "结论：")}{" "}
                    <span className={`font-semibold ${verdictText(vKey)}`}>{verdictLabelFor(vKey, lang === "zh")}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => setExpandedMap((prev) => ({ ...prev, [i]: false }))}
                    className="inline-flex min-h-6 items-center text-xs text-muted-foreground hover:text-foreground underline decoration-muted-foreground/60 underline-offset-2"
                  >
                    {tx("Collapse", "收起")}
                  </button>
                </div>
              ) : null}
              <p className="whitespace-pre-wrap">{m.role === "assistant" ? plainText(m.content, lang) : m.content}</p>
              {m.card ? <ChatCardView card={m.card} /> : null}
              {m.readFrom ? <p className="mt-2 text-[13px] text-muted-foreground">{tx(`Read out of ${m.readFrom}.`, `依据：${m.readFrom}。`)}</p> : null}
              {m.byline ? <p className="mt-2 text-[13px] text-muted-foreground">{m.byline}</p> : null}
              {m.removed ? <GuardNote n={m.removed} lang={lang} /> : null}
              {m.unverified && m.unverified.length ? <p className="mt-2 text-xs text-status-warning">{tx("Numbers not found in the report: ", "报告中找不到这些数字：")}{m.unverified.join(", ")}</p> : null}
            </div>
          );
        })}
        {/* Once there is a report, offer the questions it can answer about itself. Nobody
            guesses that a stress tester will tell them what a 6% stop would do. */}
        {contextId != null && !busy ? (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {contextId > 0 && !agent.started ? (
              <button
                type="button"
                onClick={() => startAgent(contextId, lang)}
                className="rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs max-sm:min-h-10 font-medium hover:bg-primary/20 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                {tx("Let the AI stress-test it", "让 AI 压力测试")}
              </button>
            ) : null}
            {agent.started && agent.run?.status === "running" ? (
              <span className="px-1 py-1 text-[13px] text-muted-foreground" role="status">
                {tx(`Agent running… ${agent.run.steps?.length ?? 0} checks done`, `代理运行中… 已完成 ${agent.run.steps?.length ?? 0} 项检查`)}
              </span>
            ) : null}
            {followUps(lang, side).map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => void send(q)}
                className="rounded-full border border-border px-3 py-1 text-[13px] max-sm:min-h-10 text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                {q}
              </button>
            ))}
          </div>
        ) : null}
        {busy ? (
          <div className="mr-2 rounded-lg bg-muted px-3 py-2" aria-label={tx("Working", "计算中")}>
            <Working compact lang={lang} steps={steps} />
          </div>
        ) : null}
        {takePending ? (
          <div className="mr-2 rounded-lg bg-muted px-3 py-2 text-sm" role="status">
            <p className="animate-pulse text-muted-foreground">{tx("Analyst writing… (about 10 s)", "分析师撰写中…（约 10 秒）")}</p>
            <div className="mt-2 space-y-1.5" aria-hidden>
              <div className="h-2.5 w-full animate-pulse rounded bg-foreground/10" />
              <div className="h-2.5 w-4/5 animate-pulse rounded bg-foreground/10" />
            </div>
          </div>
        ) : null}
        {error ? (
          <div role="alert" className="space-y-1 rounded-lg border border-destructive/30 p-4 text-sm">
            <p className="font-medium">{tx("Couldn't get an answer", "没能得到回答")}</p>
            <p className="text-[13px] text-muted-foreground">{error}</p>
            <p className="mt-2 text-[13px] text-muted-foreground">{tx("You can still use the ticket form on the other tab.", "你仍然可以使用另一个标签页里的表单。")}</p>
          </div>
        ) : null}
        <div ref={endRef} />
      </div>
      {messages.length > 0 ? (
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={newChat}
            disabled={busy}
            className="inline-flex min-h-10 items-center rounded-md border border-border px-3 text-[13px] text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50 sm:min-h-8"
          >
            {tx("New chat", "新对话")}
          </button>
        </div>
      ) : null}
      <form
        className="mt-3 flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        <label htmlFor="chat-input" className="sr-only">
          {tx("Describe your trade", "描述你的交易")}
        </label>
        <Textarea
          id="chat-input"
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(draft);
            }
          }}
          placeholder={tx("e.g. hold 20k of TSLA through the weekend, stop at 350", "例如 持有 2 万 TSLA 过周末，止损 350")}
          disabled={busy}
          className="min-h-[44px] resize-none"
        />
        <Button type="submit" disabled={busy || !draft.trim()} className="h-11">
          {tx("Send", "发送")}
        </Button>
      </form>
    </div>
  );
}
