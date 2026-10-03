"use client";

import { Layers } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, ApiError, type Report, type TicketInput } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import { type Lang, t as tl, tr } from "@/lib/i18n";

/** A deliberately concentrated example book: the same direction as the trade, in two
 *  names that move together. It is an illustration, not the visitor's book. */
export function exampleBook(side: TicketInput["side"]): NonNullable<TicketInput["open_positions"]> {
  return [
    { ticker: "TSLA", side, notional_quote: 60000 },
    { ticker: "NVDA", side, notional_quote: 40000 },
  ];
}

/** The ticket as asked, without a book it did not ask for. Not journaled: nobody took it. */
function forContrast(t: TicketInput, patch: Partial<TicketInput>): TicketInput {
  return { ...t, record: false, ...patch };
}

export interface Contrast {
  alone: Report;
  withBook: Report;
}

/** Why the size moved, in the desk's own fields: the book's tail limit when it binds, else
 *  whichever cap changed, else the honest "it did not". Never a number the engine did not compute. */
export function whyChanged(c: Contrast, lang: Lang): string {
  const L = tr(lang);
  const a = c.alone;
  const b = c.withBook;
  const pa = a.verdict.recommended_notional;
  const pb = b.verdict.recommended_notional;
  const p = b.portfolio;
  if (p?.book_cap_binds && p.book_cap_quote != null) {
    return L(
      `With that book already on, the whole book's one-in-twenty loss limits this trade: the most it can add is ${fmtUsd(p.book_cap_quote)}${p.book_cap_pct_of_equity != null ? ` (${p.book_cap_pct_of_equity.toFixed(1)}% of equity)` : ""}. Alone it faces no such limit.`,
      `已有这个组合时，整个组合的二十分之一亏损限制了这笔交易：最多可再加 ${fmtUsd(p.book_cap_quote)}${p.book_cap_pct_of_equity != null ? `（占权益 ${p.book_cap_pct_of_equity.toFixed(1)}%）` : ""}。单独做则没有这个限制。`,
    );
  }
  const ca = a.sizing.binding_cap;
  const cb = b.sizing.binding_cap;
  if (cb && cb !== ca) {
    return L(
      `The limit that binds changed from ${ca ? tl("en", "cap", ca) : "none"} to ${tl("en", "cap", cb)} once the book is counted.`,
      `计入组合后，起限制作用的上限由${ca ? tl("zh", "cap", ca) : "无"}变为${tl("zh", "cap", cb)}。`,
    );
  }
  if (pa != null && pb != null && Math.abs(pa - pb) > 1) {
    const extra = b.verdict.reasons.find((r) => !a.verdict.reasons.includes(r));
    return extra ?? L("The book changes the size through the same limit that applied alone.", "组合通过同一项限制改变了仓位。");
  }
  return L("This book does not change the size: the limit that binds is the same with or without it.", "这个组合没有改变仓位：有无它，起限制作用的上限相同。");
}

function Side({ title, r, lang }: { title: string; r: Report; lang: Lang }) {
  const L = tr(lang);
  const v = r.verdict;
  const tail = r.portfolio?.after.tail_loss_quote ?? null;
  return (
    <div className="space-y-1 rounded-lg border border-border p-3">
      <h4 className="text-[13px] font-medium text-muted-foreground">{title}</h4>
      <p className="text-lg font-semibold" data-testid="contrast-verdict">
        {tl(lang, "verdictName", v.verdict)}
      </p>
      <p className="tabular text-sm">
        {L("Size", "仓位")}: {fmtUsd(v.recommended_notional)} <span className="text-muted-foreground">{L("of", "/ 请求")} {fmtUsd(v.requested_notional)}</span>
      </p>
      {tail != null ? (
        <p className="tabular text-[13px] text-muted-foreground">{L(`Whole-book 1-in-20 loss: ${fmtUsd(tail)}`, `整个组合二十分之一亏损：${fmtUsd(tail)}`)}</p>
      ) : null}
    </div>
  );
}

/** The same ticket twice, alone and on top of the example book, side by side. */
export function ContrastView({ c, lang }: { c: Contrast; lang: Lang }) {
  const L = tr(lang);
  const side = c.alone.ticket.side;
  return (
    <div className="space-y-2">
      <div className="grid gap-3 sm:grid-cols-2">
        <Side title={L("Alone", "单独做")} r={c.alone} lang={lang} />
        <Side title={L("With an example book (60k TSLA + 40k NVDA, both " + side + ")", "加上示例组合（TSLA 6 万 + NVDA 4 万，均为" + (side === "long" ? "多" : "空") + "）")} r={c.withBook} lang={lang} />
      </div>
      <p className="text-sm" data-testid="contrast-why">
        {whyChanged(c, lang)}
      </p>
      <p className="text-[13px] text-muted-foreground">
        {L("The book is an example, not yours. Add your real positions in the Ticket tab or tell the chat, e.g. “I also hold 60k TSLA and 40k NVDA”.", "这个组合只是示例，不是你的持仓。请在“表单”标签添加真实持仓，或告诉聊天，例如“我另外持有 6 万 TSLA 和 4 万 NVDA”。")}
      </p>
    </div>
  );
}

export async function runContrast(ticket: TicketInput): Promise<Contrast> {
  // Alone first, then the book at the same moment, so the only difference is the book.
  const alone = await api.analyze(forContrast(ticket, { open_positions: [] }));
  const withBook = await api.analyze(forContrast(ticket, { open_positions: exampleBook(ticket.side), as_of: alone.as_of }));
  return { alone, withBook };
}

/** One click: run this trade alone and on a concentrated book, and say why the size moved. */
export function BookContrast({ ticket, lang = "en", auto = false }: { ticket: TicketInput; lang?: Lang; auto?: boolean }) {
  const L = tr(lang);
  const [state, setState] = useState<"idle" | "busy" | "done">(auto ? "busy" : "idle");
  const [c, setC] = useState<Contrast | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    setState("busy");
    setError(null);
    try {
      setC(await runContrast(ticket));
      setState("done");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : L("Could not run the comparison.", "无法运行对比。"));
      setState("idle");
    }
  }
  useEffect(() => {
    if (auto) void go();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-2 text-sm">
      {!auto ? (
        <Button variant="outline" size="sm" disabled={state === "busy"} onClick={() => void go()}>
          <Layers aria-hidden /> {state === "busy" ? L("Running both…", "正在运行两种情形…") : L("Same trade, different book", "同一笔交易，不同的组合")}
        </Button>
      ) : state === "busy" ? (
        <p className="text-muted-foreground">{L("Running the trade alone and on the example book…", "正在分别运行单独做和加上示例组合的情形…")}</p>
      ) : null}
      {error ? <p className="text-xs text-status-critical">{error}</p> : null}
      {c ? <ContrastView c={c} lang={lang} /> : null}
    </div>
  );
}
