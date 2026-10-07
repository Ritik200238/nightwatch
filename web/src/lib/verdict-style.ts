/** One colour map for every verdict badge and word, so the same verdict never looks
 *  different on two screens. GO green, REDUCE TO / HEDGE blue, REVIEW amber, NO GO red. */
export type VerdictKey = "GO" | "REDUCE_TO" | "HEDGE" | "REVIEW" | "NO_GO";

const TEXT: Record<VerdictKey, string> = {
  GO: "text-verdict-go",
  REDUCE_TO: "text-verdict-reduce",
  HEDGE: "text-verdict-reduce",
  REVIEW: "text-verdict-review",
  NO_GO: "text-verdict-nogo",
};

const BADGE: Record<VerdictKey, string> = {
  GO: "border-verdict-go/40 text-verdict-go",
  REDUCE_TO: "border-verdict-reduce/40 text-verdict-reduce",
  HEDGE: "border-verdict-reduce/40 text-verdict-reduce",
  REVIEW: "border-verdict-review/50 text-verdict-review",
  NO_GO: "border-verdict-nogo/50 text-verdict-nogo",
};

/** Text colour class for a verdict word; unknown values fall back to muted. */
export function verdictText(v: string): string {
  return TEXT[v as VerdictKey] ?? "text-muted-foreground";
}

/** Border + text classes for a verdict pill. */
export function verdictBadge(v: string): string {
  return BADGE[v as VerdictKey] ?? "border-border text-muted-foreground";
}
