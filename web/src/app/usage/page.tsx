"use client";

import { useEffect, useState } from "react";
import { Section, Stat } from "@/components/report/primitives";
import { LoadingRecord, PageHead, PROOF_WIDTH, RecordError } from "@/components/proof-page";
import { engagement, type Usage } from "@/lib/engagement";
import { fmtTimeL } from "@/lib/i18n";
import { useLang } from "@/lib/lang";
import { peek } from "@/lib/api";

/** The kinds of answer the chat gives, in words. An unknown key still reads as words. */
const KIND: Record<string, [string, string]> = {
  what_if: ["What-if", "假设情景"], thesis_saved: ["Plan saved", "已保存计划"], thesis: ["Plan", "计划"], plain: ["Plain explanation", "通俗解释"], menu: ["Menu of questions", "问题菜单"],
  corporate: ["Company events", "公司事件"], worst: ["Worst case", "最坏情况"], technicals: ["Chart levels", "技术位"], street: ["Analyst views", "分析师观点"], size: ["Size", "仓位大小"],
  history: ["History", "历史"], hedge: ["Hedge", "对冲"], gate: ["Risk gate", "风控关卡"], stop: ["Stop", "止损"], shock: ["Shock", "冲击情景"], regime: ["Market mood", "市场状态"],
  lessons: ["Lessons", "经验教训"], exit: ["Getting out", "退出"], decide: ["Decide", "决策"], data: ["Data", "数据"], why: ["Why", "原因"], trust: ["Trust", "可信度"],
  model: ["Free-form answer (model)", "自由回答（模型）"], rules: ["Rule-based answer", "规则回答"], ways: ["Ways to change the trade", "调整交易的办法"], unknown_ticker: ["Unknown token", "未知代币"],
  override: ["Override", "手动覆盖"], base_rate: ["Base rate", "基础概率"], compare: ["Comparison", "对比"], followup: ["Follow-up", "追问"], clarify: ["Clarifying question", "澄清问题"], options: ["Options market", "期权市场"],
  premise: ["Premise check", "前提检查"], now: ["Right now", "此刻"], moments: ["Past moments", "历史时刻"], against: ["Against the trade", "反方观点"], ack: ["Acknowledged", "已确认"], book: ["Whole book", "整体持仓"],
};
function kindLabel(k: string, lang: "en" | "zh"): string {
  const hit = KIND[k];
  if (hit) return lang === "zh" ? hit[1] : hit[0];
  return k.replace(/_/g, " ");
}

/** What the desk knows about its own use. Counts only: no accounts, no addresses. */
export default function UsagePage() {
  const { tx, lang } = useLang();
  const [u, setU] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    const c = peek<Usage>("/usage");
    if (c) setU(c);
    void engagement
      .usage()
      .then((r) => !cancelled && setU(r))
      .catch(() => !cancelled && setError(tx("Could not load the numbers.", "无法加载数据。")));
    return () => {
      cancelled = true;
    };
  }, [tx, attempt]);

  if (error && !u)
    return (
      <div className={PROOF_WIDTH}>
        <RecordError message={error} onRetry={() => setAttempt((n) => n + 1)} />
      </div>
    );
  if (!u)
    return (
      <div className={PROOF_WIDTH}>
        <LoadingRecord blocks={[256]} onRetry={() => setAttempt((n) => n + 1)} />
      </div>
    );

  const since = u.counted_since ? fmtTimeL(u.counted_since, lang) : tx("no verdicts yet", "暂无结论");
  const asked = u.feedback.useful + u.feedback.not_useful;
  const kinds = Object.entries(u.follow_ups_by_answer_kind);
  return (
    <div className={`${PROOF_WIDTH} space-y-4`}>
      <PageHead
        title={tx("Who uses the desk", "谁在使用交易台")}
        intro={tx(`Counted since ${since}; no accounts; only an anonymous random id in your browser.`, `统计自 ${since}；无账户；只使用您浏览器里的匿名随机编号。`)}
      />
      <Section title={tx("Numbers", "数字")}>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat
            label={tx("Verdicts given to visitors", "给访客的结论")}
            value={u.live_verdicts.toLocaleString()}
            hint={tx(
              `answers visitors asked for, our own checks left out. The journal holds ${u.journal_live_verdicts_all_time.toLocaleString()} live analyses in all (open ones and our own checks included); the scored count is on /wrong.`,
              `访客请求的回答，不含我们自己的检查。日志里共有 ${u.journal_live_verdicts_all_time.toLocaleString()} 条实时分析（含尚未到期的和我们自己的检查）；已评分的数量见 /wrong。`,
            )}
          />
          <Stat
            label={tx("Anonymous visitors", "匿名访客")}
            value={String(u.distinct_anonymous_clients)}
            hint={u.clients_stable_across_restarts ? undefined : tx("may be over-counted after a server restart", "服务器重启后可能重复计数")}
          />
          <Stat label={tx("Useful", "有用")} value={String(u.feedback.useful)} hint={asked ? tx(`of ${asked} answers`, `共 ${asked} 个回答`) : tx("no answers yet", "暂无回答")} />
          <Stat label={tx("Not useful", "没用")} value={String(u.feedback.not_useful)} />
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          {tx("By language: ", "按语言：")}
          {Object.entries(u.by_language)
            .map(([k, v]) => `${k === "zh" ? "中文" : "English"} ${v}`)
            .join(" · ") || "-"}
        </p>
      </Section>
      <Section title={tx("Follow-up questions by kind of answer", "追问（按回答类型）")}>
        {kinds.length ? (
          <ul className="space-y-1 text-sm">
            {kinds.map(([k, n]) => (
              <li key={k} className="flex justify-between gap-4">
                <span>{kindLabel(k, lang)}</span>
                <span className="font-mono">{n}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{tx("None yet.", "暂无。")}</p>
        )}
      </Section>
      <Section title={tx("Latest notes", "最新留言")} subtitle={tx("Links and email addresses are removed.", "链接和邮箱已删除。")}>
        {u.last_notes.length ? (
          <ul className="space-y-2 text-sm">
            {u.last_notes.map((n) => (
              <li key={n.at + n.note}>
                <span className="text-muted-foreground">
                  {n.useful ? tx("useful", "有用") : tx("not useful", "没用")} · {fmtTimeL(n.at, lang)}
                </span>
                <br />
                {n.note}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{tx("None yet.", "暂无。")}</p>
        )}
      </Section>
      <p className="text-[13px] text-muted-foreground">
        {tx(
          "Requests from the operator's own browser are excluded (header x-nw-internal: 1, or localStorage nightwatch.internal = 1).",
          "运营者自己浏览器的请求不计入（请求头 x-nw-internal: 1，或 localStorage nightwatch.internal = 1）。",
        )}
      </p>
    </div>
  );
}
