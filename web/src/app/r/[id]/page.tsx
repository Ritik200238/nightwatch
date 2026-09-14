"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ReportView } from "@/components/report/report-view";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api, type Report } from "@/lib/api";
import { fmtTime } from "@/lib/format";

/** One stored report, reopened exactly as it was argued.
 *
 *  Nothing is recomputed here. The page shows the report the desk produced at that
 *  moment, with the hash of the inputs it used, which is the point: a link somebody else
 *  opens has to show them what you saw, not what the market is doing now.
 */
export default function StoredReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .report(id)
      .then((r) => !cancelled && setReport(r))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load that report."));
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) {
    return (
      <div className="mx-auto max-w-xl space-y-3 py-10 text-center">
        <h1 className="text-lg font-semibold">That report is not here</h1>
        <p className="text-sm text-muted-foreground">{error}</p>
        <p className="text-sm">
          <Link href="/" className="underline underline-offset-2">
            Run a new one on the desk
          </Link>
          {" · "}
          <Link href="/journal" className="underline underline-offset-2">
            see every call in the journal
          </Link>
        </p>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm">
        <p className="font-medium">A saved report, not a live one</p>
        <p className="text-xs text-muted-foreground">
          This is forecast #{id} exactly as the desk argued it at {fmtTime(report.as_of)}. Nothing on this page has been recomputed since.{" "}
          <Link href="/" className="underline underline-offset-2">
            Run the same trade now
          </Link>
          .
        </p>
      </div>
      <ReportView report={report} />
    </div>
  );
}
