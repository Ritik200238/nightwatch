import { ImageResponse } from "next/og";

export const OG_SIZE = { width: 1200, height: 630 };

const VERDICT_COLOR: Record<string, string> = { GO: "#34d399", REDUCE_TO: "#60a5fa", HEDGE: "#60a5fa", REVIEW: "#fbbf24", NO_GO: "#f87171" };
const VERDICT_WORD: Record<string, string> = { GO: "GO", REDUCE_TO: "REDUCE", HEDGE: "HEDGE", REVIEW: "REVIEW", NO_GO: "NO GO" };

export interface OgReport {
  ticker: string;
  side: string;
  size: string;
  verdict: string;
}

/** One card for the site and for a stored report. Images are drawn from the same
 *  numbers the page shows; with no report it is the product card. */
export function ogImage(report: OgReport | null): ImageResponse {
  const color = report ? (VERDICT_COLOR[report.verdict] ?? "#a1a1aa") : "#34d399";
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", background: "#0a0a0b", color: "#fafafa", padding: 72, fontFamily: "sans-serif" }}>
        <div style={{ display: "flex", alignItems: "center", fontSize: 34, fontWeight: 700, letterSpacing: -1 }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: color, marginRight: 16 }} />
          Nightwatch
        </div>
        {report ? (
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", fontSize: 40, color: "#a1a1aa" }}>{`${report.side.toUpperCase()} ${report.size} of ${report.ticker}`}</div>
            <div style={{ display: "flex", fontSize: 168, fontWeight: 800, letterSpacing: -6, color, lineHeight: 1.05 }}>{VERDICT_WORD[report.verdict] ?? report.verdict}</div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", fontSize: 88, fontWeight: 800, letterSpacing: -3, lineHeight: 1.05 }}>Stress-test the trade before you place it.</div>
            <div style={{ display: "flex", fontSize: 36, color: "#a1a1aa", marginTop: 28 }}>Tokenized US stocks trade 24/7. Nightwatch shows what happened last time, prices the exit on Bitget&apos;s live book, and scores its own calls in public.</div>
          </div>
        )}
        <div style={{ display: "flex", fontSize: 26, color: "#71717a" }}>
          {report ? "Stress-tested by Nightwatch. Research tool; it never places orders." : "nightwatch-gules.vercel.app"}
        </div>
      </div>
    ),
    OG_SIZE,
  );
}
