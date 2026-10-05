"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLang } from "@/lib/lang";
import { ProofTabs } from "./proof-tabs";

/** One width for every proof page, so moving between them does not shift the layout. */
export const PROOF_WIDTH = "mx-auto w-full max-w-5xl";
export const H1_CLASS = "text-xl font-semibold tracking-tight";
export const INTRO_CLASS = "mt-1 max-w-prose text-sm text-muted-foreground";

/** The heading block shared by the proof, status, sources and usage pages. */
export function PageHead({ title, intro, actions, tabs = false }: { title: string; intro: ReactNode; actions?: ReactNode; tabs?: boolean }) {
  return (
    <div className="space-y-4">
      {tabs ? <ProofTabs /> : null}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className={H1_CLASS}>{title}</h1>
          <p className={INTRO_CLASS}>{intro}</p>
        </div>
        {actions}
      </div>
    </div>
  );
}

/** The page's answer in two or three sentences, above every table. */
export function PlainBox({ children }: { children: ReactNode }) {
  const { tx } = useLang();
  return (
    <div className="rounded-lg border border-border bg-muted/40 p-4 text-sm">
      <p className="font-medium">{tx("In plain words", "通俗地说")}</p>
      <p className="mt-1 leading-relaxed text-muted-foreground">{children}</p>
    </div>
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
        style={{ background: "linear-gradient(to left, var(--card), transparent)" }}
      />
    </div>
  );
}
