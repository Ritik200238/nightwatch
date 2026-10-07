"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLang } from "@/lib/lang";

/** The four pages that together are the public record, shown as one group. */
export function ProofTabs() {
  const { tx } = useLang();
  const path = usePathname();
  const tabs = [
    { href: "/calibration", label: tx("Calibration", "校准") },
    { href: "/studies", label: tx("Studies", "研究") },
    { href: "/journal", label: tx("Journal", "日志") },
    { href: "/wrong", label: tx("Misses", "失误") },
  ];
  // Same words as the top nav ("Track record" / "战绩", "Misses" / "失误"), so the page matches where you clicked.
  return (
    <nav aria-label={tx("Track record", "战绩")} className="space-y-1">
      <p className="t-label">{tx("Track record", "战绩")}</p>
      <ul className="-mx-1 flex gap-x-1 overflow-x-auto border-b border-border px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {tabs.map((t) => {
          const here = path === t.href || (path?.startsWith(`${t.href}/`) ?? false);
          return (
            <li key={t.href} className="shrink-0">
              <Link
                href={t.href}
                aria-current={here ? "page" : undefined}
                className={`-mb-px inline-flex min-h-11 items-center border-b-2 px-3 text-sm whitespace-nowrap focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none ${
                  here ? "border-foreground font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
