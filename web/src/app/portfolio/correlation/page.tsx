"use client";

import { useState } from "react";
import { api, CorrelationResult } from "@/lib/api";
import clsx from "clsx";
import SavedPortfolioBanner from "@/components/SavedPortfolioBanner";

// ─── Heat-map cell colour ────────────────────────────────────────────────────
function corrColor(r: number, isIdentity: boolean): string {
  if (isIdentity) return "bg-slate-700 text-slate-300";
  const abs = Math.abs(r);
  if (abs >= 0.90) return r > 0 ? "bg-red-700 text-red-100"    : "bg-emerald-800 text-emerald-100";
  if (abs >= 0.70) return r > 0 ? "bg-red-600/70 text-red-200" : "bg-emerald-700/70 text-emerald-200";
  if (abs >= 0.50) return r > 0 ? "bg-orange-700/50 text-orange-200" : "bg-teal-700/50 text-teal-200";
  if (abs >= 0.30) return r > 0 ? "bg-amber-900/40 text-amber-300" : "bg-cyan-900/40 text-cyan-300";
  return "bg-slate-800 text-slate-400";
}

export default function CorrelationPage() {
  const [tickerInput, setTickerInput] = useState("");
  const [days, setDays] = useState(90);
  const [result, setResult] = useState<CorrelationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [portfolioLoaded, setPortfolioLoaded] = useState(false);

  // Correlation only needs tickers, not weights
  const handleLoadPortfolio = (ti: string) => {
    setTickerInput(ti);
    setPortfolioLoaded(true);
  };

  const handleFetch = async () => {
    const tickers = tickerInput.split(/[\s,]+/).map(t => t.trim().toUpperCase()).filter(Boolean);
    if (!tickers.length) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.correlation(tickers, days);
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Correlation Matrix</h1>
        <p className="text-slate-500 text-sm mt-1">
          Pairwise return correlations · red = high positive, green = high negative
        </p>
      </div>

      {/* Saved portfolio banner — only uses tickers */}
      <SavedPortfolioBanner onLoad={(ti) => handleLoadPortfolio(ti)} loaded={portfolioLoaded} />

      {/* Controls */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6 space-y-4">
        <div>
          <label className="text-xs text-slate-400 block mb-1.5">Tickers</label>
          <input
            value={tickerInput}
            onChange={e => { setTickerInput(e.target.value); setPortfolioLoaded(false); }}
            placeholder="AAPL,MSFT,GOOGL,AMZN,NVDA…"
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
          />
        </div>

        <div>
          <label className="flex justify-between text-xs text-slate-400 mb-1.5">
            <span>Look-back Days</span>
            <span className="text-slate-300">{days}d</span>
          </label>
          <input
            type="range" min={30} max={252} step={10}
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="w-full accent-sky-500"
          />
        </div>

        <button
          onClick={handleFetch}
          disabled={loading || !tickerInput.trim()}
          className="px-5 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
        >
          {loading ? "Computing…" : "🔗 Compute Correlation"}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {result && result.tickers.length > 0 && (
        <div className="space-y-6">
          {/* Heatmap */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 overflow-x-auto">
            <h2 className="text-sm font-semibold text-slate-300 mb-4">Heatmap</h2>
            <table className="text-xs border-separate border-spacing-0.5">
              <thead>
                <tr>
                  <th className="w-16" />
                  {result.tickers.map(t => (
                    <th key={t} className="px-2 pb-2 text-slate-400 font-medium text-center">
                      {t}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.matrix.map((row, i) => (
                  <tr key={result.tickers[i]}>
                    <td className="pr-2 text-slate-400 font-medium text-right">{result.tickers[i]}</td>
                    {row.map((r, j) => (
                      <td
                        key={j}
                        className={clsx(
                          "w-14 h-10 text-center rounded font-mono font-medium transition-colors",
                          corrColor(r, i === j)
                        )}
                      >
                        {i === j ? "—" : r.toFixed(2)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Legend */}
            <div className="flex gap-4 mt-4 text-xs text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded bg-red-700" /> High positive (&gt;0.9)
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded bg-emerald-700" /> High negative (&lt;-0.9)
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded bg-slate-800 border border-slate-700" /> Low correlation
              </span>
            </div>
          </div>

          {/* High-correlation pairs */}
          {result.high_pairs.length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-slate-300 mb-3">
                ⚠ High-Correlation Pairs (|r| ≥ 0.70)
              </h2>
              <p className="text-xs text-slate-500 mb-4">
                These pairs share significant co-movement. Kelly sizing will apply a -20% penalty per high-corr peer.
              </p>
              <div className="space-y-2">
                {result.high_pairs.map(pair => {
                  const abs = Math.abs(pair.r);
                  const barPct = Math.round(abs * 100);
                  return (
                    <div key={`${pair.a}-${pair.b}`} className="flex items-center gap-3">
                      <span className="text-slate-300 font-mono text-sm w-20 text-right">{pair.a}</span>
                      <span className="text-slate-600 text-xs">↔</span>
                      <span className="text-slate-300 font-mono text-sm w-20">{pair.b}</span>
                      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                        <div
                          className={clsx("h-full rounded-full", pair.r > 0 ? "bg-red-500" : "bg-emerald-500")}
                          style={{ width: `${barPct}%` }}
                        />
                      </div>
                      <span className={clsx("font-mono text-sm w-12 text-right", pair.r > 0 ? "text-red-400" : "text-emerald-400")}>
                        {pair.r.toFixed(2)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
