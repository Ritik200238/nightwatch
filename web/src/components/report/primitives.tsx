"use client";

import { ChevronDown } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
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
            <CardTitle className="text-sm font-semibold">{title}</CardTitle>
            {subtitle ? <p className="text-xs text-muted-foreground">{subtitle}</p> : null}
          </div>
          {action}
        </CardHeader>
        <CardContent className="px-5">{children}</CardContent>
      </Card>
    );
  }

  return (
    <Card className={`gap-0 py-0 ${open ? "" : "hover:border-border/80"}`}>
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
          {summary ? <span className="block text-xs text-muted-foreground">{summary}</span> : subtitle ? <span className="block truncate text-xs text-muted-foreground">{subtitle}</span> : null}
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open ? (
        <CardContent className="px-5 pb-5">
          {summary && subtitle ? <p className="mb-3 text-xs text-muted-foreground">{subtitle}</p> : null}
          {children}
        </CardContent>
      ) : null}
    </Card>
  );
}

/** Stat tile: label · value · optional hint. Value in proportional figures. */
export function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "good" | "warning" | "critical" | "muted" }) {
  const color = tone === "good" ? "text-status-good" : tone === "warning" ? "text-status-warning" : tone === "critical" ? "text-status-critical" : "";
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-lg border border-border bg-background/40 px-3 py-2">
      <span className="truncate text-xs text-muted-foreground">{label}</span>
      <span className={`text-base font-semibold leading-tight ${color}`}>{value}</span>
      {hint ? <span className="truncate text-xs text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

export function Pill({ children, tone = "muted" }: { children: ReactNode; tone?: "good" | "warning" | "critical" | "muted" | "info" }) {
  const cls =
    tone === "good" ? "border-status-good/40 text-status-good" : tone === "warning" ? "border-status-warning/50 text-status-warning" : tone === "critical" ? "border-status-critical/50 text-status-critical" : tone === "info" ? "border-primary/40 text-primary" : "border-border text-muted-foreground";
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}>{children}</span>;
}
