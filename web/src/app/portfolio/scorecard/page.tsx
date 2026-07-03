"use client";

import { useState, useEffect, useCallback } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ScorecardMetric {
  metric: string;
  category: string;
  value: number | null;
  unit: string;
  avg_10yr: number | null;
  std_10yr: number | null;
  z_score: number | null;
  status: "OVERVALUED" | "UNDERVALUED" | "NORMAL" | "N/A";
  notes: string;
  source: string;
}

interface ScorecardData {
  updated_at: string;
  fred_available: boolean;
  warnings: string[];
  summary: {
    overvalued: number;
    normal: number;
    undervalued: number;
    na: number;
    heat_level: "EXTREME" | "ELEVATED" | "MODERATE" | "LOW";
    total: number;
  };
  metrics: ScorecardMetric[];
}

// ── Constants ─────────────────────────────────────────────────────────────────

const BACKEND = "http://localhost:8765";

const CATEGORY_ORDER = [
  "Valuation Multiples",
  "Market Technicals",
  "Credit & Macro",
  "Sentiment",
  "Economic",
  "Consumer Stress",
];

const HEAT_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  EXTREME:  { label: "🔴 EXTREME",  color: "text-red-400",    bg: "bg-red-950/60 border-red-700" },
  ELEVATED: { label: "🟠 ELEVATED", color: "text-orange-400", bg: "bg-orange-950/60 border-orange-700" },
  MODERATE: { label: "🟡 MODERATE", color: "text-amber-400",  bg: "bg-amber-950/60 border-amber-700" },
  LOW:      { label: "🟢 LOW",      color: "text-emerald-400",bg: "bg-emerald-950/60 border-emerald-700" },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v: number | null, unit: string): string {
  if (v === null) return "—";
  const n = unit === "%" ? v.toFixed(2) + "%" : unit === "x" ? v.toFixed(1) + "x"
    : unit === "idx" ? v.toFixed(1) : unit === "pts" ? v.toFixed(1)
    : v.toFixed(2);
  return n;
}

function fmtZ(z: number | null): string {
  if (z === null) return "—";
  return (z >= 0 ? "+" : "") + z.toFixed(2) + "σ";
}

function statusBadge(status: ScorecardMetric["status"]) {
  switch (status) {
    case "OVERVALUED":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold bg-red-900/70 text-red-300 border border-red-700">
          ▲ OVERVALUED
        </span>
      );
    case "UNDERVALUED":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold bg-emerald-900/70 text-emerald-300 border border-emerald-700">
          ▼ UNDERVALUED
        </span>
      );
    case "NORMAL":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-slate-800 text-slate-400 border border-slate-600">
          ● NORMAL
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-slate-900 text-slate-600 border border-slate-700">
          — N/A
        </span>
      );
  }
}

function rowBg(status: ScorecardMetric["status"], notes: string): string {
  if (notes.startsWith("★"))
    return "bg-red-950/40 border-l-2 border-red-500";
  if (status === "OVERVALUED")
    return "bg-red-950/20 border-l-2 border-red-800";
  if (status === "UNDERVALUED")
    return "bg-emerald-950/20 border-l-2 border-emerald-800";
  return "border-l-2 border-transparent";
}

function zBar(z: number | null): JSX.Element {
  if (z === null) return <div className="h-1.5 w-24 bg-slate-800 rounded" />;
  const clamped = Math.max(-3, Math.min(3, z));
  const pct = ((clamped + 3) / 6) * 100;
  const color = clamped > 1 ? "bg-red-500" : clamped < -1 ? "bg-emerald-500" : "bg-slate-400";
  return (
    <div className="relative h-1.5 w-24 bg-slate-800 rounded overflow-hidden">
      {/* Zero line */}
      <div className="absolute top-0 bottom-0 w-px bg-slate-500" style={{ left: "50%" }} />
      {/* Bar */}
      <div
        className={`absolute top-0 bottom-0 ${color} rounded`}
        style={
          clamped >= 0
            ? { left: "50%", width: `${(pct - 50)}%` }
            : { right: `${100 - 50}%`, width: `${50 - pct}%` }
        }
      />
    </div>
  );
}

// ── Summary Card ──────────────────────────────────────────────────────────────

