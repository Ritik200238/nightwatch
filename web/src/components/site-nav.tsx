"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import { snapshotFlag } from "@/lib/snapshot";
import { HealthPill } from "@/components/health-pill";
import { LangToggle, useLang } from "@/lib/lang";
import { fmtDateTimeL } from "@/lib/i18n";

const LINK = "shrink-0 whitespace-nowrap rounded-md px-2 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none sm:px-3 aria-[current=page]:bg-accent aria-[current=page]:font-medium aria-[current=page]:text-foreground";

/** Studies and Journal live under Track record (tabs on those pages), so they keep it lit. */
const TRACK_PATHS = ["/calibration", "/studies", "/journal"];

function isCurrent(href: string, path: string | null): boolean {
  if (!path) return false;
  if (href === "/") return path === "/" || path.startsWith("/r/") || path.startsWith("/watch/");
  if (href === "/calibration") return TRACK_PATHS.some((p) => path === p || path.startsWith(p + "/"));
  return path === href || path.startsWith(href + "/");
}

/** Shown when the proxy answered from a saved copy because the live server is down. */
function SnapshotBanner() {
  const { tx, lang } = useLang();
  const iso = useSyncExternalStore(snapshotFlag.subscribe, snapshotFlag.get, () => null);
  if (!iso) return null;
  const when = fmtDateTimeL(iso, lang);
  return (
    <div role="status" className="border-b border-amber-500/40 bg-amber-500/10 px-4 py-2 text-center text-sm">
      {tx(`Live server unreachable — showing a saved snapshot from ${when}`, `实时服务器无法连接，正在显示 ${when} 的已保存快照`)}
    </div>
  );
}

/** Brand, primary nav, language switch and status pill. Client component so the labels
 *  follow the global language; the layout around it stays a server component. */
export function SiteHeader() {
  const { tx } = useLang();
  const path = usePathname();
  const items: [string, string][] = [
    ["/", tx("Stress-test", "压力测试")],
    ["/tonight", tx("Tonight", "今晚")],
    ["/calibration", tx("Track record", "战绩")],
    ["/wrong", tx("Misses", "失误")],
  ];
  return (
    <>
    <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:ring-2 focus:ring-ring">{tx("Skip to content", "跳到正文")}</a>
    <SnapshotBanner />
    <div className="mx-auto flex min-h-14 w-full max-w-7xl items-center justify-between gap-x-3 px-4 py-2 md:px-6 lg:px-8">
      <div className="flex min-w-0 flex-1 items-center gap-x-2 sm:gap-x-6">
        <Link href="/" className="shrink-0 rounded-md text-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none">
          Nightwatch
        </Link>
        {/* One row at every width: it scrolls sideways on a phone instead of wrapping to three lines. */}
        <nav aria-label={tx("Primary", "主导航")} className="flex min-w-0 flex-1 items-center gap-x-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {items.map(([href, label]) => (
            <Link key={href} href={href} className={LINK} aria-current={isCurrent(href, path) ? "page" : undefined}>
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
    </>
  );
}

export function SiteFooter() {
  const { tx } = useLang();
  return (
    <div className="mx-auto w-full max-w-7xl space-y-1 px-4 py-4 text-[13px] text-muted-foreground md:px-6 lg:px-8">
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
        {" · "}
        <Link href="/usage" className="underline underline-offset-2 hover:text-foreground">
          {tx("Usage", "用量")}
        </Link>
      </p>
    </div>
  );
}
