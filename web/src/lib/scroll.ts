/** On a phone the report sits below the whole form, so a tap on "run" would otherwise leave the
 *  reader looking at the form while the work happens somewhere off screen. Smooth unless the
 *  reader asked for less motion; does nothing on wide screens where both columns are visible. */
export function scrollIntoViewOnSmall(el: HTMLElement | null): void {
  if (!el || typeof window === "undefined") return;
  if (!window.matchMedia("(max-width: 1023px)").matches) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
}
