"use client";

import { useEffect, useState } from "react";
import type { ChatStep } from "@/lib/api";
import { useLang } from "@/lib/lang";

/** The stages one analysis runs through, in order, with roughly when each starts on a warm
 *  server (from the report's own timings). Shown while a request is in flight so ten
 *  seconds of grey boxes read as work being done rather than a hang. The highlight follows
 *  the clock, not the server: it says what the desk does, not a live trace of it. */
const STEPS: { at: number; en: string; zh: string }[] = [
  { at: 0, en: "Reading the trade", zh: "读取交易" },
  { at: 1.5, en: "Finding the past moments most like now", zh: "寻找与现在最相似的历史时刻" },
  { at: 4, en: "Stress-testing the position: presets, crash replays, simulation", zh: "压力测试：预设情景、危机重演、模拟" },
  { at: 7, en: "Pricing the exit on Bitget's live order book", zh: "按 Bitget 实时盘口计算平仓成本" },
  { at: 10, en: "Sizing the verdict against your account", zh: "按账户规模给出结论和仓位" },
];
const SLOW_AFTER = 20;

/** What the desk is doing next, per finished stage, shown under the live steps. */
const NEXT: Record<string, { en: string; zh: string }> = {
  snapshot: { en: "Searching history for moments like now", zh: "正在搜索相似的历史时刻" },
  analog: { en: "Reading the live order book", zh: "正在读取实时盘口" },
  book: { en: "Running the stress presets, crash replays and simulation", zh: "正在运行压力情景、危机重演和模拟" },
  stress: { en: "Pricing the exit on the book", zh: "正在计算平仓成本" },
  execution: { en: "Checking the risk rules and sizing the trade", zh: "正在核对风控规则并确定仓位" },
  decision: { en: "Writing the answer", zh: "正在撰写回答" },
};

export function Working({ lang: langProp, compact = false, steps }: { lang?: "en" | "zh"; compact?: boolean; steps?: ChatStep[] }) {
  const ctx = useLang();
  const lang = langProp ?? ctx.lang;
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - start) / 1000), 250);
    return () => clearInterval(id);
  }, []);
  const zh = lang === "zh";
  // Steps the server reported as they finished replace the clock-driven guide.
  const reported = steps && steps.length > 0;
  const next = reported ? NEXT[steps[steps.length - 1].stage] : undefined;
  const current = STEPS.reduce((i, s, j) => (elapsed >= s.at ? j : i), 0);
  const label = reported
    ? next
      ? zh ? next.zh : next.en
      : zh ? steps[steps.length - 1].zh : steps[steps.length - 1].en
    : zh ? STEPS[current].zh : STEPS[current].en;
  const done = reported ? Math.min(steps.length, 6) / 6 : (current + 0.5) / STEPS.length;
  return (
    <div className={compact ? "space-y-1.5" : "space-y-2 border-l-2 border-border pl-4"} role="status" aria-live="polite">
      <p className="flex items-baseline justify-between gap-3 text-sm">
        <span className="min-w-0 truncate font-medium">{label}</span>
        <span className="shrink-0 tabular-nums text-[13px] text-muted-foreground">{Math.floor(elapsed)}s</span>
      </p>
      <div className="h-0.5 overflow-hidden rounded-full bg-border" aria-hidden>
        <div className="h-full rounded-full bg-foreground/50 transition-[width] duration-700 ease-out motion-reduce:transition-none" style={{ width: `${Math.round(done * 100)}%` }} />
      </div>
      {elapsed > SLOW_AFTER ? (
        <p className="text-[13px] text-muted-foreground">
          {zh ? "比平常慢：长时间没人用之后，第一次计算要先加载历史数据。" : "Slower than usual: the first run after a quiet spell loads the history first."}
        </p>
      ) : null}
    </div>
  );
}
