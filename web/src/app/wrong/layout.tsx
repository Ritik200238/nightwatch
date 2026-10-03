import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "What we got wrong",
  description: "Verdicts that went past their line and mistakes found in the desk.",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
