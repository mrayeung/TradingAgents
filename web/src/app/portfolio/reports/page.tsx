"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ReportSummary } from "@/lib/api";
import clsx from "clsx";

function ratingColor(r: string) {
  const v = r.toUpperCase();
  if (v === "BUY" || v === "STRONG BUY") return "text-emerald-400 bg-emerald-400/10";
  if (v === "SELL" || v === "STRONG SELL") return "text-red-400 bg-red-400/10";
  return "text-amber-400 bg-amber-400/10";
}

function formatDate(d: string) {
  // "2026-06-27" → "Jun 27, 2026"
  try { return new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }); }
  catch { return d; }
}

// Group reports by ticker
function groupByTicker(reports: ReportSummary[]) {
  const map: Record<string, ReportSummary[]> = {};
  for (const r of reports) {
    (map[r.ticker] ??= []).push(r);
  }
  return map;
}

export default function ReportsPage() {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listReports();
      setReports(data.reports);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filtered = search.trim()
    ? reports.filter(r => r.ticker.toUpperCase().includes(search.toUpperCase()))
    : reports;

  const grouped = groupByTicker(filtered);
  const tickers = Object.keys(grouped).sort();

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Report Library</h1>
          <p className="text-slate-500 text-sm mt-1">
            Full TradingAgents reports — analyst write-ups, debate transcripts, final decisions
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-300 rounded-lg text-sm font-medium transition-colors"
        >
          {loading ? "…" : "↻ Refresh"}
        </button>
      </div>

      {/* Search */}
      <input
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Filter by ticker…"
        className="w-full mb-6 bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-sky-500 uppercase placeholder:normal-case"
      />

      {/* Error */}
      {error && (
        <div className="mb-4 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">{error}</div>
      )}

      {/* Empty */}
      {!loading && tickers.length === 0 && !error && (
        <div className="text-center py-20 text-slate-500">
          No reports found.{" "}
          <Link href="/portfolio/signals" className="text-sky-400 hover:underline">
            Run an analysis →
          </Link>
        </div>
      )}

      {/* Grouped report list */}
      <div className="space-y-4">
        {tickers.map(ticker => (
          <div key={ticker} className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            {/* Ticker header */}
            <div className="px-5 py-3 bg-slate-800/60 border-b border-slate-800 flex items-center gap-3">
              <span className="font-bold text-slate-100 font-mono text-sm">{ticker}</span>
              <span className="text-xs text-slate-500">{grouped[ticker].length} report{grouped[ticker].length !== 1 ? "s" : ""}</span>
            </div>

            {/* Report rows */}
            <div className="divide-y divide-slate-800/60">
              {grouped[ticker].map(report => (
                <Link
                  key={report.date}
                  href={`/portfolio/reports/${report.ticker}/${report.date}`}
                  className="flex items-center gap-4 px-5 py-3.5 hover:bg-slate-800/40 transition-colors group"
                >
                  <span className="text-sm text-slate-300 group-hover:text-sky-400 transition-colors flex-1">
                    {formatDate(report.date)}
                  </span>
                  {report.rating && (
                    <span className={clsx("px-2.5 py-0.5 rounded-md text-xs font-bold", ratingColor(report.rating))}>
                      {report.rating}
                    </span>
                  )}
                  <span className="text-slate-600 group-hover:text-sky-400 text-sm transition-colors">→</span>
                </Link>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
