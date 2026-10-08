import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Method",
  description: "How a verdict is built, what the AI is and is not allowed to do, how the one-in-twenty line compares with plain stop rules, and what did not work.",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
