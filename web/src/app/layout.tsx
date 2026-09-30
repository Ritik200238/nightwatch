import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { SiteFooter, SiteHeader } from "@/components/site-nav";
import { LangProvider } from "@/lib/lang";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "https://nightwatch-gules.vercel.app";
const TAGLINE = "Stress-test a tokenized-US-stock trade before you place it.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE),
  title: { default: "Nightwatch", template: "%s · Nightwatch" },
  description: TAGLINE,
  openGraph: { type: "website", siteName: "Nightwatch", title: "Nightwatch", description: TAGLINE },
  twitter: { card: "summary_large_image", title: "Nightwatch", description: TAGLINE },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <LangProvider>
          <header className="border-b border-border">
            <SiteHeader />
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-6 lg:px-8">{children}</main>
          <footer className="border-t border-border">
            <SiteFooter />
          </footer>
        </LangProvider>
      </body>
    </html>
  );
}
