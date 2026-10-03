import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Journal",
  description: "Every forecast, written down before the outcome and scored after.",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
