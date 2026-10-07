"use client";

import { CheckCircle2, Loader2, MinusCircle, Sparkles } from "lucide-react";
import { GuardNote } from "@/components/report/guard-note";
import { Button } from "@/components/ui/button";
import { resetAgent, startAgent, toolVerb, useAgent } from "@/lib/agent-run";
import { tr, type Lang } from "@/lib/i18n";

/** The AI stress-test agent: Qwen plans up to five checks against the engine and the
 *  steps appear here as they finish. It cannot change the verdict. */
export function AgentPanel({ forecastId, lang }: { forecastId: number; lang: Lang }) {
  const L = tr(lang);
  const st = useAgent(forecastId, lang);
  const run = st.run;
  const steps = run?.steps ?? [];
  const running = st.started && (run?.status === "running" || run == null);
  const failed = run?.status === "failed";
  const final = run?.status === "done" ? run.final : null;

  return (
    <div className="border-t border-border pt-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold">{L("AI stress-test agent", "AI 压力测试代理")}</p>
          <p className="text-[13px] text-muted-foreground">{L("Qwen picks up to five checks and runs each on our engine.", "Qwen 最多挑选五项检查，并在我们的引擎上逐项运行。")}</p>
        </div>
        {!st.started || failed ? (
          <Button
            type="button"
            size="lg"
            onClick={() => {
              resetAgent(forecastId, lang);
              startAgent(forecastId, lang);
            }}
          >
            <Sparkles className="h-4 w-4" aria-hidden />
            {failed ? L("Try again", "重试") : L("Let the AI stress-test it deeper", "让 AI 深入压力测试")}
          </Button>
        ) : (
          <p className="text-[13px] text-muted-foreground tabular-nums">{Math.round(st.elapsed)} s</p>
        )}
      </div>
      {st.started ? (
        <ol className="mt-3 space-y-3 border-l border-border pl-4" aria-live="polite">
          {steps.map((s) => (
            <li key={s.n} className="relative text-sm">
              {s.status === "skipped" || s.status === "refused" ? (
                <MinusCircle className="absolute -left-[25px] top-0.5 h-4 w-4 rounded-full bg-card text-status-warning" aria-hidden />
              ) : (
                <CheckCircle2 className="absolute -left-[25px] top-0.5 h-4 w-4 rounded-full bg-card text-status-good" aria-hidden />
              )}
              <p className="font-medium">
                {s.n}. {toolVerb(s.tool, s.args, lang === "zh")}
                {typeof s.seconds === "number" ? <span className="ml-2 text-xs font-normal text-muted-foreground tabular-nums">{s.seconds.toFixed(1)} s</span> : null}
              </p>
              {s.thought ? <p className="text-[13px] text-muted-foreground">{s.thought}</p> : null}
              {s.result_summary ? <p className={s.status === "skipped" || s.status === "refused" ? "mt-0.5 text-[13px] text-status-warning" : "mt-0.5"}>{s.result_summary}</p> : null}
            </li>
          ))}
          {running ? (
            <li className="relative text-sm text-muted-foreground" role="status">
              <Loader2 className="absolute -left-[25px] top-0.5 h-4 w-4 animate-spin rounded-full bg-card" aria-hidden />
              {steps.length ? L(`Step ${steps.length + 1} in progress…`, `第 ${steps.length + 1} 步进行中…`) : L("The agent is planning its first check…", "代理正在规划第一项检查…")}
            </li>
          ) : null}
        </ol>
      ) : null}
      {failed ? (
        <p className="mt-3 text-sm text-status-warning">
          {L("The agent stopped before it finished. The verdict above is unchanged.", "代理未能完成。上面的结论不受影响。")}
          {steps.length ? L(" Steps so far are shown.", " 已完成的步骤如上。") : ""}
        </p>
      ) : null}
      {final ? (
        <div className="mt-4 space-y-2 border-t border-border pt-3 text-sm">
          {final.summary ? <p className="font-semibold">{final.summary}</p> : null}
          {final.findings && final.findings.length ? (
            <ul className="list-disc space-y-1 pl-5">
              {final.findings.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          ) : null}
          {final.verdict_restated ? (
            <p className="text-muted-foreground">
              <span className="font-medium text-foreground">{L("Verdict, restated: ", "结论重述：")}</span>
              {final.verdict_restated}
            </p>
          ) : null}
          {run?.removed ? <GuardNote n={run.removed} lang={lang} className="text-[13px] text-muted-foreground" /> : null}
          <p className="text-[13px] text-muted-foreground">
            {final.coverage ? `${final.coverage} ` : ""}
            {L(`Took ${Math.round(st.elapsed)} s.`, `用时 ${Math.round(st.elapsed)} 秒。`)}
          </p>
        </div>
      ) : null}
    </div>
  );
}
