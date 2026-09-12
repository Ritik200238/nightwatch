"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api, type Report } from "@/lib/api";

interface Msg {
  role: "user" | "assistant";
  content: string;
  unverified?: string[];
}

interface Props {
  accountEquity: number | null;
  busy: boolean;
  setBusy: (b: boolean) => void;
  onReport: (r: Report) => void;
}

const STARTERS = ["Hold $20k of TSLA through the weekend, stop at 350", "Short 5k NVDA for the next 12 hours", "Long 10k SPY until Monday open, thesis: strong Friday close"];

export function Chat({ accountEquity, busy, setBusy, onReport }: Props) {
  const [messages, setMessages] = useState<Msg[]>([]);
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
      );
      setMessages([...next, { role: "assistant", content: res.reply, unverified: res.unverified_numbers }]);
      if (res.report) onReport(res.report);
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
            <p className="font-medium">Plain-language entry is switched off</p>
            <p className="text-xs text-muted-foreground">This server has no Anthropic API key, so trade ideas cannot be parsed from free text. The ticket form on the other tab runs exactly the same analysis.</p>
          </div>
        ) : null}
        {messages.length === 0 ? (
          <div className="space-y-3 py-2">
            <p className="text-sm text-muted-foreground">Describe the trade in plain words. I will ask for anything missing, run the numbers, and explain them.</p>
            <ul className="space-y-2">
              {STARTERS.map((s) => (
                <li key={s}>
                  <button type="button" onClick={() => void send(s)} disabled={busy || ready === false} className="w-full rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50">
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
            {m.unverified && m.unverified.length ? <p className="mt-2 text-xs text-status-warning">Numbers not found in the report: {m.unverified.join(", ")}</p> : null}
          </div>
        ))}
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
          placeholder={ready === false ? "Use the ticket form: this server has no model key" : "e.g. hold 20k of TSLA through the weekend, stop at 350"}
          disabled={busy || ready === false}
          className="min-h-[44px] resize-none"
        />
        <Button type="submit" disabled={busy || ready === false || !draft.trim()} className="h-11">
          Send
        </Button>
      </form>
    </div>
  );
}
