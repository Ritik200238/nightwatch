/**
 * How the live record is counted, in one line, for the home page and the report.
 *
 * Why: the scored count alone overstates the evidence. The same ticket asked again is one
 * outcome, and every forecast on one night shares that night's market move, so the
 * distinct events and the nights are said next to it. The numbers are /misses' own.
 */

export interface RecordCounts {
  scored: number;
  distinct_events?: number;
  n_nights?: number;
}

/** "1,805 forecasts scored · 656 distinct events · 22 nights"; the parts the server sent, no others. */
export function recordCountsText(t: RecordCounts, lang: "en" | "zh"): string {
  const n = (x: number) => x.toLocaleString("en-US");
  const zh = lang === "zh";
  const parts = [zh ? `已评分 ${n(t.scored)} 个预测` : `${n(t.scored)} forecasts scored`];
  if (t.distinct_events != null) parts.push(zh ? `${n(t.distinct_events)} 个独立事件` : `${n(t.distinct_events)} distinct events`);
  if (t.n_nights != null) parts.push(zh ? `${n(t.n_nights)} 个夜晚` : `${n(t.n_nights)} ${t.n_nights === 1 ? "night" : "nights"}`);
  return parts.join(" · ");
}
