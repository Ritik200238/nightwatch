"use client";

import { CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Pill, Section, Stat } from "@/components/report/primitives";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type StudiesResponse, type Study } from "@/lib/api";
import { fmtTime } from "@/lib/format";

/** The verdict answers the question in the title, and nothing else.
 *
 *  It deliberately does not say whether the answer flattered us: "no, a token is not
 *  best explained by its own past" is why the search is pooled, and colouring that red
 *  would be lying about what the study found.
 */
const VERDICT: Record<Study["verdict"], { label: string; tone: "good" | "warning" | "muted"; Icon: typeof CheckCircle2 }> = {
  yes: { label: "yes", tone: "good", Icon: CheckCircle2 },
  no: { label: "no", tone: "warning", Icon: XCircle },
  unclear: { label: "cannot tell yet", tone: "muted", Icon: CircleHelp },
};

/** Stat keys are machine names; these are what a person would call them. Anything not
 *  named here still shows, with the underscores turned back into spaces. */
const STAT_LABEL: Record<string, string> = {
  sd_ratio_near_over_far: "spread of near half ÷ far half",
  iqr_ratio_near_over_far: "IQR of near half ÷ far half",
  share_near_tighter: "moments where near was tighter",
  breach_equal: "outcomes below p5, equal weighting",
  "breach_similarity (already computed)": "outcomes below p5, similarity weighting",
  pooled_lo_coverage: "one factor: outcomes below p5, overall",
  pooled_lo_overnight: "one factor: overnight",
  pooled_lo_multi_day: "one factor: multi-day",
  banded_lo_overnight: "per holding period: overnight",
  banded_lo_multi_day: "per holding period: multi-day",
  pooled_width_multi_day: "one factor: multi-day band width",
  banded_width_multi_day: "per holding period: multi-day band width",
  heldout_lo_batch: "held out, what we ship",
  heldout_lo_online: "held out, online update",
  mean_move_farthest_quartile: "move after the farthest quarter",
  mean_move_closest_quartile: "move after the closest quarter",
  pooled_t: "t, pooled",
  clustered_t: "t, clustered by token",
  raw_diff: "breach rate, most-disagreed third minus least",
  raw_t: "t, disagreement alone (thirds)",
  alone_t: "t, disagreement alone (slope)",
  controlled_t: "t, disagreement with size held fixed",
  size_t: "t, size of the shipped number",
  controlled_up: "tokens where disagreement still predicts",
  ensemble_t: "t, median of versions vs shipped",
  ensemble_up: "tokens where the median wins",
  breach_shipped: "outcomes below shipped p5",
  breach_ensemble: "outcomes below median-of-versions p5",
  breach_narrow: "outcomes below p5, narrowest third",
  breach_wide: "outcomes below p5, widest third",
  median_spread: "median disagreement, as a share of the shipped number",
  versions: "versions of the engine",
  breach_own_token: "outcomes below p5, same-token analogs",
  breach_other_tokens: "outcomes below p5, other-token analogs",
  boot_ci_low: "bootstrap interval, low",
  boot_ci_high: "bootstrap interval, high",
  move_flagged: "move after a flagged filing",
  move_rest: "move after the rest",
  n_flagged: "filings flagged",
  n_rest: "filings not flagged",
  tokens_agreeing: "tokens where it holds",
  hit_rate: "directional calls correct",
  ci_low: "interval, low",
  ci_high: "interval, high",
  share_committed: "filings it committed to",
  n_called: "directional calls made",
  n_read: "filings read",
  conditions_judged: "conditions with a decided answer",
  conditions_better: "narrowing scored better",
  conditions_worse: "narrowing scored worse",
};

/** Per-condition results, for a study whose stats are keyed "condition.metric".
 *
 *  Sixty numbers in a grid would bury the one comparison that matters, which is the
 *  same two columns for each condition: how often the unfiltered tail was breached and
 *  how often the narrowed one was, against a target of 5%.
 */
