"use client";

import { BellRing, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { engagement, EngagementError } from "@/lib/engagement";
import { type Lang, tr } from "@/lib/i18n";

const KEY = (id: number) => `nightwatch.feedback.${id}`;

/** "Was this useful?" under a report, once per report per browser, with an optional note.
 *  The answer is the product's only direct evidence that a verdict helped someone, so it
 *  is asked plainly and never required. The server also refuses a second answer. */
export function Feedback({ forecastId, lang = "en" }: { forecastId: number; lang?: Lang }) {
  const L = tr(lang);
  const [done, setDone] = useState(false);
  const [pick, setPick] = useState<boolean | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      setDone(localStorage.getItem(KEY(forecastId)) === "1");
    } catch {
      /* storage blocked: the server still refuses a second answer */
    }
  }, [forecastId]);

  function remember() {
    try {
      localStorage.setItem(KEY(forecastId), "1");
    } catch {
      /* not remembered */
    }
  }

  async function send(useful: boolean) {
    setBusy(true);
    setError(null);
    try {
      await engagement.feedback({ forecast_id: forecastId, useful, note: note.trim(), lang });
      setDone(true);
      remember();
    } catch (e) {
      if (e instanceof EngagementError && e.status === 409) {
        setDone(true);
        remember();
      } else {
        setError(
          e instanceof EngagementError && e.status === 429
            ? L("Too many answers just now. Try again later.", "刚才提交太多次了，请稍后再试。")
            : L("Could not send that. Try again.", "发送失败，请重试。"),
        );
      }
    } finally {
      setBusy(false);
    }
  }

  if (done) return <p className="text-xs text-muted-foreground">{L("Thanks - that helps us fix what is wrong.", "谢谢，这能帮我们改进。")}</p>;

  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground">{L("Was this useful?", "这份报告有用吗？")}</span>
        <Button variant={pick === true ? "default" : "outline"} size="sm" aria-pressed={pick === true} disabled={busy} onClick={() => setPick(true)}>
          <ThumbsUp aria-hidden /> {L("Yes", "有用")}
        </Button>
        <Button variant={pick === false ? "default" : "outline"} size="sm" aria-pressed={pick === false} disabled={busy} onClick={() => setPick(false)}>
          <ThumbsDown aria-hidden /> {L("No", "没用")}
        </Button>
      </div>
      {pick !== null ? (
        <div className="flex flex-wrap items-start gap-2">
          <label className="sr-only" htmlFor={`fb-note-${forecastId}`}>
            {L("Optional note", "可选备注")}
          </label>
          <textarea
            id={`fb-note-${forecastId}`}
            value={note}
            maxLength={500}
            rows={2}
            onChange={(e) => setNote(e.target.value)}
            placeholder={L("Optional: what was useful or wrong? Do not include contact details.", "可选：哪里有用，哪里不对？请勿填写联系方式。")}
            className="min-w-56 flex-1 rounded-lg border border-border bg-background p-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          />
          <Button size="sm" disabled={busy} onClick={() => void send(pick)}>
            {L("Send", "发送")}
          </Button>
        </div>
      ) : null}
      {error ? <p className="text-xs text-status-critical">{error}</p> : null}
    </div>
  );
}

/** Ask the desk to judge the same trade again at the next US close. The recorder does it;
 *  the page it opens shows the verdict then and now. Email is not offered. */
export function WatchButton({ forecastId, lang = "en" }: { forecastId: number; lang?: Lang }) {
  const L = tr(lang);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHook, setShowHook] = useState(false);
  const [hook, setHook] = useState("");

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const w = await engagement.watch({ forecast_id: forecastId, webhook: hook.trim() || null, lang });
      window.location.assign(`/watch/${w.id}`);
    } catch (e) {
      setError(e instanceof EngagementError ? e.message : L("Could not start that.", "无法开始。"));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" disabled={busy} onClick={() => void start()}>
          <BellRing aria-hidden /> {L("Re-check at the next US close", "在下一个美股收盘时复查")}
        </Button>
        {!showHook ? (
          <button type="button" onClick={() => setShowHook(true)} className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground">
            {L("or send it to a webhook", "或发送到 webhook")}
          </button>
        ) : null}
      </div>
      {showHook ? (
        <input
          value={hook}
          onChange={(e) => setHook(e.target.value)}
          inputMode="url"
          aria-label={L("Webhook URL (https only)", "Webhook 地址（仅 https）")}
          placeholder="https://..."
          className="w-full max-w-md rounded-lg border border-border bg-background p-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        />
      ) : null}
      <p className="text-xs text-muted-foreground">
        {L("No email: open the link it gives you, or use a webhook.", "不发邮件：打开它给你的链接，或使用 webhook。")}{" "}
        <Link href="/usage" className="underline underline-offset-2">
          {L("what we count", "我们统计什么")}
        </Link>
      </p>
      {error ? <p className="text-xs text-status-critical">{error}</p> : null}
    </div>
  );
}
