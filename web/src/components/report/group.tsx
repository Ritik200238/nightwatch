"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

/** A named heading that folds a run of report sections away, so the page opens on the
 *  verdict and the evidence behind it and a reader scans the rest by heading. Nothing
 *  inside is removed: the sections keep their own summaries and open/close state. */
export function Group({ title, hint, openAll, tier = "quiet", children }: { title: string; hint: string; openAll?: boolean; tier?: "primary" | "quiet"; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  // The report's expand-all / collapse-all wins while it is set; after that the reader owns it.
  useEffect(() => {
    if (openAll !== undefined) setOpen(openAll);
  }, [openAll]);
  return (
    <div className={`border-t ${tier === "primary" ? "border-foreground/30" : "border-border"}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`-mx-2 flex w-[calc(100%+1rem)] items-center justify-between gap-4 rounded-md px-2 ${tier === "primary" ? "min-h-16 py-5" : "min-h-14 py-4"} text-left hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none`}
      >
        <span className="min-w-0">
          <span className={tier === "primary" ? "t-heading block" : "block text-sm font-medium text-muted-foreground"}>{title}</span>
          <span className="t-caption mt-0.5 block">{hint}</span>
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {/* Hidden rather than unmounted: sections keep their state and the page keeps its anchors. */}
      <div className={open ? "space-y-6 pt-2 pb-6" : "hidden"}>{children}</div>
    </div>
  );
}
