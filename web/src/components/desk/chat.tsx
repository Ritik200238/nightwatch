"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api, type Report } from "@/lib/api";

interface Msg {
  role: "user" | "assistant";
  content: string;
  unverified?: string[];
  /** Which part of the report this answer was read out of, when it answered a question. */
  readFrom?: string;
  /** Who wrote it, when it was the model rather than the desk's own fields. */
  byline?: string;
}

interface Props {
  accountEquity: number | null;
  busy: boolean;
  setBusy: (b: boolean) => void;
  onReport: (r: Report) => void;
}

const STARTERS = ["Hold $20k of TSLA through the weekend, stop at 350", "Short 5k NVDA for the next 12 hours", "Long 10k SPY until Monday open, thesis: strong Friday close"];

/** Offered once a report is on screen, because until then there is nothing to ask about. */
const FOLLOW_UPS = ["Why not bigger?", "What if I double it?", "Was it worse on earnings nights?", "What if I only held it 6 hours?", "Has this setup burned me before?", "Talk me out of it"];

/** What each kind of question was answered out of. Shown under the answer so the reader
 *  can go and check it rather than take the sentence on trust. */
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
};

export function Chat({ accountEquity, busy, setBusy, onReport }: Props) {
  const [messages, setMessages] = useState<Msg[]>([]);
  // The report the conversation is currently about. Questions are answered from it.
  const [contextId, setContextId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  // null = not checked yet. The desk works without a model; only this tab needs one.
  const [ready, setReady] = useState<boolean | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

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
    for (let i = 0; i < 40; i++) {
      try {
        const t = i === 0 ? await api.analystStart(id, lang) : await api.analystGet(id, lang);
        if (t.status === "done" && t.text) {
          const label = lang === "zh" ? "分析师的看法" : "Analyst's take";
          setMessages((m) => [...m, { role: "assistant", content: `${label}\n\n${t.text}`, byline: lang === "zh" ? "由 Qwen 撰写 · 数字已与报告核对，推理是模型自己的，可能出错" : "Written by Qwen · numbers checked against the report; the reasoning is the model's and can be wrong" }]);
          return;
        }
        if (t.status !== "pending") return;
      } catch {
        return;
      }
      await new Promise((r) => setTimeout(r, 3000));
    }
  }

  async function send(text: string) {
    const content = text.trim();
    if (!content || busy) return;
    const next: Msg[] = [...messages, { role: "user", content }];
    setMessages(next);
    setDraft("");
    setError(null);
    setBusy(true);
    try {
      const res = await api.chat(
        next.map((m) => ({ role: m.role, content: m.content })),
        accountEquity,
        contextId,
      );
      setMessages([...next, { role: "assistant", content: res.reply, unverified: res.unverified_numbers, readFrom: res.answer_kind ? READ_FROM[res.answer_kind] : undefined }]);
      // A follow-up answers about the report already on screen and leaves it there.
      if (res.report) {
        onReport(res.report);
        const id = (res.report.forecast_id as number | null) ?? null;
        setContextId(id);
        if (id != null && res.mode !== "what_if") void followWithTake(id, /[\u3400-\u9fff]/.test(content) ? "zh" : "en");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Something went wrong.";
      setError(msg);
      setMessages(next);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full min-h-[320px] flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto pr-1" role="log" aria-live="polite" aria-label="Conversation">
        {ready === false ? (
          <div className="mb-3 rounded-lg border border-border bg-muted/40 p-3 text-sm">
            <p className="font-medium">Reading your words with rules, not a model</p>
            <p className="text-xs text-muted-foreground">
              This server has no Anthropic API key, so a parser handles the sentence instead. It understands the usual shape — &ldquo;long 25k TSLA overnight, stop 340&rdquo; — and every
              number in the answer is copied from the report. With a key the same conversation gets more range.
            </p>
          </div>
        ) : null}
        {messages.length === 0 ? (
          <div className="space-y-3 py-2">
            <p className="text-sm text-muted-foreground">Describe the trade in plain words. I will ask for anything missing, run the numbers, and explain them.</p>
            <ul className="space-y-2">
              {STARTERS.map((s) => (
                <li key={s}>
                  <button type="button" onClick={() => void send(s)} disabled={busy} className="w-full rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50">
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "ml-6 rounded-lg bg-primary/10 px-3 py-2 text-sm" : "mr-2 rounded-lg bg-muted px-3 py-2 text-sm"}>
            <p className="whitespace-pre-wrap">{m.content}</p>
            {m.readFrom ? <p className="mt-2 text-xs text-muted-foreground">Read out of {m.readFrom}.</p> : null}
            {m.byline ? <p className="mt-2 text-xs text-muted-foreground">{m.byline}</p> : null}
            {m.unverified && m.unverified.length ? <p className="mt-2 text-xs text-status-warning">Numbers not found in the report: {m.unverified.join(", ")}</p> : null}
          </div>
        ))}
        {/* Once there is a report, offer the questions it can answer about itself. Nobody
            guesses that a stress tester will tell them what a 6% stop would do. */}
        {contextId != null && !busy ? (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {FOLLOW_UPS.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => void send(q)}
                className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                {q}
              </button>
            ))}
          </div>
        ) : null}
        {busy ? (
          <div className="mr-2 space-y-2 rounded-lg bg-muted px-3 py-2" aria-label="Working">
            <div className="h-3 w-3/4 animate-pulse rounded bg-background/60" />
            <div className="h-3 w-1/2 animate-pulse rounded bg-background/60" />
          </div>
        ) : null}
        {error ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
            <p className="font-medium">Couldn&apos;t get an answer</p>
            <p className="text-xs text-muted-foreground">{error}</p>
            <p className="mt-2 text-xs text-muted-foreground">You can still use the ticket form on the other tab.</p>
          </div>
        ) : null}
        <div ref={endRef} />
      </div>
      <form
        className="mt-3 flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        <label htmlFor="chat-input" className="sr-only">
          Describe your trade
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
          placeholder="e.g. hold 20k of TSLA through the weekend, stop at 350"
          disabled={busy}
          className="min-h-[44px] resize-none"
        />
        <Button type="submit" disabled={busy || !draft.trim()} className="h-11">
          Send
        </Button>
      </form>
    </div>
  );
}
