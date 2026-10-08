import { fmtPct, fmtUsd } from "@/lib/format";
import { type Lang, t as tl, tr } from "@/lib/i18n";
import type { Report } from "@/lib/api";

/** The bad move and the thin book at once, for the part of the week the hold runs through.
 *  The numbers are the report's own one-in-twenty line and the recorder's thinnest-twentieth
 *  of snapshots; the sentence is written by the server so the page cannot reword a figure. */
export function JointBreak({ report, lang }: { report: Report; lang: Lang }) {
  const L = tr(lang);
  const j = report.joint_break;
  if (!j) return null;
  if (!j.available) {
    return (
      <p className="mt-4 text-[13px] text-muted-foreground">
        {L(
          "The bad move and a thin book at once: the recorder has not stored enough of this book across the hours the hold runs through to say yet.",
          "坏行情与薄盘口同时出现的情形：记录器还没有存下足够多的、覆盖本次持有时段的盘口数据，暂时说不了。",
        )}
      </p>
    );
  }
  return (
    <div className="mt-4 rounded-md border border-border p-3">
      <p className="text-xs font-medium text-muted-foreground">
        {L("If the bad move and a thin book arrive together", "如果坏行情和薄盘口同时到来")} ·{" "}
        {tl(lang, "bucket", j.bucket)} · {j.n_snapshots.toLocaleString()} {L("recorded snapshots", "份记录的快照")}
      </p>
      <p className="mt-2 max-w-prose text-sm">{lang === "zh" ? j.plain_zh : j.plain}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[13px] sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">{L("Move alone", "仅价格波动")}</dt>
          <dd className="tabular font-medium">{fmtPct(j.move_pct, 1)} · {fmtUsd(Math.abs(j.move_quote))}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{L("With the spread", "加上价差")}</dt>
          <dd className="tabular font-medium">≤ {fmtPct(j.total_floor_pct, 1)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{L("Sellable inside 25 bps", "25 bps 内可卖")}</dt>
          <dd className="tabular font-medium">{fmtUsd(j.depth_p5)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{L("Beyond that, unmeasured", "超出部分（未测量）")}</dt>
          <dd className={`tabular font-medium ${j.unclearable_quote > 0 ? "text-status-warning" : ""}`}>{fmtUsd(j.unclearable_quote)}</dd>
        </div>
      </dl>
    </div>
  );
}
