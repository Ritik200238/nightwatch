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
  if (steps && steps.length > 0) {
    const next = NEXT[steps[steps.length - 1].stage];
    return (
      <div className={compact ? "space-y-1.5" : "space-y-2 rounded-lg border border-border p-4"} role="status" aria-live="polite">
        <p className="flex items-center justify-between text-sm font-medium">
          <span>{zh ? "正在计算" : "Running the desk"}</span>
          <span className="tabular-nums text-[13px] text-muted-foreground">{Math.floor(elapsed)}s</span>
        </p>
        <ol className="space-y-1 text-sm">
          {steps.map((s) => (
            <li key={s.stage} className="text-muted-foreground">
              <span aria-hidden className="mr-1.5 inline-block w-3">✓</span>
              {zh ? s.zh : s.en}
            </li>
          ))}
          {next ? (
            <li className="font-medium text-foreground">
              <span aria-hidden className="mr-1.5 inline-block w-3">›</span>
              {zh ? next.zh : next.en}
            </li>
          ) : null}
        </ol>
      </div>
    );
  }
  const current = STEPS.reduce((i, s, j) => (elapsed >= s.at ? j : i), 0);
  return (
    <div className={compact ? "space-y-1.5" : "space-y-2 rounded-lg border border-border p-4"} role="status" aria-live="polite">
      <p className="flex items-center justify-between text-sm font-medium">
        <span>{zh ? "正在计算" : "Running the desk"}</span>
        <span className="tabular-nums text-[13px] text-muted-foreground">{Math.floor(elapsed)}s</span>
      </p>
      <ol className="space-y-1 text-sm">
        {STEPS.map((s, j) => (
          <li key={s.en} className={j < current ? "text-muted-foreground line-through decoration-muted-foreground/40" : j === current ? "font-medium text-foreground" : "text-muted-foreground/60"}>
            <span aria-hidden className="mr-1.5 inline-block w-3">{j < current ? "✓" : j === current ? "›" : ""}</span>
            {zh ? s.zh : s.en}
          </li>
        ))}
      </ol>
      {elapsed > SLOW_AFTER ? (
        <p className="text-[13px] text-muted-foreground">
          {zh ? "比平常慢：长时间没人用之后，第一次计算要先加载历史数据。" : "Slower than usual: the first run after a quiet spell loads the history first."}
        </p>
      ) : null}
    </div>
  );
}
