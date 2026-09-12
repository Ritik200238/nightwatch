import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function Section({ title, subtitle, children, action }: { title: string; subtitle?: string; children: ReactNode; action?: ReactNode }) {
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
