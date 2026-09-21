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
  breach_own_token: "outcomes below p5, same-token analogs",
  breach_other_tokens: "outcomes below p5, other-token analogs",
  boot_ci_low: "bootstrap interval, low",
  boot_ci_high: "bootstrap interval, high",
};

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
  const isShare = key.startsWith("breach_") || key.startsWith("pooled_lo") || key.startsWith("banded_lo") || key.startsWith("heldout_lo") || key === "share_near_tighter";
  if (isShare) return `${(v * 100).toFixed(1)}%`;
  if (key.includes("width") || key.startsWith("mean_move")) return `${v.toFixed(2)}%`;
  return Number.isInteger(v) ? String(v) : v.toFixed(3);
}

export default function StudiesPage() {
  const [rep, setRep] = useState<StudiesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .studies()
      .then(setRep)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the studies."));
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
                      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs lg:grid-cols-3">
                        {Object.entries(s.stats).map(([k, val]) => (
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
