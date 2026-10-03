import type { Metadata } from "next";
import DeskPage from "@/components/desk/desk-page";

export const metadata: Metadata = {
  title: "Stress-test",
  description: "A pre-trade desk for tokenized US stocks on Bitget: history, stress tests, your exit on the live order book, and a sized verdict.",
};

export default function Page() {
  return <DeskPage />;
}
