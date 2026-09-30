"use client";

import Link from "next/link";
import { HealthPill } from "@/components/health-pill";
import { LangToggle, useLang } from "@/lib/lang";

const LINK = "rounded-md px-2 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none sm:px-3";

/** Brand, primary nav, language switch and status pill. Client component so the labels
 *  follow the global language; the layout around it stays a server component. */
export function SiteHeader() {
  const { tx } = useLang();
  const items: [string, string][] = [
    ["/", tx("Desk", "交易台")],
    ["/tonight", tx("Tonight", "今晚")],
    ["/calibration", tx("Calibration", "校准")],
    ["/studies", tx("Studies", "研究")],
    ["/journal", tx("Journal", "日志")],
    ["/wrong", tx("What we got wrong", "我们错在哪")],
  ];
  return (
    <div className="mx-auto flex min-h-14 w-full max-w-7xl flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-2 md:flex-nowrap md:px-6 lg:px-8">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 sm:gap-x-6">
        <Link href="/" className="rounded-md text-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none">
          Nightwatch
        </Link>
        {/* Wraps rather than clips: six destinations do not fit next to the brand at 375px. */}
        <nav aria-label={tx("Primary", "主导航")} className="flex flex-wrap items-center gap-x-1 gap-y-0.5">
          {items.map(([href, label]) => (
            <Link key={href} href={href} className={LINK}>
              {label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <LangToggle />
        <HealthPill />
      </div>
    </div>
  );
}

export function SiteFooter() {
  const { tx } = useLang();
  return (
    <div className="mx-auto w-full max-w-7xl space-y-1 px-4 py-4 text-xs text-muted-foreground md:px-6 lg:px-8">
      <p>
      {tx(
        "Research tool. Nightwatch never places orders; the human decides. Every number is computed from stored market data and labelled with its source.",
        "研究工具。Nightwatch 不会下单，决定权在你。每个数字都由存储的市场数据计算得出，并标明来源。",
      )}
      </p>
      <p>
        <Link href="/status" className="underline underline-offset-2 hover:text-foreground">
          {tx("Status", "状态")}
        </Link>
        {" · "}
        <Link href="/sources" className="underline underline-offset-2 hover:text-foreground">
          {tx("Data sources", "数据来源")}
        </Link>
      </p>
    </div>
  );
}
