import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Status",
  description: "Is the desk running, are the feeds fresh, do the receipts check.",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
