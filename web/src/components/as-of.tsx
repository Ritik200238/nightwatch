"use client";

import { recall } from "@/lib/record-cache";
import { fmtTimeL } from "@/lib/i18n";
import { useLang } from "@/lib/lang";

/** When the figures on a record page were read. Several pages count the same things from
 *  caches that refresh at different moments, so two pages can differ by a verdict or a
 *  feed; each says when it looked, and the difference is no longer a mystery. Render-time
 *  read: the page re-renders when its data arrives, which is when this is written. */
export function AsOf({ path }: { path: string }) {
  const { tx, lang } = useLang();
  const hit = recall<unknown>(path);
  if (!hit) return null;
  const iso = new Date(hit.at).toISOString();
  return (
    <p className="text-[13px] text-muted-foreground">
      {tx(`Figures as of ${fmtTimeL(iso, lang)}. Pages count the same things from caches that refresh at different moments, so a total can differ by a few between pages.`, `数字截至 ${fmtTimeL(iso, lang)}。各页面的缓存刷新时间不同，同一项合计在不同页面可能相差几个。`)}
    </p>
  );
}
