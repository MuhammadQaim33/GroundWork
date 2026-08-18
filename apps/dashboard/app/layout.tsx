import type { Metadata } from "next";
import { Jura, Puritan } from "next/font/google";
import Link from "next/link";
import HeaderNav from "@/components/header-nav";
import "./globals.css";

const jura = Jura({
  variable: "--font-jura-src",
  subsets: ["latin"],
});

const puritan = Puritan({
  variable: "--font-puritan-src",
  weight: ["400", "700"],
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Groundwork",
  description: "Autonomous job search & interview system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${jura.variable} ${puritan.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-white font-puritan text-black">
        <header className="sticky top-0 z-[100] border-b border-black/10 bg-white/80 backdrop-blur-sm">
          <div className="container mx-auto flex items-center justify-between px-6 py-4 md:px-12">
            <Link href="/generate" className="group flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-brand animate-pulse" />
              <span className="font-jura text-xl font-bold tracking-tighter">GROUNDWORK</span>
            </Link>
            <HeaderNav />
          </div>
        </header>
        <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10 md:px-12">{children}</main>
      </body>
    </html>
  );
}