function ConditionTable({ stats, labels }: { stats: Record<string, number>; labels: Record<string, string> }) {
  const byCondition = new Map<string, Record<string, number>>();
  for (const [k, v] of Object.entries(stats)) {
    const dot = k.indexOf(".");
    if (dot < 0) continue;
    const name = k.slice(0, dot);
    const row = byCondition.get(name) ?? {};
    row[k.slice(dot + 1)] = v;
    byCondition.set(name, row);
  }
  if (!byCondition.size) return null;
  const rows = [...byCondition.entries()].sort((a, b) => (b[1].n ?? 0) - (a[1].n ?? 0));
  const pct = (v: number | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
  const num = (v: number | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : v.toFixed(d));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-xs">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-1 pr-3 font-medium">condition</th>
            <th className="py-1 pr-3 text-right font-medium">nights</th>
            <th className="py-1 pr-3 text-right font-medium">below p5, all hours</th>
            <th className="py-1 pr-3 text-right font-medium">below p5, narrowed</th>
            <th className="py-1 pr-3 text-right font-medium">typical p5, all → narrowed</th>
            <th className="py-1 text-right font-medium">t, by token</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map(([name, r]) => (
            <tr key={name} className="border-b border-border/50">
              <td className="py-1 pr-3">{labels[name] ?? name.replace(/_/g, " ")}</td>
              <td className="py-1 pr-3 text-right">{num(r.n, 0)}</td>
              <td className="py-1 pr-3 text-right">{pct(r.breach_all)}</td>
              <td className="py-1 pr-3 text-right">
                {pct(r.breach_lens)}
                {r.breach_lens_lo != null ? <span className="text-muted-foreground"> [{pct(r.breach_lens_lo)}–{pct(r.breach_lens_hi)}]</span> : null}
              </td>
              <td className="py-1 pr-3 text-right">
                {r.p5_all_median != null ? `${num(r.p5_all_median, 1)}% → ${num(r.p5_lens_median, 1)}%` : "—"}
              </td>
              <td className="py-1 text-right">{num(r.t_clustered, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-muted-foreground">Target for both breach columns is 5%. A positive t means the narrowed tail scored better.</p>
    </div>
  );
}

/** The verdict in one line, for the collapsed header.
 *
 *  The header keeps showing its summary while the section is open, which is right when
 *  the summary is a digest of stats and wrong when it is the finding itself — the whole
 *  paragraph would then be printed twice, once small and grey and once properly. So the
 *  header gets the answer and the body gets the argument.
 */
function firstSentence(text: string): string {
  const m = text.match(/^.*?[.?!](?=\s|$)/);
  return m ? m[0] : text;
}

/** Shares are printed as percentages and everything else at three places, because a
 *  t-statistic rendered as "215%" is worse than no label at all. */
function statValue(key: string, v: number): string {
  const isShare =
    key.startsWith("breach_") ||
    key.startsWith("pooled_lo") ||
    key.startsWith("banded_lo") ||
    key.startsWith("heldout_lo") ||
    key === "share_near_tighter" ||
    key === "hit_rate" ||
    key === "ci_low" ||
    key === "ci_high" ||
    key === "share_committed";
  if (isShare) return `${(v * 100).toFixed(1)}%`;
  if (key.includes("width") || key.startsWith("mean_move") || key.startsWith("move_")) return `${v.toFixed(2)}%`;
  return Number.isInteger(v) ? String(v) : v.toFixed(3);
}

export default function StudiesPage() {
  const [rep, setRep] = useState<StudiesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lensLabels, setLensLabels] = useState<Record<string, string>>({});

  useEffect(() => {
    api
      .studies()
      .then(setRep)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the studies."));
    // The names a trader sees for each condition. Missing labels fall back to the
    // machine name, so a failed request costs wording, not the table.
    api
      .lenses()
      .then((r) => setLensLabels(Object.fromEntries(r.lenses.map((l) => [l.name, l.label]))))
      .catch(() => undefined);
  }, []);

  const yes = rep?.studies.filter((s) => s.verdict === "yes").length ?? 0;
  const no = rep?.studies.filter((s) => s.verdict === "no").length ?? 0;
  const unclear = rep?.studies.filter((s) => s.verdict === "unclear").length ?? 0;

  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-lg font-semibold tracking-tight">What we tested about our own retrieval</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The desk is built to find past moments like the one in front of you and report what followed. Anyone can describe doing that. These are the claims underneath it, written
          so they could fail, each one tested against this database and reported whichever way it came out.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Most of them came out against us. The obvious improvement — count the closest matches for more — turns out to make the forecast measurably worse, and the study below is
          why. One test found something worth fixing, and it is fixed.
        </p>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="font-medium">Couldn&apos;t load the studies</p>
          <p className="text-xs text-muted-foreground">{error}</p>
        </div>
      ) : null}

      {!rep && !error ? (
        <>
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </>
      ) : null}

      {rep && !rep.studies.length ? (
        <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          {rep.note || "No studies have been run against this database yet."}
        </div>
      ) : null}

      {rep?.studies.length ? (
        <>
          <Section
            title="The scoreboard"
            subtitle={`Last recomputed ${rep.last_run ? fmtTime(rep.last_run) : "unknown"}. Every number on this page is derived from the stored bars and the journal by \`nightwatch studies\`; none of it is typed in.`}
          >
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <Stat label="Questions asked" value={String(rep.studies.length)} hint="each written so it could come back no" />
              <Stat label="Answered yes" value={String(yes)} hint="and acted on" tone={yes ? "good" : undefined} />
              <Stat label="Answered no" value={String(no)} hint="which is the more useful half" tone={no ? "warning" : undefined} />
              <Stat label="Cannot tell yet" value={String(unclear)} hint="not enough matured history" />
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              A study that nobody acted on is decoration, so each one below ends with what changed because of it — including &ldquo;nothing, and here is why that is the right
              answer&rdquo;. The calibration behind two of these is on the{" "}
              <Link href="/calibration" className="underline underline-offset-2">
                calibration page
              </Link>
              .
            </p>
          </Section>

          {rep.studies.map((s) => {
            const v = VERDICT[s.verdict];
            return (
              <Section
                key={s.key}
                collapsible
                defaultOpen
                summary={firstSentence(s.finding)}
                title={s.title}
                subtitle={s.question}
                action={
                  <Pill tone={v.tone}>
                    <v.Icon className="mr-1 h-3 w-3" aria-hidden />
                    {v.label}
                  </Pill>
                }
              >
                <div className="space-y-3 text-sm">
                  <div>
                    <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">How it was tested</p>
                    <p className="mt-1 text-muted-foreground">{s.method}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">What came back</p>
                    <p className="mt-1 leading-relaxed">{s.finding}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-muted/30 p-3">
                    <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">What changed because of it</p>
                    <p className="mt-1 leading-relaxed">{s.consequence}</p>
                  </div>
                  {Object.keys(s.stats).length ? (
                    <div>
                      <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">The numbers ({s.n.toLocaleString()} observations)</p>
                      <ConditionTable stats={s.stats} labels={lensLabels} />
                      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs lg:grid-cols-3">
                        {Object.entries(s.stats).filter(([k]) => !k.includes(".")).map(([k, val]) => (
                          <div key={k} className="flex items-baseline justify-between gap-2 border-b border-border/50 py-1">
                            <span className="min-w-0 text-muted-foreground">{STAT_LABEL[k] ?? k.replace(/_/g, " ")}</span>
                            <span className="tabular shrink-0 font-medium">{statValue(k, val)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </Section>
            );
          })}
        </>
      ) : null}
    </div>
  );
}
