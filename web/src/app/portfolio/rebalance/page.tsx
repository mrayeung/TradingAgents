"use client";

import { useState } from "react";
import { api, RebalanceTrade } from "@/lib/api";
import clsx from "clsx";
import { usePortfolioStore, savedLabel } from "@/lib/portfolio-store";

function fmt$(v: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);
}
function pct(v: number) {
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

// ── Holdings editor ───────────────────────────────────────────────────────────

interface HoldingRow { ticker: string; weight: string }

function HoldingEditor({
  title,
  rows,
  onChange,
  badge,
}: {
  title: string;
  rows: HoldingRow[];
  onChange: (rows: HoldingRow[]) => void;
  badge?: React.ReactNode;
}) {
  const update = (i: number, field: keyof HoldingRow, val: string) => {
    const next = rows.map((r, idx) => idx === i ? { ...r, [field]: val } : r);
    onChange(next);
  };
  const add = () => onChange([...rows, { ticker: "", weight: "" }]);
  const remove = (i: number) => onChange(rows.filter((_, idx) => idx !== i));

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-300">{title}</h2>
          {badge}
        </div>
        <button onClick={add} className="text-xs text-sky-400 hover:text-sky-300">+ Add row</button>
      </div>
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div key={i} className="flex gap-2">
            <input
              value={r.ticker}
              onChange={e => update(i, "ticker", e.target.value.toUpperCase())}
              placeholder="AAPL"
              className="w-24 bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-100 font-mono focus:outline-none focus:border-sky-500 uppercase"
            />
            <input
              value={r.weight}
              onChange={e => update(i, "weight", e.target.value)}
              placeholder="0.25"
              className="flex-1 bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-100 font-mono focus:outline-none focus:border-sky-500"
            />
            <button onClick={() => remove(i)} className="text-slate-600 hover:text-red-400 text-xs px-1">✕</button>
          </div>
        ))}
      </div>
      {/* Weight sum */}
      <div className="mt-2 text-xs text-slate-500 text-right">
        Sum: {rows.reduce((acc, r) => acc + (parseFloat(r.weight) || 0), 0).toFixed(2)}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RebalancePage() {
  const { savedPortfolio } = usePortfolioStore();

  const [currentRows, setCurrentRows] = useState<HoldingRow[]>([
    { ticker: "AAPL", weight: "0.40" },
    { ticker: "MSFT", weight: "0.30" },
    { ticker: "GOOGL", weight: "0.30" },
  ]);

  const [targetRows, setTargetRows] = useState<HoldingRow[]>([
    { ticker: "AAPL", weight: "0.25" },
    { ticker: "MSFT", weight: "0.25" },
    { ticker: "GOOGL", weight: "0.20" },
    { ticker: "AMZN", weight: "0.15" },
    { ticker: "NVDA", weight: "0.15" },
  ]);
  const [targetLoaded, setTargetLoaded] = useState(false);

  const [portfolioValue, setPortfolioValue] = useState("100000");
  const [trades, setTrades] = useState<RebalanceTrade[] | null>(null);
  const [totalValue, setTotalValue] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSavedAsTarget = () => {
    if (!savedPortfolio) return;
    const rows = Object.entries(savedPortfolio.weights)
      .sort(([, a], [, b]) => b - a)
      .map(([ticker, weight]) => ({ ticker, weight: weight.toFixed(4) }));
    setTargetRows(rows);
    setTargetLoaded(true);
    setTrades(null);
  };

  const rowsToMap = (rows: HoldingRow[]) =>
    Object.fromEntries(
      rows
        .filter(r => r.ticker && r.weight)
        .map(r => [r.ticker, parseFloat(r.weight)])
    );

  const handleCompute = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.rebalance({
        current_holdings: rowsToMap(currentRows),
        target_weights: rowsToMap(targetRows),
        portfolio_value: parseFloat(portfolioValue) || 100_000,
      });
      setTrades(data.trades);
      setTotalValue(data.portfolio_value);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const buys  = trades?.filter(t => t.action === "BUY")  ?? [];
  const sells = trades?.filter(t => t.action === "SELL") ?? [];
  const totalBuy  = buys.reduce((s, t) => s + t.dollar_amount, 0);
  const totalSell = sells.reduce((s, t) => s + t.dollar_amount, 0);

  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Rebalance Plan</h1>
        <p className="text-slate-500 text-sm mt-1">
          Minimum-trade rebalance from current holdings to target weights
        </p>
      </div>

      {/* Saved portfolio action strip */}
      {savedPortfolio && (
        <div className="mb-5 flex items-center gap-3 px-4 py-3 bg-sky-900/20 border border-sky-800/50 rounded-xl text-sm">
          <span className="text-sky-400 shrink-0 text-base">📋</span>
          <div className="flex-1 min-w-0 text-slate-400 text-xs">
            Saved portfolio available · {savedLabel(savedPortfolio.savedAt)} ·{" "}
            <span className="text-slate-200">
              {Object.keys(savedPortfolio.weights).join(", ")}
            </span>
          </div>
          <button
            onClick={loadSavedAsTarget}
            className={`px-4 py-1.5 rounded-lg text-xs font-medium transition-colors shrink-0 ${
              targetLoaded
                ? "bg-emerald-800/60 text-emerald-300 cursor-default"
                : "bg-sky-600 hover:bg-sky-500 text-white"
            }`}
          >
            {targetLoaded ? "✓ Loaded as Target" : "↙ Use as Target Weights"}
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-5 mb-5">
        <HoldingEditor title="Current Holdings" rows={currentRows} onChange={rows => { setCurrentRows(rows); setTrades(null); }} />
        <HoldingEditor
          title="Target Weights"
          rows={targetRows}
          onChange={rows => { setTargetRows(rows); setTargetLoaded(false); setTrades(null); }}
          badge={
            targetLoaded
              ? <span className="text-xs text-emerald-400 bg-emerald-900/30 px-2 py-0.5 rounded-full">from saved</span>
              : undefined
          }
        />
      </div>

      {/* Portfolio value */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-5">
        <label className="text-xs text-slate-400 block mb-1.5">Portfolio Value ($)</label>
        <input
          type="number"
          value={portfolioValue}
          onChange={e => setPortfolioValue(e.target.value)}
          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-100 font-mono focus:outline-none focus:border-sky-500"
        />
      </div>

      <button
        onClick={handleCompute}
        disabled={loading}
        className="mb-6 px-5 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
      >
        {loading ? "Computing…" : "🔄 Compute Rebalance"}
      </button>

      {error && (
        <div className="mb-4 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {trades && (
        <>
          {/* Summary strip */}
          <div className="grid grid-cols-3 gap-4 mb-5">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="text-xs text-slate-500 mb-1">Portfolio Value</div>
              <div className="text-xl font-bold text-slate-100">{fmt$(totalValue)}</div>
            </div>
            <div className="bg-emerald-900/30 border border-emerald-800/50 rounded-xl p-4">
              <div className="text-xs text-emerald-500 mb-1">Total Buys</div>
              <div className="text-xl font-bold text-emerald-400">{fmt$(totalBuy)}</div>
            </div>
            <div className="bg-red-900/20 border border-red-800/40 rounded-xl p-4">
              <div className="text-xs text-red-400 mb-1">Total Sells</div>
              <div className="text-xl font-bold text-red-400">{fmt$(totalSell)}</div>
            </div>
          </div>

          {trades.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              No trades required — portfolio is already within tolerance.
            </div>
          ) : (
            <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 bg-slate-900/60">
                    <th className="text-left px-4 py-3 font-medium text-slate-400">Action</th>
                    <th className="text-left px-4 py-3 font-medium text-slate-400">Ticker</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-400">Current</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-400">Target</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-400">Delta</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-400">$ Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {trades.map(trade => (
                    <tr key={trade.ticker} className="hover:bg-slate-800/30 transition-colors">
                      <td className="px-4 py-3">
                        <span className={clsx(
                          "px-2 py-0.5 rounded text-xs font-bold",
                          trade.action === "BUY"
                            ? "bg-emerald-400/10 text-emerald-400"
                            : "bg-red-400/10 text-red-400"
                        )}>
                          {trade.action}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-bold text-slate-100">{trade.ticker}</td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-slate-400">
                        {pct(trade.current_weight)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-slate-300">
                        {pct(trade.target_weight)}
                      </td>
                      <td className={clsx(
                        "px-4 py-3 text-right font-mono text-xs",
                        trade.delta_weight > 0 ? "text-emerald-400" : "text-red-400"
                      )}>
                        {pct(trade.delta_weight)}
                      </td>
                      <td className={clsx(
                        "px-4 py-3 text-right font-mono text-sm font-medium",
                        trade.action === "BUY" ? "text-emerald-400" : "text-red-400"
                      )}>
                        {trade.action === "BUY" ? "+" : "-"}{fmt$(trade.dollar_amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
