import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Data sources",
  description: "Every feed behind a report and when it last updated.",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
