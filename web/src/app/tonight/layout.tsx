import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Tonight",
  description: "Check everything you hold against tonight's US market close, before the market reopens.",
};

export default function TonightLayout({ children }: { children: ReactNode }) {
  return children;
}
