import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Oasis TradingDesk",
  description: "Portfolio Construction powered by TradingAgents",
};

const NAV = [
  { href: "/portfolio/signals",      label: "📡 Signals",        desc: "Analyst conviction" },
  { href: "/portfolio/construct",    label: "⚖️  Construct",      desc: "BL optimisation" },
  { href: "/portfolio/benchmark",    label: "📈 Benchmark",      desc: "vs SPY / QQQ / DIA" },
  { href: "/portfolio/correlation",  label: "🔗 Correlation",    desc: "Risk clusters" },
  { href: "/portfolio/sizing",       label: "📐 Sizing",         desc: "Kelly criterion" },
  { href: "/portfolio/rebalance",    label: "🔄 Rebalance",      desc: "Trade list" },
  { href: "/portfolio/institutions", label: "🏦 Institutions",   desc: "13F portfolio tracker" },
  { href: "/portfolio/options",      label: "🎯 Options Action",  desc: "IV · trade ideas · flow" },
  { href: "/portfolio/reports",      label: "📚 Reports",         desc: "Full report library" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex h-screen overflow-hidden">
        {/* ── Sidebar ─────────────────────────────────────────────────────── */}
        <aside className="w-[220px] shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col">
          {/* Logo */}
          <div className="px-5 py-5 border-b border-slate-800">
            <span className="text-sky-400 font-bold text-lg tracking-tight">Oasis</span>
            <span className="text-slate-300 font-bold text-lg tracking-tight"> TradingDesk</span>
          </div>

          {/* Nav links */}
          <nav className="flex-1 overflow-y-auto py-3">
            {NAV.map(({ href, label, desc }) => (
              <Link
                key={href}
                href={href}
                className="flex flex-col px-5 py-3 hover:bg-slate-800 transition-colors group"
              >
                <span className="text-sm font-medium text-slate-200 group-hover:text-sky-400">
                  {label}
                </span>
                <span className="text-xs text-slate-500 mt-0.5">{desc}</span>
              </Link>
            ))}
          </nav>

          {/* Footer */}
          <div className="px-5 py-4 border-t border-slate-800 text-xs text-slate-600">
            Engine · localhost:8765
          </div>
        </aside>

        {/* ── Main content ─────────────────────────────────────────────────── */}
        <main className="flex-1 overflow-y-auto bg-slate-950">
          {children}
        </main>
      </body>
    </html>
  );
}
