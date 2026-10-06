"use client";

import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";
import { ReportView } from "@/components/report/report-view";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api, peek, type Report } from "@/lib/api";
import { recall } from "@/lib/record-cache";
import { snapshotFlag } from "@/lib/snapshot";
import { fmtDateTimeL } from "@/lib/i18n";
import { useLang } from "@/lib/lang";

/** A link that puts this trade through the desk again, today: the home page runs ``?q=`` through
 *  the chat once. The words are the ticket's own, in the shapes the desk reads, so it is the same
 *  trade (side, size, hold, leverage, stop, account, reason) and not just the start screen. */
export function rerunHref(report: Report): string {
  const t = report.ticket;
  if (!t || !t.ticker || !(t.notional_quote > 0)) return "/";
  const label = String((t.extra as { horizon_label?: unknown } | undefined)?.horizon_label ?? "");
  const parts = [`${t.side} ${Math.round(t.notional_quote)} ${t.ticker}`];
  if (/weekend/i.test(label)) parts.push("over the weekend");
  else if (t.horizon_kind === "next_open") parts.push("overnight");
  else if (t.horizon_kind === "window_end") parts.push("until the close");
  else if (t.horizon_hours) parts.push(`for ${t.horizon_hours} hours`);
  if (t.leverage && t.leverage > 1) parts.push(`${t.leverage}x`);
  if (t.stop_price) parts.push(`stop ${t.stop_price}`);
  if (t.account_equity_quote) parts.push(`account ${Math.round(t.account_equity_quote)}`);
  if (t.thesis) parts.push(`because ${t.thesis}`);
  if (t.invalidation) parts.push(`wrong if ${t.invalidation}`);
  return `/?q=${encodeURIComponent(parts.join(", ").slice(0, 480))}`;
}

/** One stored report, reopened exactly as it was argued.
 *
 *  Nothing is recomputed here. The page shows the report the desk produced at that
 *  moment, with the hash of the inputs it used, which is the point: a link somebody else
 *  opens has to show them what you saw, not what the market is doing now.
 */
export function StoredReport({ id }: { id: string }) {
  const { lang, tx } = useLang();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [slow, setSlow] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // Set when the report on screen is a copy (this browser's, or the proxy's saved one), not a live read.
  const [copyFrom, setCopyFrom] = useState<string | null>(null);
  const proxyCopy = useSyncExternalStore(snapshotFlag.subscribe, snapshotFlag.get, () => null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setSlow(false);
    // A stored report never changes, so a copy this browser already holds shows at once.
    const path = `/reports/${id}`;
    const cached = peek<Report>(path);
    if (cached) {
      setReport(cached);
      const at = recall<Report>(path)?.at;
      setCopyFrom(at ? new Date(at).toISOString() : "");
    }
    const timer = setTimeout(() => setSlow(true), 15_000);
    void api
      .report(id)
      .then((r) => {
        if (cancelled) return;
        setReport(r);
        setCopyFrom(null);
      })
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : tx("Could not load that report.", "无法加载这份报告。")))
      .finally(() => clearTimeout(timer));
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, attempt]);

  const retry = () => setAttempt((n) => n + 1);

  if (error && !report) {
    return (
      <div className="mx-auto max-w-xl space-y-3 py-10 text-center">
        <h1 className="text-lg font-semibold">{tx("That report did not load", "这份报告没有加载出来")}</h1>
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button variant="secondary" className="min-h-10" onClick={retry}>
          {tx("Try again", "重试")}
        </Button>
        <p className="text-sm">
          <Link href="/" className="underline underline-offset-2">
            {tx("Run a new one on the desk", "在交易台运行一份新的")}
          </Link>
          {" · "}
          <Link href="/journal" className="underline underline-offset-2">
            {tx("see every call in the journal", "在日志里查看所有结论")}
          </Link>
        </p>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="space-y-4" role="status" aria-live="polite">
        <p className="text-sm text-muted-foreground">
          {slow ? tx("Still loading. The server is slow or not answering right now.", "仍在加载。服务器响应很慢，或暂时没有响应。") : tx("Loading the saved report…", "正在加载已保存的报告…")}
          {slow ? (
            <>
              {" "}
              <button type="button" onClick={retry} className="inline-flex min-h-10 items-center px-2 underline underline-offset-2 hover:text-foreground">
                {tx("Try again", "重试")}
              </button>
            </>
          ) : null}
        </p>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {copyFrom !== null || proxyCopy ? (
        <p role="status" className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm">
          {proxyCopy
            ? tx(`The live server is not answering, so this is the saved copy from ${fmtDateTimeL(proxyCopy, lang)}.`, `实时服务器没有响应，所以这里显示的是 ${fmtDateTimeL(proxyCopy, lang)} 保存的副本。`)
            : tx(`Showing the copy this browser saved${copyFrom ? ` on ${fmtDateTimeL(copyFrom, lang)}` : ""} while the server answers. A stored report does not change.`, `正在显示本浏览器${copyFrom ? `于 ${fmtDateTimeL(copyFrom, lang)} ` : ""}保存的副本，同时等待服务器响应。已保存的报告不会改变。`)}
          {error ? (
            <>
              {" "}
              <button type="button" onClick={retry} className="inline-flex min-h-10 items-center px-2 underline underline-offset-2">
                {tx("Try again", "重试")}
              </button>
            </>
          ) : null}
        </p>
      ) : null}
      <h1 className="sr-only">{`${report.ticket.ticker} ${tx("stored report", "已保存的报告")}`}</h1>
      <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm">
        <p className="font-medium">{tx("A saved report, not a live one", "这是保存的报告，不是实时的")}</p>
        <p className="text-[13px] text-muted-foreground">
          {tx(
            `This is ${id.startsWith("-") ? "a what-if run" : `forecast #${id}`} exactly as the desk argued it on ${fmtDateTimeL(report.as_of, lang)}. Nothing on this page has been recomputed since.`,
            `这是${id.startsWith("-") ? "一次假设情景" : `预测 #${id}`}，与交易台在 ${fmtDateTimeL(report.as_of, lang)} 给出的内容完全一致，此后页面上的任何内容都没有重新计算。`,
          )}{" "}
          <Link href={rerunHref(report)} className="underline underline-offset-2">
            {tx("Run the same trade now", "现在重新运行同一笔交易")}
          </Link>
          {tx(".", "。")}
        </p>
      </div>
      <ReportView report={report} lang={lang} />
    </div>
  );
}
