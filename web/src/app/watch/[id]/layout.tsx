import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Re-check at the US close",
  description: "A trade judged again once the US market has closed: the verdict then, and now.",
};

export default function WatchLayout({ children }: { children: ReactNode }) {
  return children;
}
