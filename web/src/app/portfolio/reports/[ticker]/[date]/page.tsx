"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, FullReport } from "@/lib/api";
import clsx from "clsx";

// ─── Section component ────────────────────────────────────────────────────────

function ReportSection({ title, content, defaultOpen = false }: {
  title: string;
  content?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (!content) return null;

  return (
    <div className="border border-slate-800 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-5 py-3.5 bg-slate-900 hover:bg-slate-800/60 transition-colors text-left"
      >
        <span className="text-sm font-semibold text-slate-200">{title}</span>
        <span className="text-slate-500 text-xs">{open ? "▲ collapse" : "▼ expand"}</span>
      </button>
      {open && (
        <div className="px-5 py-4 bg-slate-950 text-sm text-slate-300 whitespace-pre-wrap leading-relaxed border-t border-slate-800 font-mono">
          {content}
        </div>
      )}
    </div>
  );
}

// ─── Rating badge ──────────────────────────────────────────────────────────────

function ratingColor(r: string) {
  const v = (r || "").toUpperCase();
  if (v.includes("BUY")) return "text-emerald-400 bg-emerald-400/15 border-emerald-500/30";
  if (v.includes("SELL")) return "text-red-400 bg-red-400/15 border-red-500/30";
  return "text-amber-400 bg-amber-400/15 border-amber-500/30";
}

function extractRating(decision: string): string {
  const m = decision.match(/\b(STRONG BUY|BUY|HOLD|SELL|STRONG SELL)\b/i);
  return m ? m[1].toUpperCase() : "";
}

function formatDate(d: string) {
  try { return new Date(d).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" }); }
  catch { return d; }
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ReportDetailPage() {
  const params = useParams<{ ticker: string; date: string }>();
  const { ticker, date } = params;

  const [report, setReport] = useState<FullReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getReport(ticker, date);
        setReport(data);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [ticker, date]);

  const rating = report?.final_trade_decision ? extractRating(report.final_trade_decision) : "";

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Back nav */}
      <Link href="/portfolio/reports" className="text-slate-500 hover:text-sky-400 text-sm transition-colors mb-5 block">
        ← Report Library
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 font-mono">{ticker}</h1>
          <p className="text-slate-500 text-sm mt-1">{formatDate(date)}</p>
        </div>
        {rating && (
          <span className={clsx("px-4 py-1.5 rounded-lg text-sm font-bold border", ratingColor(rating))}>
            {rating}
          </span>
        )}
      </div>

      {/* Loading / error */}
      {loading && (
        <div className="text-slate-500 text-sm text-center py-20">Loading report…</div>
      )}
      {error && (
        <div className="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">{error}</div>
      )}

      {/* Report sections */}
      {report && (
        <div className="space-y-3">
          {/* Final decision — always open */}
          {report.final_trade_decision && (
            <div className="bg-slate-900 border border-sky-800/40 rounded-xl p-5">
              <h2 className="text-xs font-semibold text-sky-400 uppercase tracking-wider mb-3">Final Trade Decision</h2>
              <p className="text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">
                {report.final_trade_decision}
              </p>
            </div>
          )}

          {/* Analyst reports */}
          <ReportSection title="📊 Market Analysis"         content={report.market_report} />
          <ReportSection title="💬 Sentiment Analysis"     content={report.sentiment_report} />
          <ReportSection title="📰 News Analysis"          content={report.news_report} />
          <ReportSection title="📋 Fundamentals"           content={report.fundamentals_report} />
          <ReportSection title="💰 Valuation"              content={report.valuation_report} />
          <ReportSection title="📉 Market Technician"      content={report.market_technician_report} />
          <ReportSection title="🔢 Quantitative (Markov)"  content={report.quantitative_report} />

          {/* Debate transcripts */}
          <ReportSection
            title="⚔️ Bull vs Bear Debate"
            content={report.investment_debate_state?.history}
          />
          <ReportSection
            title="🎯 Risk Debate (Aggressive / Neutral / Conservative)"
            content={report.risk_debate_state?.history}
          />
        </div>
      )}
    </div>
  );
}
