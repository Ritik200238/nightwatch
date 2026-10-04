"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

/** A named heading that folds a run of report sections away, so the page opens on the
 *  verdict and the evidence behind it and a reader scans the rest by heading. Nothing
 *  inside is removed: the sections keep their own summaries and open/close state. */
export function Group({ title, hint, openAll, children }: { title: string; hint: string; openAll?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  // The report's expand-all / collapse-all wins while it is set; after that the reader owns it.
  useEffect(() => {
    if (openAll !== undefined) setOpen(openAll);
  }, [openAll]);
  return (
    <div className="rounded-xl border border-border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 rounded-xl px-5 py-4 text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <span className="min-w-0">
          <span className="block text-base font-semibold">{title}</span>
          <span className="block text-[13px] text-muted-foreground">{hint}</span>
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {/* Hidden rather than unmounted: sections keep their state and the page keeps its anchors. */}
      <div className={open ? "space-y-4 px-3 pb-3 sm:px-4 sm:pb-4" : "hidden"}>{children}</div>
    </div>
  );
}
