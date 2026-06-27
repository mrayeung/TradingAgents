"use client";

import { useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { api, BenchmarkResult } from "@/lib/api";
import SavedPortfolioBanner from "@/components/SavedPortfolioBanner";

function pct(v: number) {
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
}

function StatChip({
  label, value, base,
}: { label: string; value: number; base?: number }) {
  const color =
    base !== undefined
      ? value > base ? "text-emerald-400" : value < base ? "text-red-400" : "text-slate-300"
      : value > 0 ? "text-emerald-400" : "text-red-400";
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-xl font-bold font-mono ${color}`}>{pct(value)}</div>
    </div>
  );
}

export default function BenchmarkPage() {
  const [tickerInput, setTickerInput] = useState("");
  const [weightInput, setWeightInput] = useState("");
  const [days, setDays] = useState(90);
  const [result, setResult] = useState<BenchmarkResult | null>(null);
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
      const data = await api.benchmark(tickers, weights, days);
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  // Build combined chart data from parallel arrays
  const chartData = result
    ? result.dates.map((date, i) => ({
        date,
        Portfolio: result.portfolio_values[i] ?? null,
        SPY: result.spy_values[i] ?? null,
        QQQ: result.qqq_values[i] ?? null,
        DIA: result.dia_values[i] ?? null,
      }))
    : [];

  const tickInterval = chartData.length > 60 ? Math.ceil(chartData.length / 10) : 7;

  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Benchmark Comparison</h1>
        <p className="text-slate-500 text-sm mt-1">Portfolio performance vs SPY, QQQ, DIA · rebased to 1.0</p>
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
            <label className="text-xs text-slate-400 block mb-1.5">Weights (matching order)</label>
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
            <span>Look-back Period</span>
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
          {loading ? "Fetching…" : "📈 Compare"}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {result && (
        <>
          {/* Summary stat chips */}
          <div className="grid grid-cols-5 gap-3 mb-6">
            <StatChip label="Portfolio" value={result.summary.portfolio_return} />
            <StatChip label="SPY" value={result.summary.spy_return} base={result.summary.portfolio_return} />
            <StatChip label="QQQ" value={result.summary.qqq_return} base={result.summary.portfolio_return} />
            <StatChip label="DIA" value={result.summary.dia_return} base={result.summary.portfolio_return} />
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="text-xs text-slate-500 mb-1">Sharpe vs SPY</div>
              <div className={`text-xl font-bold font-mono ${result.summary.sharpe_vs_spy > 0 ? "text-emerald-400" : "text-red-400"}`}>
                {result.summary.sharpe_vs_spy.toFixed(2)}
              </div>
            </div>
          </div>

          {/* Line chart */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-slate-300 mb-4">Cumulative Performance (rebased to 1.0)</h2>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={chartData}>
                <XAxis
                  dataKey="date"
                  interval={tickInterval}
                  tick={{ fill: "#64748b", fontSize: 10 }}
                  tickFormatter={d => d.slice(5)}
                />
                <YAxis
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  tickFormatter={v => v.toFixed(2)}
                  width={50}
                />
                <Tooltip
                  contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                  formatter={(v: number, name: string) => [`${v.toFixed(4)} (${((v - 1) * 100).toFixed(2)}%)`, name]}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: "#94a3b8" }} />
                <Line type="monotone" dataKey="Portfolio" stroke="#0ea5e9" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="SPY" stroke="#f59e0b" dot={false} strokeWidth={1.5} strokeDasharray="4 2" />
                <Line type="monotone" dataKey="QQQ" stroke="#a78bfa" dot={false} strokeWidth={1.5} strokeDasharray="4 2" />
                <Line type="monotone" dataKey="DIA" stroke="#6ee7b7" dot={false} strokeWidth={1.5} strokeDasharray="4 2" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
