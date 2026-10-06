"use client";

import { ChevronDown } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { chipText, detailText, KIND_MEANING, KIND_NAME, type ProvEntry, type ProvKind } from "@/lib/provenance";
import type { Lang } from "@/lib/i18n";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** A card of the report.
 *
 *  With `collapsible`, the header becomes a button and the body starts closed. A report
 *  has twelve of these and the full text runs to nine thousand words; open all at once it
 *  reads as noise rather than as depth. Each collapsed header carries `summary` — the one
 *  number that section is about — so the page still scans as an index of the evidence,
 *  and you open the parts you want to argue with.
 *
 *  `openAll` lets a parent force every section open at once, for the reader who does want
 *  the wall, and for printing.
 */
export function Section({
  title,
  subtitle,
  children,
  action,
  collapsible = false,
  defaultOpen = false,
  summary,
  openAll,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  action?: ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  summary?: ReactNode;
  openAll?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  // A parent's expand-all wins while it is set; after that the section is the reader's again.
  useEffect(() => {
    if (openAll !== undefined) setOpen(openAll);
  }, [openAll]);

  if (!collapsible) {
    return (
      <Card className="gap-4 py-5">
        <CardHeader className="flex flex-row items-start justify-between gap-4 px-5">
          <div className="space-y-1">
            <CardTitle role="heading" aria-level={2} className="text-sm font-semibold">{title}</CardTitle>
            {subtitle ? <p className="text-[13px] text-muted-foreground">{subtitle}</p> : null}
          </div>
          {action}
        </CardHeader>
        <CardContent className="px-5">{children}</CardContent>
      </Card>
    );
  }

  return (
    <Card className={`gap-0 py-0 ${open ? "" : "hover:border-border/80"}`}>
      <div role="heading" aria-level={2}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 rounded-xl px-5 py-4 text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <span className="min-w-0 space-y-1">
          <span className="flex items-center gap-2">
            <CardTitle className="text-sm font-semibold">{title}</CardTitle>
            {action}
          </span>
          {summary ? <span className="block text-[13px] text-muted-foreground">{summary}</span> : subtitle ? <span className="block text-[13px] text-muted-foreground">{subtitle}</span> : null}
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      </div>
      {open ? (
        <CardContent className="px-5 pb-5">
          {summary && subtitle ? <p className="mb-3 text-[13px] text-muted-foreground">{subtitle}</p> : null}
          {children}
        </CardContent>
      ) : null}
    </Card>
  );
}

/** Stat tile: label · value · optional hint. Value in proportional figures. */
export function Stat({ label, value, hint, tone, chip }: { label: string; value: string; hint?: string; tone?: "good" | "warning" | "critical" | "muted"; chip?: ReactNode }) {
  const color = tone === "good" ? "text-status-good" : tone === "warning" ? "text-status-warning" : tone === "critical" ? "text-status-critical" : "";
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-lg border border-border bg-background/40 px-3 py-2">
      <span className="text-[13px] leading-snug text-muted-foreground">{label}</span>
      <span className={`text-base font-semibold leading-tight ${color}`}>{value}</span>
      {hint ? <span className="text-[13px] leading-snug text-muted-foreground">{hint}</span> : null}
      {chip ? <span className="mt-0.5 flex">{chip}</span> : null}
    </div>
  );
}

export function Pill({ children, tone = "muted" }: { children: ReactNode; tone?: "good" | "warning" | "critical" | "muted" | "info" }) {
  const cls =
    tone === "good" ? "border-status-good/40 text-status-good" : tone === "warning" ? "border-status-warning/50 text-status-warning" : tone === "critical" ? "border-status-critical/50 text-status-critical" : tone === "info" ? "border-primary/40 text-primary" : "border-border text-muted-foreground";
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}>{children}</span>;
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
        className={`inline-flex items-center gap-1 rounded-full border border-border/70 ${dot ? "p-1" : "px-1.5 py-px"} text-[11px] font-medium leading-4 whitespace-nowrap hover:border-border focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none ${st.text}`}
      >
        <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${st.dot}`} />
        {dot ? <span className="sr-only">{kindName}</span> : chipText(entry, lang)}
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
  return (
    <p className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
      <span className="font-medium text-foreground">{lang === "zh" ? "每个数字的来源：" : "Where each number comes from:"}</span>
      {kinds.map((k) => (
        <span key={k} className="inline-flex items-center gap-1.5">
          <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${KIND_STYLE[k].text}`}>
            <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${KIND_STYLE[k].dot}`} />
            {lang === "zh" ? KIND_NAME[k].zh : KIND_NAME[k].en}
          </span>
          {lang === "zh" ? KIND_MEANING[k].zh : KIND_MEANING[k].en}
        </span>
      ))}
    </p>
  );
}
