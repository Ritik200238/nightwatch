/** On a phone the report sits below the whole form, so a tap on "run" would otherwise leave the
 *  reader looking at the form while the work happens somewhere off screen. Smooth unless the
 *  reader asked for less motion; does nothing on wide screens where both columns are visible. */
export function scrollIntoViewOnSmall(el: HTMLElement | null): void {
  if (!el || typeof window === "undefined") return;
  if (!window.matchMedia("(max-width: 1023px)").matches) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
}

export function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function motion(): ScrollBehavior {
  return reducedMotion() ? "auto" : "smooth";
}

/** Bring the top of a freshly rendered answer into view. On a phone the answer sits under the
 *  form or chat, so it always scrolls there; on a wide screen both columns are visible and it
 *  only scrolls when the answer's top is off screen. Call after the answer has rendered. */
export function scrollToAnswer(el: HTMLElement | null): void {
  if (!el || typeof window === "undefined") return;
  const small = window.matchMedia("(max-width: 1023px)").matches;
  const top = el.getBoundingClientRect().top;
  if (!small && top >= 0 && top < window.innerHeight * 0.5) return;
  el.scrollIntoView({ behavior: motion(), block: "start" });
}

/** Scroll the start of a chat message into view, so a long reply is read from its first line
 *  rather than from the bottom. Skips the scroll when the start is already comfortably visible. */
export function scrollToMessageStart(el: HTMLElement | null): void {
  if (!el || typeof window === "undefined") return;
  const top = el.getBoundingClientRect().top;
  if (top >= 0 && top < window.innerHeight * 0.6) return;
  el.scrollIntoView({ behavior: motion(), block: "start" });
}
