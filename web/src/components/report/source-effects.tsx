"use client";

import type { Report, SourceEffect } from "@/lib/api";
import { type Lang, t as tl, tr } from "@/lib/i18n";

const ORDER: SourceEffect["effect"][] = ["moved_size", "set_preset", "raised_flag", "context"];

/** What each source did: for every source the report used, what it supplied and whether it
 *  changed the answer. Built on the server from the report's own decisions (the cap that
 *  bound, the worst severe preset, the flags raised), not from narrative. */
export function SourceEffects({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const rows = report.source_effects ?? [];
  if (!rows.length) return null;
  const word: Record<SourceEffect["effect"], string> = {
    moved_size: L("Moved the size", "改变了仓位"),
    set_preset: L("Set a stress preset", "设定了压力情景"),
    raised_flag: L("Raised a flag", "触发了提示"),
    context: L("Context only", "仅供参考"),
  };
  const tone: Record<SourceEffect["effect"], string> = {
    moved_size: "bg-status-warning/15 text-status-warning",
    set_preset: "bg-primary/10 text-primary",
    raised_flag: "bg-status-warning/15 text-status-warning",
    context: "bg-muted text-muted-foreground",
  };
  const sorted = [...rows].sort((a, b) => ORDER.indexOf(a.effect) - ORDER.indexOf(b.effect));
  const changed = rows.filter((r) => r.effect !== "context").length;
  return (
    <div className="mb-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
      <p className="font-medium text-foreground">{L("What each source did", "各数据源起了什么作用")}</p>
      <p className="text-[13px] text-muted-foreground">
        {L(`${changed} of ${rows.length} sources changed something in this answer; the rest are shown beside it.`, `${rows.length} 个数据源中有 ${changed} 个改变了这次的结论，其余仅作参考。`)}
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-[13px]">
          <thead>
            <tr className="text-muted-foreground">
              <th className="py-1 pr-3 font-medium">{L("Source", "数据源")}</th>
              <th className="py-1 pr-3 font-medium">{L("Supplied", "提供了什么")}</th>
              <th className="py-1 font-medium">{L("Effect", "作用")}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.kind} className="border-t border-border align-top">
                <td className="py-1.5 pr-3 font-medium text-foreground">{tl(lang, "feed", r.kind)}</td>
                <td className="py-1.5 pr-3 text-muted-foreground">{lang === "zh" ? r.supplied_zh : r.supplied}</td>
                <td className="py-1.5">
                  <span className={`inline-block rounded px-1.5 py-0.5 text-[12px] font-medium ${tone[r.effect]}`}>{word[r.effect]}</span>
                  {(lang === "zh" ? r.note_zh : r.note) ? <span className="mt-0.5 block text-muted-foreground">{lang === "zh" ? r.note_zh : r.note}</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
