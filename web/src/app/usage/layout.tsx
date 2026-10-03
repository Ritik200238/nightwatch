import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Usage",
  description: "Who uses the desk, counted without accounts.",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
