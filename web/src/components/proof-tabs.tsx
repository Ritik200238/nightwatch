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
    <nav aria-label={tx("Track record", "战绩")} className="space-y-1.5">
      <p className="text-sm font-semibold tracking-tight text-foreground">{tx("Track record", "战绩")}</p>
      <ul className="flex flex-wrap gap-1.5">
        {tabs.map((t) => {
          const here = path === t.href || (path?.startsWith(`${t.href}/`) ?? false);
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={here ? "page" : undefined}
                className={`inline-flex min-h-10 items-center rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none ${
                  here ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:bg-muted hover:text-foreground"
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
