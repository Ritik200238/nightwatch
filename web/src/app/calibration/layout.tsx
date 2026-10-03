import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Calibration",
  description: "Does the desk tell the truth? Every forecast scored against what then happened.",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
