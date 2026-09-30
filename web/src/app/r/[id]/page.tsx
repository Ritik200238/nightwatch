import type { Metadata } from "next";
import { shareFacts } from "@/lib/site-api";
import { StoredReport } from "./stored-report";

const WORD: Record<string, string> = { GO: "GO", REDUCE_TO: "REDUCE", HEDGE: "HEDGE", REVIEW: "REVIEW", NO_GO: "NO GO" };

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const f = await shareFacts(id);
  if (!f) return { title: "Stored report" };
  const title = `${f.side.toUpperCase()} ${f.size} ${f.ticker}: ${WORD[f.verdict] ?? f.verdict}`;
  const description = "A stored Nightwatch stress test, reopened exactly as it was argued.";
  return { title, description, openGraph: { title, description }, twitter: { title, description } };
}

export default async function StoredReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StoredReport id={id} />;
}
