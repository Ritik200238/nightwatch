"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { verdictText } from "@/lib/verdict-style";
import { useLang } from "@/lib/lang";
import { ProofTabs } from "./proof-tabs";

/** One width for every proof page, so moving between them does not shift the layout. */
export const PROOF_WIDTH = "mx-auto w-full max-w-5xl";
/** Vertical rhythm between the blocks of a proof page (32 px; sections inside use 24). */
export const PROOF_STACK = "space-y-8";
export const H1_CLASS = "t-title";
export const INTRO_CLASS = "t-body mt-2 max-w-prose text-muted-foreground";

/** The heading block shared by every proof page: tabs, then title and a one-line description. */
export function PageHead({ title, intro, actions, tabs = false }: { title: string; intro: ReactNode; actions?: ReactNode; tabs?: boolean }) {
  return (
    <div className="space-y-6">
      {tabs ? <ProofTabs /> : null}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0">
          <h1 className={H1_CLASS}>{title}</h1>
          <p className={INTRO_CLASS}>{intro}</p>
        </div>
        {actions}
      </div>
    </div>
  );
}

/** The page's answer in two or three sentences, above every table. Open, with a quiet rule,
 *  not a box. */
export function PlainBox({ children }: { children: ReactNode }) {
  const { tx } = useLang();
  return (
    <div className="border-l-2 border-foreground/25 pl-4">
      <p className="t-label">{tx("In plain words", "通俗地说")}</p>
      <p className="t-body mt-1 max-w-prose">{children}</p>
    </div>
  );
}

/** A status word in running text or a header: colour on the text, no outline, no fill.
 *  A verdict keeps the shared verdict colour map. */
export function Tag({ children, tone = "muted", verdict }: { children: ReactNode; tone?: "good" | "warning" | "critical" | "muted" | "info"; verdict?: string }) {
  const cls = verdict ? verdictText(verdict) : tone === "good" ? "text-status-good" : tone === "warning" ? "text-status-warning" : tone === "critical" ? "text-status-critical" : tone === "info" ? "text-primary" : "text-muted-foreground";
  return <span className={`inline-flex items-center text-[13px] font-medium whitespace-nowrap ${cls}`}>{children}</span>;
}

/** One number, large, with its label above and a quiet hint below. No box: a hairline above
 *  and whitespace do the grouping. */
export function Figure({ label, value, hint, tone, chip }: { label: string; value: string; hint?: string; tone?: "good" | "warning" | "critical" | "muted"; chip?: ReactNode }) {
  const color = tone === "good" ? "text-status-good" : tone === "warning" ? "text-status-warning" : tone === "critical" ? "text-status-critical" : "";
  return (
    <div className="flex min-w-0 flex-col gap-1 border-t border-border pt-3">
      <span className="t-caption">{label}</span>
      <span className={`text-2xl leading-tight font-semibold tracking-tight [overflow-wrap:anywhere] [word-break:keep-all] tabular-nums sm:text-[1.75rem] ${color}`}>{value}</span>
      {hint ? <span className="t-caption">{hint}</span> : null}
      {chip ? <span className="mt-1 flex">{chip}</span> : null}
    </div>
  );
}

/** A section of a proof page. Open, separated by a hairline and whitespace; with
 *  `collapsible` the heading row is a full-width button and the body starts closed.
 *  Same props as the report Section, so a page can swap one for the other. */
export function OpenSection({
  title,
  subtitle,
  children,
  action,
  collapsible = false,
  defaultOpen = false,
  summary,
  openAll,
  tier = "default",
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  action?: ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  summary?: ReactNode;
  openAll?: boolean;
  tier?: "primary" | "default" | "quiet";
}) {
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => {
    if (openAll !== undefined) setOpen(openAll);
  }, [openAll]);
  const titleCls = tier === "quiet" ? "text-sm font-medium text-muted-foreground" : "t-heading";

  if (!collapsible) {
    return (
      <section className="border-t border-border pt-6">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 space-y-1">
            <h2 className={titleCls}>{title}</h2>
            {subtitle ? <p className="t-caption max-w-prose">{subtitle}</p> : null}
          </div>
          {action}
        </div>
        <div className="mt-6">{children}</div>
      </section>
    );
  }

  return (
    <section className="border-t border-border">
      <h2>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="-mx-2 flex min-h-14 w-[calc(100%+1rem)] items-center justify-between gap-4 rounded-md px-2 py-4 text-left hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <span className="min-w-0 space-y-1">
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className={titleCls}>{title}</span>
              {action}
            </span>
            {summary ? <span className="t-caption block max-w-prose font-normal">{summary}</span> : subtitle ? <span className="t-caption block max-w-prose font-normal">{subtitle}</span> : null}
          </span>
          <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
        </button>
      </h2>
      {open ? (
        <div className="pt-2 pb-6">
          {summary && subtitle ? <p className="t-caption mb-4 max-w-prose">{subtitle}</p> : null}
          {children}
        </div>
      ) : null}
    </section>
  );
}

