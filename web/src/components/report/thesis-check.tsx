"use client";

import { useEffect, useState } from "react";
import { api, type ThesisCheck, type ThesisClaim } from "@/lib/api";
import { type Lang, fmtTimeL, tr } from "@/lib/i18n";

const STATUS: Record<ThesisClaim["status"], { en: string; zh: string; tone: string }> = {
  supported: { en: "In the news", zh: "新闻中有", tone: "text-status-good" },
  contradicted: { en: "The news says otherwise", zh: "新闻说法相反", tone: "text-status-critical" },
  not_found: { en: "Not in our feeds", zh: "我们的数据源中没有", tone: "text-muted-foreground" },
  related: { en: "Related headlines", zh: "相关标题", tone: "text-muted-foreground" },
};

function ClaimRow({ c, lang }: { c: ThesisClaim; lang: Lang }) {
  const s = STATUS[c.status];
  return (
    <li className="space-y-1">
      <p>
        <span className={`font-medium ${s.tone}`}>{lang === "zh" ? s.zh : s.en}</span>
        <span className="text-muted-foreground"> · </span>
        <span>“{c.claim}”</span>
      </p>
      {c.evidence.length ? (
        <ul className="space-y-0.5 border-l border-border pl-3 text-[13px] text-muted-foreground">
          {c.evidence.map((e) => (
            <li key={e.id}>
              {e.link ? (
                <a href={e.link} target="_blank" rel="noreferrer" className="text-foreground underline-offset-2 hover:underline">
                  {e.title}
                </a>
              ) : (
                <span className="text-foreground">{e.title}</span>
              )}{" "}
              · {e.source} · {fmtTimeL(e.published_at, lang)}
            </li>
          ))}
        </ul>
      ) : null}
      {c.note ? <p className="text-[13px] text-muted-foreground">{c.note}</p> : null}
    </li>
  );
}

/** The trader's written reason, claim by claim, against the headlines and SEC filings the
 *  desk had stored before the report. The model only matched them; every quote here is a
 *  stored headline with its source and time. */
export function ThesisCheckCard({ forecastId, thesis, lang = "en" }: { forecastId: number; thesis: string; lang?: Lang }) {
  const L = tr(lang);
  const [got, setGot] = useState<ThesisCheck | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!thesis.trim()) return;
    let off = false;
    setGot(null);
    setFailed(false);
    api
      .thesisCheck(forecastId, lang)
      .then((r) => !off && setGot(r))
      .catch(() => !off && setFailed(true));
    return () => {
      off = true;
    };
  }, [forecastId, thesis, lang]);

  if (!thesis.trim() || failed) return null;
  const box = "mt-3 border-l-2 border-border pl-3 text-sm";
  if (!got) {
    return (
      <div className={box} role="status">
        <span className="font-medium text-foreground">{L("Your reason vs the news: ", "你的理由与新闻对照：")}</span>
        <span className="text-muted-foreground">{L("checking it against the last 14 days of headlines and filings…", "正在对照过去 14 天的新闻和公告…")}</span>
      </div>
    );
  }
  if (got.state === "no_items") {
    return (
      <div className={box}>
        <span className="font-medium text-foreground">{L("Your reason vs the news: ", "你的理由与新闻对照：")}</span>
        <span className="text-muted-foreground">
          {L(`no ${got.ticker} headlines or filings in our feeds in the ${got.window_days} days before this report, so there was nothing to check it against.`,
            `本报告之前 ${got.window_days} 天内，我们的数据源中没有 ${got.ticker} 的新闻或公告，无从对照。`)}
        </span>
      </div>
    );
  }
  if (got.state !== "checked") return null;
  const how = got.method === "model"
    ? L(`AI-matched against ${got.items_considered} stored headlines and filings; every quote is the stored headline.`, `由 AI 对照 ${got.items_considered} 条已存储的新闻和公告；所有引用均为原始标题。`)
    : L(`Matched by shared words against ${got.items_considered} stored headlines; no model read them.`, `按共同词语对照 ${got.items_considered} 条已存储的标题；未经模型阅读。`);
  return (
    <section className={box} aria-label={L("Your reason vs the news", "你的理由与新闻对照")}>
      <p className="font-medium text-foreground">{L("Your reason vs the news", "你的理由与新闻对照")}</p>
      {got.claims.length ? (
        <ul className="mt-2 space-y-2">
          {got.claims.map((c, i) => (
            <ClaimRow key={i} c={c} lang={lang} />
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-muted-foreground">{L("Your reason makes no claim about news a headline could confirm (it reads as a view, not a report).", "你的理由没有可由新闻证实的事实陈述（更像观点而非报道）。")}</p>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        {how} {L("“Not in our feeds” means we did not see it, not that it is false.", "“数据源中没有”表示我们没看到，不代表它是假的。")}
      </p>
    </section>
  );
}
