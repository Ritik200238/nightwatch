"use client";

import { Check, Link2 } from "lucide-react";
import { useState } from "react";

/** Copy a link that reopens this exact report.
 *
 *  A verdict is an argument, and a screenshot of one is not evidence. The stored report
 *  is the same page with the same inputs hash, which is what makes it worth showing to
 *  someone else. Only recent live tickets are kept, and the page says so when one is gone.
 */
export function Permalink({ forecastId }: { forecastId: number }) {
  const [copied, setCopied] = useState(false);
  const href = `/r/${forecastId}`;

  async function copy() {
    const url = new URL(href, window.location.origin).toString();
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // A browser that refuses the clipboard still gets a link it can right-click.
      window.prompt("Copy this link", url);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <a href={href} className="inline-flex items-center gap-1 rounded underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        <Link2 className="h-3 w-3" aria-hidden />
        open this report on its own
      </a>
      <button
        type="button"
        onClick={() => void copy()}
        className="inline-flex items-center gap-1 rounded underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        {copied ? <Check className="h-3 w-3 text-status-good" aria-hidden /> : null}
        {copied ? "link copied" : "copy link"}
      </button>
    </span>
  );
}
