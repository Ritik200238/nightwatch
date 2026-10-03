import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Studies",
  description: "The claims behind the retrieval, each written so it could fail, with the results.",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
