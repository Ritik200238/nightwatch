"use client";

import { useEffect, useState } from "react";
import { Section, Stat } from "@/components/report/primitives";
import { LoadingRecord, PageHead, PROOF_WIDTH } from "@/components/proof-page";
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

  useEffect(() => {
    let cancelled = false;
    const c = peek<Usage>("/usage");
    if (c) setU(c);
    void engagement
      .usage()
      .then((r) => !cancelled && setU(r))
      .catch(() => !cancelled && setError(tx("Could not load the numbers.", "无法加载数据。")));
    return () => {
      cancelled = true;
    };
  }, [tx]);

  if (error) return <p className={`${PROOF_WIDTH} py-10 text-center text-sm text-muted-foreground`}>{error}</p>;
  if (!u)
    return (
      <div className={PROOF_WIDTH}>
        <LoadingRecord blocks={[256]} />
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
          <Stat label={tx("Live verdicts", "实时结论")} value={String(u.live_verdicts)} hint={tx(`${u.journal_live_verdicts_all_time} in the journal all time`, `日志中累计 ${u.journal_live_verdicts_all_time} 条`)} />
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
