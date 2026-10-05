"use client";

import { useSyncExternalStore } from "react";
import { busyNotice } from "@/lib/api";
import { busyMessage } from "@/lib/errors";
import { useLang } from "@/lib/lang";

/** Shown while a call is being retried, so a slow box reads as busy rather than broken. */
export function BusyBanner() {
  const { lang } = useLang();
  const on = useSyncExternalStore(busyNotice.subscribe, busyNotice.get, () => false);
  if (!on) return null;
  return (
    <div role="status" aria-live="polite" className="border-b border-amber-500/40 bg-amber-500/10 px-4 py-1.5 text-center text-sm">
      {busyMessage(lang)}
    </div>
  );
}
