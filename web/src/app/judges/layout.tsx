import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "For judges",
  description: "What the Track 3 handbook asks for, and the live page that answers each point.",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
