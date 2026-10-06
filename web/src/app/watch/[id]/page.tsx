"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { TripwireList } from "@/components/report/tripwire";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { engagement, EngagementError, type Watch, type WatchSummary } from "@/lib/engagement";
import { fmtPct, fmtUsd } from "@/lib/format";
import { fmtTimeL, STRINGS } from "@/lib/i18n";
import { useLang } from "@/lib/lang";

/** The gate's own decision names ("REVIEW_REQUIRED") and the verdict's, as words. */
function decisionWord(lang: "en" | "zh", d: unknown): string {
  const k = String(d ?? "-");
  if (k === "-") return k;
  if (lang === "zh") return k === "REVIEW_REQUIRED" ? "需要复核" : (STRINGS.zh.verdictName as Record<string, string>)[k] ?? k;
  return k.replace(/_/g, " ");
}

function Column({ title, s, empty }: { title: string; s: WatchSummary | null; empty: string }) {
  const { tx, lang } = useLang();
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{title}</h3>
      {s ? (
        <div className="grid grid-cols-2 gap-3">
          <Stat label={tx("Verdict", "结论")} value={decisionWord(lang, s.verdict)} hint={s.as_of ? fmtTimeL(s.as_of, lang) : undefined} />
          <Stat label={tx("Size", "仓位")} value={s.recommended_notional != null ? fmtUsd(s.recommended_notional) : "-"} />
          <Stat label={tx("Gate", "风控检查")} value={decisionWord(lang, s.gate)} />
          <Stat label={tx("1-in-20 loss", "二十分之一的亏损")} value={s.tail_p5_pct != null ? fmtPct(s.tail_p5_pct) : "-"} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{empty}</p>
      )}
    </div>
  );
}

/** A trade judged again once the market has closed: the verdict then, and now. */
export default function WatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { tx, lang } = useLang();
  const [w, setW] = useState<Watch | null>(null);
  const [error, setError] = useState<{ message: string; missing: boolean } | null>(null);
  const [slow, setSlow] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setError(null);
    setSlow(false);
    const slowTimer = setTimeout(() => setSlow(true), 12_000);
    const load = () =>
      void engagement
        .getWatch(id)
        .then((r) => {
          if (cancelled) return;
          clearTimeout(slowTimer);
          setW(r);
          if (r.status === "pending") timer = setTimeout(load, 60_000);
        })
        .catch((e) => {
          if (cancelled) return;
          clearTimeout(slowTimer);
          setError({
            message: e instanceof EngagementError ? e.message : tx("Could not load that re-check.", "无法加载这次复查。"),
            // Only a 404 means the link is wrong; a busy or unreachable server is worth another try.
            missing: e instanceof EngagementError && e.status === 404,
          });
        });
    load();
    return () => {
      cancelled = true;
      clearTimeout(slowTimer);
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, attempt]);

  if (error && !w) {
    return (
      <div className="mx-auto max-w-xl space-y-3 py-10 text-center">
        <h1 className="text-lg font-semibold">{error.missing ? tx("That re-check is not here", "找不到这次复查") : tx("That re-check did not load", "这次复查没有加载出来")}</h1>
        <p className="text-sm text-muted-foreground">{error.message}</p>
        {error.missing ? null : (
          <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
            {tx("Try again", "重试")}
          </Button>
        )}
        <p>
          <Link href="/" className="inline-flex min-h-10 items-center text-sm underline underline-offset-2">
            {tx("Back to the desk", "回到交易台")}
          </Link>
        </p>
      </div>
    );
  }
  if (!w)
    return (
      <div className="space-y-4" role="status" aria-live="polite">
        <p className="text-sm text-muted-foreground">
          {slow ? tx("Still loading. The server is slow or not answering right now.", "仍在加载。服务器响应很慢，或暂时没有响应。") : tx("Loading the re-check…", "正在加载复查…")}
          {slow ? (
            <>
              {" "}
              <button type="button" onClick={() => setAttempt((n) => n + 1)} className="inline-flex min-h-10 items-center px-2 underline underline-offset-2 hover:text-foreground">
                {tx("Try again", "重试")}
              </button>
            </>
          ) : null}
        </p>
        <Skeleton className="h-64 w-full" />
      </div>
    );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">{tx("Re-check at the US close", "美股收盘复查")}</h1>
        <p className="text-sm text-muted-foreground">
          {w.status === "pending"
            ? tx(`Waiting for the next US close. It runs a few minutes after ${fmtTimeL(w.due_at, lang)}; this page refreshes itself.`, `等待下一个美股收盘。将在 ${fmtTimeL(w.due_at, lang)} 之后几分钟运行；本页会自动刷新。`)
            : w.status === "done"
              ? tx(`Done ${w.done_at ? fmtTimeL(w.done_at, lang) : ""}.`, `已完成 ${w.done_at ? fmtTimeL(w.done_at, lang) : ""}。`)
              : tx("The re-check could not run.", "复查未能运行。")}{" "}
          <Link href={`/r/${w.forecast_id}`} className="underline underline-offset-2">
            {tx("open the original report", "打开原报告")}
          </Link>
        </p>
      </div>
      {w.status === "failed" ? <p className="text-sm text-status-critical">{w.error}</p> : null}
      {w.moved != null ? <Pill tone={w.moved ? "warning" : "good"}>{w.moved ? tx("The call changed", "结论已变化") : tx("Same call", "结论未变")}</Pill> : null}
      <Section title={tx("Before and after", "前后对比")}>
        <div className="grid gap-6 md:grid-cols-2">
          <Column title={tx("When you asked", "提问时")} s={w.before} empty="" />
          <Column title={tx("At the close", "收盘时")} s={w.after} empty={tx("Not yet.", "尚未。")} />
        </div>
      </Section>
      <Section title={tx("Price tripwires on this report", "本报告的价格警报")}>
        <TripwireList forecastId={w.forecast_id} lang={lang} empty={tx("None set on this report yet.", "这份报告还没有设置价格警报。")} />
        <p className="text-[13px] text-muted-foreground">
          <Link href={`/r/${w.forecast_id}`} className="underline underline-offset-2">
            {tx("Set one from the report page", "到报告页设置")}
          </Link>
          {tx(". Armed ones are checked every minute.", "。已布防的每分钟检查一次。")}
        </p>
      </Section>
      <p className="text-[13px] text-muted-foreground">
        {w.webhook_host ? tx(`Also sent to ${w.webhook_host}${w.webhook_status ? ` (${w.webhook_status})` : ""}. `, `同时发送至 ${w.webhook_host}${w.webhook_status ? `（${w.webhook_status}）` : ""}。`) : ""}
        {tx("We don't send email — bookmark this page to check back.", "我们不会发送邮件——请收藏本页，稍后回来查看。")}
      </p>
    </div>
  );
}