/** "The short version": one line per finding, the tag on the left, the sentence on the right. */
export function Digest({ title, children, note }: { title: string; children: ReactNode; note?: ReactNode }) {
  return (
    <section aria-label={title} className="border-t border-border pt-6">
      <h2 className="t-heading">{title}</h2>
      <ul className="mt-4 space-y-3">{children}</ul>
      {note ? <p className="t-caption mt-4 max-w-prose">{note}</p> : null}
    </section>
  );
}
export function DigestRow({ tag, children }: { tag: ReactNode; children: ReactNode }) {
  return (
    <li className="t-body grid gap-x-6 gap-y-0.5 sm:grid-cols-[9rem_1fr]">
      <span>{tag}</span>
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/** Placeholder blocks plus a line of text, at a fixed height so the page does not jump
 *  when the data arrives. After `slowAfterMs` it says the wait is longer than usual and,
 *  when `onRetry` is given, offers a retry, so a down server never looks like an endless load. */
export function LoadingRecord({ blocks = [96, 256], onRetry, slowAfterMs = 12_000 }: { blocks?: number[]; onRetry?: () => void; slowAfterMs?: number }) {
  const { tx } = useLang();
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setSlow(true), slowAfterMs);
    return () => clearTimeout(id);
  }, [slowAfterMs]);
  return (
    <div className="space-y-4" role="status" aria-live="polite">
      <p className="text-sm text-muted-foreground">
        {slow ? tx("Still loading. The server is slow or not answering right now.", "仍在加载。服务器响应很慢，或暂时没有响应。") : tx("Loading the public record…", "正在加载公开记录…")}
        {slow && onRetry ? (
          <>
            {" "}
            <button type="button" onClick={onRetry} className="inline-flex min-h-10 items-center rounded-md px-2 underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              {tx("Try again", "重试")}
            </button>
          </>
        ) : null}
      </p>
      {blocks.map((h, i) => (
        <div key={i} aria-hidden className="animate-pulse rounded-lg bg-muted" style={{ height: h }} />
      ))}
    </div>
  );
}

/** A failed load of a record page: what happened, in plain words, and a way to try again. */
export function RecordError({ message, onRetry }: { message: string; onRetry: () => void }) {
  const { tx } = useLang();
  return (
    <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
      <p className="font-medium">{tx("Could not load this page", "无法加载此页面")}</p>
      <p className="mt-1 text-[13px] text-muted-foreground">{message}</p>
      <button type="button" onClick={onRetry} className="mt-2 inline-flex min-h-10 items-center rounded-md border border-border px-4 text-sm hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        {tx("Try again", "重试")}
      </button>
    </div>
  );
}

/** A horizontally scrolling table with a fade on the right edge while there is more to
 *  scroll to, so a clipped column is never mistaken for the end of the table. */
export function ScrollTable({ children }: { children: ReactNode }) {
  const wrap = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);

  useEffect(() => {
    const root = wrap.current;
    const own = scroller.current;
    if (!root || !own) return;
    // The shared Table renders its own scroll container; fall back to our own box.
    const inner = root.querySelector<HTMLElement>('[data-slot="table-container"]');
    const box: HTMLElement = inner ?? own;
    const update = () => setMore(box.scrollWidth - box.clientWidth - box.scrollLeft > 4);
    update();
    box.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      box.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [children]);

  return (
    <div ref={wrap} className="relative">
      <div ref={scroller} className="overflow-x-auto">
        {children}
      </div>
      <div
        aria-hidden
        className={`pointer-events-none absolute inset-y-0 right-0 w-8 transition-opacity ${more ? "opacity-100" : "opacity-0"}`}
        style={{ background: "linear-gradient(to left, var(--background), transparent)" }}
      />
    </div>
  );
}
