"use client";

import { verdictBadge } from "@/lib/verdict-style";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { chipText, detailText, KIND_MEANING, KIND_NAME, type ProvEntry, type ProvKind } from "@/lib/provenance";
import type { Lang } from "@/lib/i18n";

/** A section of the report. Open: a hairline above and whitespace do the grouping, no box.
 *  The implementation is shared with the proof pages (OpenSection), so one change restyles both.
 *
 *  With `collapsible`, the heading row is a full-width button and the body starts closed. A
 *  report has twelve of these; each collapsed header carries `summary` (the one number that
 *  section is about) so the page still scans as an index. `openAll` lets a parent force every
 *  section open at once. */
export { OpenSection as Section } from "@/components/proof-page";

/** One number, with its label above and a quiet hint below. No box: a hairline above and
 *  whitespace do the grouping. Value in proportional figures. */
export function Stat({ label, value, hint, tone, chip }: { label: string; value: string; hint?: string; tone?: "good" | "warning" | "critical" | "muted"; chip?: ReactNode }) {
  const color = tone === "good" ? "text-status-good" : tone === "warning" ? "text-status-warning" : tone === "critical" ? "text-status-critical" : "";
  return (
    <div className="flex min-w-0 flex-col gap-0.5 border-t border-border pt-2.5 pb-1">
      <span className="t-caption">{label}</span>
      <span className={`tabular text-lg leading-tight font-semibold tracking-tight [overflow-wrap:anywhere] [word-break:keep-all] ${color}`}>{value}</span>
      {hint ? <span className="t-caption">{hint}</span> : null}
      {chip ? <span className="mt-1 flex">{chip}</span> : null}
    </div>
  );
}

/** A status word: colour on the text, no outline. A verdict keeps its badge (the one place a
 *  small outlined shape still carries meaning) and the shared verdict colour map. */
export function Pill({ children, tone = "muted", verdict }: { children: ReactNode; tone?: "good" | "warning" | "critical" | "muted" | "info"; verdict?: string }) {
  if (verdict) return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${verdictBadge(verdict)}`}>{children}</span>;
  const cls = tone === "good" ? "text-status-good" : tone === "warning" ? "text-status-warning" : tone === "critical" ? "text-status-critical" : tone === "info" ? "text-primary" : "text-muted-foreground";
  return <span className={`inline-flex items-center text-[13px] font-medium whitespace-nowrap ${cls}`}>{children}</span>;
}

const KIND_STYLE: Record<ProvKind, { dot: string; text: string }> = {
  live: { dot: "bg-status-good", text: "text-status-good" },
  history: { dot: "bg-primary", text: "text-primary" },
  assumed: { dot: "border border-status-warning bg-transparent", text: "text-status-warning" },
  ai: { dot: "bg-muted-foreground [clip-path:polygon(50%_0,100%_50%,50%_100%,0_50%)]", text: "text-muted-foreground" },
};

/** Where a number came from: a small chip (dot + kind + age or sample size) that opens
 *  the exact source on hover, focus or tap.
 *
 *  The kind is carried by the word and by the dot's shape (filled, hollow, diamond), not
 *  by colour alone. The popover is positioned `fixed` from the chip's own rectangle so a
 *  table's horizontal scroll container cannot clip it. Renders nothing without an entry,
 *  so older stored reports simply show no chips.
 */
export function SourceChip({ entry, lang, className = "", dot = false }: { entry?: ProvEntry | null; lang: Lang; className?: string; dot?: boolean }) {
  const id = useId();
  const ref = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  useEffect(() => {
    if (!pos) return;
    const close = () => setPos(null);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [pos]);
  if (!entry) return null;
  const st = KIND_STYLE[entry.kind];
  const open = () => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const w = Math.min(288, window.innerWidth - 16);
    setPos({ x: Math.max(8, Math.min(r.left, window.innerWidth - w - 8)), y: r.bottom + 6 });
  };
  const kindName = lang === "zh" ? KIND_NAME[entry.kind].zh : KIND_NAME[entry.kind].en;
  const lines = detailText(entry, lang);
  return (
    <span className={`inline-flex align-middle ${className}`}>
      <button
        ref={ref}
        type="button"
        aria-describedby={pos ? id : undefined}
        aria-label={`${kindName}: ${lines.join(" ")}`}
        onMouseEnter={open}
        onMouseLeave={() => setPos(null)}
        onFocus={open}
        onBlur={() => setPos(null)}
        onClick={() => (pos ? setPos(null) : open())}
        className={`group/chip relative -mx-1 -my-3 inline-flex min-h-10 min-w-10 items-center justify-center text-[11px] font-medium leading-4 whitespace-nowrap focus-visible:outline-none ${st.text}`}
      >
        {/* The button is 40 px tall for a finger; the visible chip inside keeps its small size. */}
        <span className={`inline-flex items-center gap-1 rounded-full border border-border/70 group-hover/chip:border-border group-focus-visible/chip:ring-2 group-focus-visible/chip:ring-ring ${dot ? "p-1" : "px-1.5 py-px"}`}>
          <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${st.dot}`} />
          {dot ? <span className="sr-only">{kindName}</span> : chipText(entry, lang)}
        </span>
      </button>
      {pos ? (
        <span id={id} role="tooltip" style={{ position: "fixed", left: pos.x, top: pos.y, width: Math.min(288, (typeof window === "undefined" ? 288 : window.innerWidth) - 16) }} className="z-50 rounded-lg border border-border bg-popover p-2.5 text-left text-xs font-normal leading-snug text-popover-foreground shadow-md">
          {lines.map((l) => (
            <span key={l} className="mb-1 block last:mb-0">
              {l}
            </span>
          ))}
        </span>
      ) : null}
    </span>
  );
}

/** One line that explains the four chips, shown once above the evidence. */
export function SourceLegend({ lang }: { lang: Lang }) {
  const kinds: ProvKind[] = ["live", "history", "assumed", "ai"];
  const kindTag = (k: ProvKind) => (
    <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${KIND_STYLE[k].text}`}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${KIND_STYLE[k].dot}`} />
      {lang === "zh" ? KIND_NAME[k].zh : KIND_NAME[k].en}
    </span>
  );
  return (
    <div className="mt-4 text-xs text-muted-foreground">
      {/* One quiet line of the four kinds at every width; the meanings open on tap. */}
      <details>
        <summary className="flex min-h-10 cursor-pointer select-none flex-nowrap items-center gap-x-2.5 whitespace-nowrap hover:text-foreground">
          <span className="font-medium text-foreground">{lang === "zh" ? "来源：" : "Sources:"}</span>
          {kinds.map((k) => (
            <span key={k}>{kindTag(k)}</span>
          ))}
        </summary>
        <ul className="mt-1 space-y-1">
          {kinds.map((k) => (
            <li key={k} className="flex flex-wrap items-center gap-x-1.5">
              {kindTag(k)}
              {lang === "zh" ? KIND_MEANING[k].zh : KIND_MEANING[k].en}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
