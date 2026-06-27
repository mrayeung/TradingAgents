"use client";

import { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { api, PortfolioConstructResult } from "@/lib/api";
import { usePortfolioStore, savedLabel } from "@/lib/portfolio-store";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color ?? "text-slate-100"}`}>{value}</div>
    </div>
  );
}

const WEIGHT_COLORS = [
  "#0ea5e9", "#38bdf8", "#7dd3fc",
  "#34d399", "#6ee7b7", "#a7f3d0",
  "#fbbf24", "#fcd34d", "#fde68a",
  "#f87171", "#fca5a5", "#fecaca",
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ConstructPage() {
  const { constructInputs, patchConstructInputs, savedPortfolio, savePortfolio } = usePortfolioStore();

  // Local form state — initialised from the shared store so navigating back
  // restores exactly what you had.
  const [tickerInput, setTickerInput]     = useState(constructInputs.tickerInput);
  const [riskAversion, setRiskAversion]   = useState(constructInputs.riskAversion);
  const [maxPosition, setMaxPosition]     = useState(constructInputs.maxPosition);
  const [minPosition, setMinPosition]     = useState(constructInputs.minPosition);
  const [lookbackDays, setLookbackDays]   = useState(constructInputs.lookbackDays);

  const [result, setResult]   = useState<PortfolioConstructResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [saved, setSaved]     = useState(false);   // flash state for save confirmation

  // Keep the store in sync whenever the user changes a field so that
  // navigating away and back restores the current form state.
  useEffect(() => {
    patchConstructInputs({ tickerInput, riskAversion, maxPosition, minPosition, lookbackDays });
  }, [tickerInput, riskAversion, maxPosition, minPosition, lookbackDays]); // eslint-disable-line react-hooks/exhaustive-deps

  const parsedTickers = tickerInput
    .split(/[\s,]+/)
    .map(t => t.trim().toUpperCase())
    .filter(Boolean);

  const handleConstruct = async () => {
    if (parsedTickers.length === 0) return;
    setLoading(true);
    setError(null);
    setSaved(false);
    try {
      const data = await api.construct({
        tickers: parsedTickers,
        risk_aversion: riskAversion,
        max_position: maxPosition,
        min_position: minPosition,
        lookback_days: lookbackDays,
      });
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleSave = () => {
    if (!result) return;
    savePortfolio({
      tickers: parsedTickers,
      weights: result.weights,
      savedAt: new Date().toISOString(),
      expectedReturn: result.expected_return,
      volatility: result.volatility,
      sharpe: result.sharpe,
    });
    setSaved(true);
  };

  const barData = result
    ? Object.entries(result.weights)
        .sort(([, a], [, b]) => b - a)
        .map(([ticker, weight]) => ({ ticker, weight }))
    : [];

  return (
    <div className="p-6 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Portfolio Construction</h1>
          <p className="text-slate-500 text-sm mt-1">
            Black-Litterman posterior returns → constrained mean-variance optimisation
          </p>
        </div>
        {/* Currently-saved portfolio pill */}
        {savedPortfolio && (
          <div className="text-right text-xs text-slate-400 mt-1">
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-900/30 border border-emerald-800/50 rounded-full text-emerald-400">
              ✓ Portfolio saved · {savedLabel(savedPortfolio.savedAt)}
            </span>
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 mb-6 space-y-5">
        {/* Ticker input */}
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">
            Tickers (comma or space separated)
          </label>
          <input
            value={tickerInput}
            onChange={e => setTickerInput(e.target.value)}
            placeholder="AAPL, MSFT, GOOGL …"
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
          />
          {parsedTickers.length > 0 && (
            <div className="flex gap-1.5 mt-2 flex-wrap">
              {parsedTickers.map(t => (
                <span key={t} className="px-2 py-0.5 bg-slate-700 text-slate-300 rounded text-xs">{t}</span>
              ))}
            </div>
          )}
        </div>

        {/* Sliders */}
        <div className="grid grid-cols-2 gap-6">
          <div>
            <label className="flex justify-between text-xs text-slate-400 mb-1.5">
              <span>Risk Aversion (δ)</span>
              <span className="text-slate-300">{riskAversion.toFixed(1)}</span>
            </label>
            <input
              type="range" min={0.5} max={6} step={0.5}
              value={riskAversion}
              onChange={e => setRiskAversion(Number(e.target.value))}
              className="w-full accent-sky-500"
            />
            <div className="flex justify-between text-xs text-slate-600 mt-1">
              <span>Aggressive (0.5)</span><span>Conservative (6)</span>
            </div>
          </div>

          <div>
            <label className="flex justify-between text-xs text-slate-400 mb-1.5">
              <span>Look-back Days</span>
              <span className="text-slate-300">{lookbackDays}d</span>
            </label>
            <input
              type="range" min={30} max={252} step={10}
              value={lookbackDays}
              onChange={e => setLookbackDays(Number(e.target.value))}
              className="w-full accent-sky-500"
            />
            <div className="flex justify-between text-xs text-slate-600 mt-1">
              <span>30d</span><span>252d (1yr)</span>
            </div>
          </div>

          <div>
            <label className="flex justify-between text-xs text-slate-400 mb-1.5">
              <span>Max Position</span>
              <span className="text-slate-300">{pct(maxPosition)}</span>
            </label>
            <input
              type="range" min={0.05} max={0.60} step={0.05}
              value={maxPosition}
              onChange={e => setMaxPosition(Number(e.target.value))}
              className="w-full accent-sky-500"
            />
          </div>

          <div>
            <label className="flex justify-between text-xs text-slate-400 mb-1.5">
              <span>Min Position</span>
              <span className="text-slate-300">{pct(minPosition)}</span>
            </label>
            <input
              type="range" min={0.01} max={0.10} step={0.01}
              value={minPosition}
              onChange={e => setMinPosition(Number(e.target.value))}
              className="w-full accent-sky-500"
            />
          </div>
        </div>

        {/* Run button */}
        <button
          onClick={handleConstruct}
          disabled={loading || parsedTickers.length === 0}
          className="px-6 py-2.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-lg font-medium text-sm transition-colors"
        >
          {loading ? "Optimising…" : "⚖️ Construct Portfolio"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <>
          {/* Stat cards + Save button */}
          <div className="flex items-start gap-4 mb-6">
            <div className="grid grid-cols-3 gap-4 flex-1">
              <StatCard
                label="Expected Return (ann.)"
                value={pct(result.expected_return)}
                color={result.expected_return > 0 ? "text-emerald-400" : "text-red-400"}
              />
              <StatCard label="Portfolio Volatility" value={pct(result.volatility)} />
              <StatCard
                label="Sharpe Ratio"
                value={result.sharpe.toFixed(2)}
                color={result.sharpe > 1 ? "text-emerald-400" : result.sharpe > 0.5 ? "text-amber-400" : "text-red-400"}
              />
            </div>

            {/* Save button */}
            <div className="flex flex-col items-end gap-2 mt-1 shrink-0">
              <button
                onClick={handleSave}
                className={`px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
                  saved
                    ? "bg-emerald-700 text-emerald-200 cursor-default"
                    : "bg-emerald-600 hover:bg-emerald-500 text-white"
                }`}
              >
                {saved ? "✓ Saved" : "💾 Save Portfolio"}
              </button>
              {saved && (
                <p className="text-xs text-slate-500 text-right max-w-[160px]">
                  Benchmark, Sizing &amp; Rebalance will use these weights
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Weight bar chart */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-slate-300 mb-4">Optimal Weights</h2>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={barData} layout="vertical">
                  <XAxis type="number" tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                    tick={{ fill: "#94a3b8", fontSize: 11 }} />
                  <YAxis type="category" dataKey="ticker" width={60}
                    tick={{ fill: "#cbd5e1", fontSize: 12 }} />
                  <Tooltip
                    formatter={(v: number) => pct(v)}
                    contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
                  />
                  <Bar dataKey="weight" radius={[0, 4, 4, 0]}>
                    {barData.map((_, i) => (
                      <Cell key={i} fill={WEIGHT_COLORS[i % WEIGHT_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* BL returns table */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-slate-300 mb-4">BL Posterior Returns vs Weights</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-slate-800">
                    <th className="text-left pb-2">Ticker</th>
                    <th className="text-right pb-2">BL Return</th>
                    <th className="text-right pb-2">Weight</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {Object.entries(result.weights)
                    .sort(([, a], [, b]) => b - a)
                    .map(([ticker, weight]) => {
                      const blRet = result.bl_returns[ticker] ?? 0;
                      return (
                        <tr key={ticker} className="text-slate-300">
                          <td className="py-2 font-bold text-slate-100">{ticker}</td>
                          <td className={`py-2 text-right font-mono text-xs ${blRet > 0 ? "text-emerald-400" : "text-red-400"}`}>
                            {blRet > 0 ? "+" : ""}{pct(blRet)}
                          </td>
                          <td className="py-2 text-right font-mono text-xs text-sky-400">
                            {pct(weight)}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