function SummaryCard({ data }: { data: ScorecardData }) {
  const { summary, fred_available, updated_at } = data;
  const heat = HEAT_CONFIG[summary.heat_level] ?? HEAT_CONFIG.LOW;
  const updatedDate = new Date(updated_at).toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

  return (
    <div className={`rounded-xl border p-5 ${heat.bg} mb-6`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        {/* Heat gauge */}
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">
            Valuation Heat Level
          </div>
          <div className={`text-2xl font-black tracking-tight ${heat.color}`}>
            {heat.label}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {summary.overvalued} of {summary.total - summary.na} rated metrics signal overvaluation
          </div>
        </div>

        {/* Metric counts */}
        <div className="flex gap-5">
          <div className="text-center">
            <div className="text-2xl font-bold text-red-400">{summary.overvalued}</div>
            <div className="text-xs text-slate-500">Overvalued</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-slate-300">{summary.normal}</div>
            <div className="text-xs text-slate-500">Normal</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-emerald-400">{summary.undervalued}</div>
            <div className="text-xs text-slate-500">Undervalued</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-slate-600">{summary.na}</div>
            <div className="text-xs text-slate-500">N/A</div>
          </div>
        </div>

        {/* Meta */}
        <div className="text-right">
          <div className="text-xs text-slate-500">Updated</div>
          <div className="text-sm text-slate-300 font-medium">{updatedDate}</div>
          <div className="text-xs mt-1">
            {fred_available
              ? <span className="text-emerald-400">● FRED live</span>
              : <span className="text-amber-400">⚠ FRED unavailable (add FRED_API_KEY)</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Metric Table ──────────────────────────────────────────────────────────────

function MetricTable({ metrics }: { metrics: ScorecardMetric[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-800 bg-slate-900/60">
            <th className="text-left px-4 py-3 text-xs text-slate-500 font-semibold uppercase tracking-wider w-56">Metric</th>
            <th className="text-right px-4 py-3 text-xs text-slate-500 font-semibold uppercase tracking-wider">Current</th>
            <th className="text-right px-4 py-3 text-xs text-slate-500 font-semibold uppercase tracking-wider">10yr Avg</th>
            <th className="text-right px-4 py-3 text-xs text-slate-500 font-semibold uppercase tracking-wider">±1 Std</th>
            <th className="text-center px-4 py-3 text-xs text-slate-500 font-semibold uppercase tracking-wider w-32">Z-Score</th>
            <th className="text-center px-4 py-3 text-xs text-slate-500 font-semibold uppercase tracking-wider w-36">Status</th>
            <th className="text-left px-4 py-3 text-xs text-slate-500 font-semibold uppercase tracking-wider">Notes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {metrics.map((m, i) => (
            <tr key={i} className={`${rowBg(m.status, m.notes)} hover:bg-slate-800/30 transition-colors`}>
              <td className="px-4 py-3">
                <div className="font-medium text-slate-200">{m.metric}</div>
                <div className="text-xs text-slate-600 mt-0.5">{m.source}</div>
              </td>
              <td className="px-4 py-3 text-right font-mono font-semibold text-slate-100">
                {fmt(m.value, m.unit)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-slate-400">
                {fmt(m.avg_10yr, m.unit)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-slate-500 text-xs">
                {m.std_10yr !== null ? `± ${fmt(m.std_10yr, m.unit)}` : "—"}
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-col items-center gap-1">
                  <span className={`font-mono text-xs font-bold ${
                    m.z_score === null ? "text-slate-600"
                    : m.z_score > 1 ? "text-red-400"
                    : m.z_score < -1 ? "text-emerald-400"
                    : "text-slate-400"
                  }`}>
                    {fmtZ(m.z_score)}
                  </span>
                  {zBar(m.z_score)}
                </div>
              </td>
              <td className="px-4 py-3 text-center">
                {statusBadge(m.status)}
              </td>
              <td className="px-4 py-3 text-xs">
                {m.notes.startsWith("★")
                  ? <span className="text-red-300 font-semibold">{m.notes}</span>
                  : <span className="text-slate-500">{m.notes || "—"}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Category Section ──────────────────────────────────────────────────────────

function CategorySection({ category, metrics }: { category: string; metrics: ScorecardMetric[] }) {
  const n_ov = metrics.filter(m => m.status === "OVERVALUED").length;
  const n_total = metrics.filter(m => m.status !== "N/A").length;
  const pct = n_total > 0 ? Math.round((n_ov / n_total) * 100) : 0;

  return (
    <div className="mb-8">
      <div className="flex items-center gap-3 mb-3">
        <h2 className="text-sm font-bold text-slate-300 uppercase tracking-widest">{category}</h2>
        {n_total > 0 && (
          <div className="flex items-center gap-2">
            <div className="h-1.5 rounded-full bg-slate-800 w-24 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${pct >= 75 ? "bg-red-500" : pct >= 50 ? "bg-orange-500" : pct >= 25 ? "bg-amber-500" : "bg-emerald-500"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-xs text-slate-500">{n_ov}/{n_total} overvalued</span>
          </div>
        )}
      </div>
      <MetricTable metrics={metrics} />
    </div>
  );
}

// ── Z-Score Legend ────────────────────────────────────────────────────────────

function Legend() {
  return (
    <div className="flex flex-wrap gap-6 text-xs text-slate-500 mb-6 px-1">
      <div className="flex items-center gap-2">
        <span className="inline-block w-3 h-3 rounded-sm bg-red-950/40 border border-red-800" />
        <span>OVERVALUED: &gt;1σ above 10yr avg (or &lt;1σ below for inverse metrics)</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-3 h-3 rounded-sm bg-slate-800 border border-slate-600" />
        <span>NORMAL: within 1σ of 10yr avg</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-3 h-3 rounded-sm bg-emerald-950/40 border border-emerald-800" />
        <span>UNDERVALUED: &gt;1σ below 10yr avg</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-red-300 font-bold">★</span>
        <span>Extreme reading (&gt;2σ deviation)</span>
      </div>
    </div>
  );
}

// ── Warnings Panel ────────────────────────────────────────────────────────────

function WarningsPanel({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <div className="mb-5 p-3 rounded-lg bg-amber-950/30 border border-amber-800/50">
      <div className="text-xs font-semibold text-amber-400 mb-1">Data warnings ({warnings.length})</div>
      {warnings.map((w, i) => (
        <div key={i} className="text-xs text-amber-600/80">{w}</div>
      ))}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ScorecardPage() {
  const [data, setData] = useState<ScorecardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async (forceRefresh = false) => {
    if (forceRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const url = `${BACKEND}/portfolio/scorecard${forceRefresh ? "?refresh=true" : ""}`;
      const res = await fetch(url);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? "Server error");
      }
      const json: ScorecardData = await res.json();
      setData(json);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Group metrics by category, in defined order
  const grouped = data
    ? CATEGORY_ORDER.map(cat => ({
        category: cat,
        metrics: data.metrics.filter(m => m.category === cat),
      })).filter(g => g.metrics.length > 0)
    : [];

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-6 gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">
            S&amp;P 500 Valuation Scorecard
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            19 metrics vs 10-year historical averages · Z-score classification · Weekly refresh
          </p>
          <p className="text-xs text-slate-600 mt-0.5">
            Inspired by the BofA S&P 500 Valuation Scorecard
          </p>
        </div>
        <button
          onClick={() => fetchData(true)}
          disabled={refreshing || loading}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-sm text-slate-300 disabled:opacity-50 transition-colors"
        >
          <span className={refreshing ? "animate-spin" : ""}>↻</span>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex flex-col items-center justify-center py-24 gap-4">
          <div className="w-8 h-8 border-2 border-sky-500 border-t-transparent rounded-full animate-spin" />
          <div className="text-slate-500 text-sm">Fetching valuation metrics…</div>
          <div className="text-slate-600 text-xs">
            First load may take 10–20 s while pulling yfinance + FRED data
          </div>
        </div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div className="rounded-xl border border-red-800 bg-red-950/30 p-6 text-center">
          <div className="text-red-400 font-semibold mb-2">Failed to load scorecard</div>
          <div className="text-red-600 text-sm mb-4">{error}</div>
          <button
            onClick={() => fetchData()}
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-sm text-slate-300 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* Scorecard */}
      {!loading && !error && data && (
        <>
          <SummaryCard data={data} />
          <WarningsPanel warnings={data.warnings} />
          <Legend />

          {grouped.map(({ category, metrics }) => (
            <CategorySection key={category} category={category} metrics={metrics} />
          ))}

          {/* Methodology note */}
          <div className="mt-8 p-4 rounded-lg bg-slate-900/50 border border-slate-800 text-xs text-slate-600">
            <div className="font-semibold text-slate-500 mb-1">Methodology</div>
            <p>
              Each metric is classified by comparing its current reading against its 10-year rolling mean and standard deviation.
              <strong className="text-slate-500"> OVERVALUED</strong> = current &gt; (mean + 1σ) for higher-is-expensive metrics,
              or &lt; (mean − 1σ) for lower-is-expensive metrics (e.g. dividend yield, ERP, VIX).
              <strong className="text-slate-500"> ★ EXTREME</strong> flags apply at ±2σ deviations.
              Metrics without live 10yr time-series data (P/E, P/B, P/S) use published long-term historical averages.
              Scorecard is cached for 7 days; use the Refresh button to force a new pull.
            </p>
            {!data.fred_available && (
              <p className="mt-2 text-amber-600">
                ⚠ FRED_API_KEY is not set — 7 FRED-sourced metrics (credit spreads, treasury yield, consumer confidence,
                lending standards, NFCI, payrolls, Buffett indicator) show benchmark estimates only.
                Add FRED_API_KEY to your .env for live 10yr Z-scores on these series.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
