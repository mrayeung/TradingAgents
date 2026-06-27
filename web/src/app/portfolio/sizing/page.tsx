"use client";

import { useState } from "react";
import { api, SizingPosition } from "@/lib/api";
import clsx from "clsx";
import SavedPortfolioBanner from "@/components/SavedPortfolioBanner";

function pct(v: number | null) {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function SizeBar({ value, max = 0.5 }: { value: number; max?: number }) {
  const w = Math.min((value / max) * 100, 100);
  const color = w > 70 ? "bg-sky-500" : w > 40 ? "bg-emerald-500" : "bg-amber-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 bg-slate-700 rounded-full overflow-hidden">
        <div className={clsx("h-full rounded-full", color)} style={{ width: `${w}%` }} />
      </div>
      <span className="font-mono text-xs text-slate-300">{pct(value)}</span>
    </div>
  );
}

export default function SizingPage() {
  const [tickerInput, setTickerInput] = useState("");
  const [weightInput, setWeightInput] = useState("");
  const [days, setDays] = useState(90);
  const [result, setResult] = useState<SizingPosition[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [portfolioLoaded, setPortfolioLoaded] = useState(false);

  const handleLoadPortfolio = (ti: string, wi: string) => {
    setTickerInput(ti);
    setWeightInput(wi);
    setPortfolioLoaded(true);
  };

  const handleFetch = async () => {
    const tickers = tickerInput.split(/[\s,]+/).map(t => t.trim().toUpperCase()).filter(Boolean);
    const weights = weightInput.split(/[\s,]+/).map(Number).filter(n => !isNaN(n));
    if (!tickers.length) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.sizing(tickers, weights, days);
      setResult(data.positions);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Position Sizing</h1>
        <p className="text-slate-500 text-sm mt-1">
          ½-Kelly criterion · -20% penalty per high-correlation peer (|r| ≥ 0.70)
        </p>
      </div>

      {/* Saved portfolio banner */}
      <SavedPortfolioBanner onLoad={handleLoadPortfolio} loaded={portfolioLoaded} />

      {/* Controls */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-slate-400 block mb-1.5">Tickers</label>
            <input
              value={tickerInput}
              onChange={e => { setTickerInput(e.target.value); setPortfolioLoaded(false); }}
              placeholder="AAPL,MSFT,GOOGL…"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1.5">Optimised Weights (same order)</label>
            <input
              value={weightInput}
              onChange={e => { setWeightInput(e.target.value); setPortfolioLoaded(false); }}
              placeholder="0.25,0.25,0.20…"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
            />
          </div>
        </div>

        <div>
          <label className="flex justify-between text-xs text-slate-400 mb-1.5">
            <span>Correlation Look-back</span>
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
          {loading ? "Computing…" : "📐 Compute Sizing"}
        </button>
      </div>

      {/* Formula callout */}
      <div className="mb-6 bg-slate-900/60 border border-slate-800 rounded-lg p-4 text-xs text-slate-400 font-mono space-y-1">
        <div>f* = (b·p − q) / b &nbsp;·&nbsp; ½ &nbsp;·&nbsp; (1 − n_high_corr × 0.20)</div>
        <div className="text-slate-500">b = expected return &nbsp;|&nbsp; p = win probability &nbsp;|&nbsp; q = 1 − p</div>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/60">
                <th className="text-left px-4 py-3 font-medium text-slate-400">Ticker</th>
                <th className="text-right px-4 py-3 font-medium text-slate-400">Opt Weight</th>
                <th className="text-right px-4 py-3 font-medium text-slate-400">Full Kelly f*</th>
                <th className="text-right px-4 py-3 font-medium text-slate-400">½ Kelly</th>
                <th className="text-right px-4 py-3 font-medium text-slate-400">Corr Penalty</th>
                <th className="text-left px-4 py-3 font-medium text-slate-400">Final Size</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {result.map(pos => (
                <tr key={pos.ticker} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-3 font-bold text-slate-100">{pos.ticker}</td>
                  <td className="px-4 py-3 text-right font-mono text-xs text-sky-400">{pct(pos.weight)}</td>
                  <td className="px-4 py-3 text-right font-mono text-xs text-slate-300">{pct(pos.kelly_f)}</td>
                  <td className="px-4 py-3 text-right font-mono text-xs text-slate-300">{pct(pos.half_kelly)}</td>
                  <td className="px-4 py-3 text-right font-mono text-xs">
                    {pos.correlation_penalty > 0
                      ? <span className="text-orange-400">-{pct(pos.correlation_penalty)}</span>
                      : <span className="text-slate-500">—</span>
                    }
                  </td>
                  <td className="px-4 py-3">
                    <SizeBar value={pos.final_size} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
