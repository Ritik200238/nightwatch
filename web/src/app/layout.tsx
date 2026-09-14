import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import { HealthPill } from "@/components/health-pill";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Nightwatch",
  description: "Stress-test a tokenized-US-stock trade before you place it.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <header className="border-b border-border">
          <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between gap-3 px-4 md:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-3 sm:gap-6">
              <Link href="/" className="rounded-md text-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none">
                Nightwatch
              </Link>
              {/* The nav gives way before the status pill does: at 390px an "API offline"
                  pill is wider than the healthy one and used to sit on top of "Journal". */}
              <nav aria-label="Primary" className="flex min-w-0 items-center gap-1 overflow-x-auto">
                <Link href="/" className="rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                  Desk
                </Link>
                <Link href="/calibration" className="rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                  Calibration
                </Link>
                <Link href="/journal" className="rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                  Journal
                </Link>
              </nav>
            </div>
            <HealthPill />
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-6 lg:px-8">{children}</main>
        <footer className="border-t border-border">
          <p className="mx-auto w-full max-w-7xl px-4 py-4 text-xs text-muted-foreground md:px-6 lg:px-8">
            Research tool. Nightwatch never places orders; the human decides. Every number is computed from stored market data and labelled with its source.
          </p>
        </footer>
      </body>
    </html>
  );
}
