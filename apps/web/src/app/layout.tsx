import "./globals.css";
import { Navigation } from "@/components/Navigation";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Algo Lab — Quantitative Research OS",
  description: "Systematic research and decision platform for Indian markets",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-background text-slate-100 flex min-h-screen">
        <Navigation />
        <div className="flex-1 flex flex-col min-w-0">
          <header className="h-14 border-b border-surface-border bg-surface/50 backdrop-blur px-6 flex items-center justify-between sticky top-0 z-10">
            <div className="flex items-center space-x-3">
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
                INDIAN MARKETS (NSE/BSE)
              </span>
              <span className="text-xs text-slate-400 font-mono">
                Stage 1: Foundation Architecture
              </span>
            </div>
            <div className="flex items-center space-x-3 text-xs font-mono">
              <div className="flex items-center space-x-1.5 text-emerald-400">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span>SYSTEM ONLINE</span>
              </div>
            </div>
          </header>
          <main className="flex-1 p-8 overflow-y-auto">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
