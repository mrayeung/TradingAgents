"use client";

import { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { api, PortfolioConstructResult } from "@/lib/api";
import { usePortfolioStore, savedLabel } from "@/lib/portfolio-store";

// ─── Safe formatting helpers ─────────────────────────────────────────────────

/** Format a fraction (0–1) as a percentage string; returns "—" for null/NaN. */
function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

/** Format a decimal to `dec` places; returns "—" for null/NaN. */
function fmtFixed(v: number | null | undefined, dec = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(dec);
}

/** Colour class for a return value (null → neutral). */
function returnColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "text-slate-400";
  return v > 0 ? "text-emerald-400" : "text-red-400";
}

/** Colour class for Sharpe (null → neutral). */
function sharpeColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "text-slate-400";
  return v > 1 ? "text-emerald-400" : v > 0.5 ? "text-amber-400" : "text-red-400";
}

// ─── Ticker validation ────────────────────────────────────────────────────────

const TICKER_RE = /^[A-Z0-9][A-Z0-9.\-]{0,9}$/;

interface TickerIssue {
  ticker: string;
  kind: "warn" | "error";
  reason: string;
}

function validateTickers(tickers: string[]): TickerIssue[] {
  return tickers.flatMap<TickerIssue>(t => {
    if (t.length === 0) return [];
    if (/^\d+$/.test(t))    return [{ ticker: t, kind: "error", reason: "looks like a number, not a ticker" }];
    if (t.length === 1)      return [{ ticker: t, kind: "warn",  reason: "single-char — double-check" }];
    if (!TICKER_RE.test(t)) return [{ ticker: t, kind: "warn",  reason: "unusual characters" }];
    return [];
  });
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatCard({
  label, value, color,
}: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color ?? "text-slate-100"}`}>{value}</div>
    </div>
  );
}

const WEIGHT_COLORS = [
  "#0ea5e9","#38bdf8","#7dd3fc",
  "#34d399","#6ee7b7","#a7f3d0",
  "#fbbf24","#fcd34d","#fde68a",
  "#f87171","#fca5a5","#fecaca",
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ConstructPage() {
  const { constructInputs, patchConstructInputs, savedPortfolio, savePortfolio } = usePortfolioStore();

  const [tickerInput,  setTickerInput]  = useState(constructInputs.tickerInput);
  const [riskAversion, setRiskAversion] = useState(constructInputs.riskAversion);
  const [maxPosition,  setMaxPosition]  = useState(constructInputs.maxPosition);
  const [minPosition,  setMinPosition]  = useState(constructInputs.minPosition);
  const [lookbackDays, setLookbackDays] = useState(constructInputs.lookbackDays);

  const [result,  setResult]  = useState<PortfolioConstructResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [saved,   setSaved]   = useState(false);

  // Keep store in sync so navigating away and back restores state
  useEffect(() => {
    patchConstructInputs({ tickerInput, riskAversion, maxPosition, minPosition, lookbackDays });
  }, [tickerInput, riskAversion, maxPosition, minPosition, lookbackDays]); // eslint-disable-line react-hooks/exhaustive-deps

  const parsedTickers = tickerInput
    .split(/[\s,]+/)
    .map(t => t.trim().toUpperCase())
    .filter(Boolean);

  const tickerIssues = validateTickers(parsedTickers);
  const hasErrors    = tickerIssues.some(i => i.kind === "error");

  // Constraint guard: min must be < max
  const constraintError = minPosition >= maxPosition
    ? `Min position (${fmtPct(minPosition)}) must be less than max position (${fmtPct(maxPosition)})`
    : null;

  const canSubmit = !loading && parsedTickers.length > 0 && !hasErrors && !constraintError;

  const handleConstruct = async () => {
    if (!canSubmit) return;
    setLoading(true);
    setError(null);
    setSaved(false);
    setResult(null);
    try {
      const data = await api.construct({
        tickers: parsedTickers,
        risk_aversion: riskAversion,
        max_position: maxPosition,
        min_position: minPosition,
        lookback_days: lookbackDays,
      });

      // Guard: server returned a result but weights map is empty
      if (Object.keys(data.weights).length === 0) {
        setError(
          "No valid price data was found for the entered tickers. " +
          "Check that you used valid US equity symbols (e.g. AAPL, MSFT, NVDA)."
        );
        return;
      }

      setResult(data);
    } catch (e: unknown) {
      // Unwrap the error message from the API or network layer
      const msg = e instanceof Error ? e.message : String(e);
      // POST … → 422: {"detail": "…"} — extract the readable part after the status code
      const match = msg.match(/\d{3}: ([\s\S]+)/);
      setError(match ? match[1].replace(/^[{"]*(detail[": ]+)?/, "").replace(/["}]*$/, "").trim() : msg);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = () => {
    if (!result) return;
    savePortfolio({
      tickers: Object.keys(result.weights),
      weights: result.weights,
      savedAt: new Date().toISOString(),
      expectedReturn: result.expected_return ?? 0,
      volatility: result.volatility ?? 0,
      sharpe: result.sharpe ?? 0,
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
            Tickers <span className="text-slate-600">(comma or space separated)</span>
          </label>
          <input
            value={tickerInput}
            onChange={e => { setTickerInput(e.target.value); setError(null); }}
            onKeyDown={e => e.key === "Enter" && handleConstruct()}
            placeholder="AAPL, MSFT, GOOGL …"
            className={`w-full bg-slate-800 border rounded-lg px-3 py-2.5 text-sm text-slate-100 focus:outline-none transition-colors ${
              hasErrors
                ? "border-red-600 focus:border-red-500"
                : "border-slate-700 focus:border-sky-500"
            }`}
          />

          {/* Token chips */}
          {parsedTickers.length > 0 && (
            <div className="flex gap-1.5 mt-2 flex-wrap">
              {parsedTickers.map(t => {
                const issue = tickerIssues.find(i => i.ticker === t);
                const chipCls = !issue
                  ? "bg-slate-700 text-slate-300"
                  : issue.kind === "error"
                    ? "bg-red-900/50 text-red-300 border border-red-700/50"
                    : "bg-amber-900/50 text-amber-300 border border-amber-700/50";
                return (
                  <span key={t} className={`px-2 py-0.5 rounded text-xs ${chipCls}`} title={issue?.reason}>
                    {t}
                    {issue && (
                      <span className="ml-1 opacity-70">
                        {issue.kind === "error" ? "✕" : "⚠"}
                      </span>
                    )}
                  </span>
                );
              })}
            </div>
          )}

          {/* Per-ticker validation messages */}
          {tickerIssues.length > 0 && (
            <div className="mt-1.5 space-y-0.5">
              {tickerIssues.map(i => (
                <p key={i.ticker} className={`text-xs ${i.kind === "error" ? "text-red-400" : "text-amber-400"}`}>
                  {i.kind === "error" ? "✕" : "⚠"} <strong>{i.ticker}</strong>: {i.reason}
                </p>
              ))}
            </div>
          )}

          {/* Single-ticker hint */}
          {parsedTickers.length === 1 && tickerIssues.length === 0 && (
            <p className="text-xs text-slate-500 mt-1">
              Tip: add 2+ tickers for a meaningful portfolio optimisation.
            </p>
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
              <span className="text-slate-300">{fmtPct(maxPosition)}</span>
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
              <span className={`${constraintError ? "text-red-400" : "text-slate-300"}`}>
                {fmtPct(minPosition)}
              </span>
            </label>
            <input
              type="range" min={0.01} max={0.10} step={0.01}
              value={minPosition}
              onChange={e => setMinPosition(Number(e.target.value))}
              className={`w-full ${constraintError ? "accent-red-500" : "accent-sky-500"}`}
            />
            {constraintError && (
              <p className="text-xs text-red-400 mt-1">{constraintError}</p>
            )}
          </div>
        </div>

        {/* Run button */}
        <button
          onClick={handleConstruct}
          disabled={!canSubmit}
          title={
            hasErrors ? "Fix invalid tickers first" :
            constraintError ? constraintError :
            parsedTickers.length === 0 ? "Enter at least one ticker" : undefined
          }
          className="px-6 py-2.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg font-medium text-sm transition-colors"
        >
          {loading ? "Optimising…" : "⚖️ Construct Portfolio"}
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4 p-4 bg-red-900/30 border border-red-700 rounded-lg text-sm space-y-1">
          <p className="font-semibold text-red-300">Could not build portfolio</p>
          <p className="text-red-400/90">{error}</p>
        </div>
      )}

      {/* Partial-ticker warning */}
      {result?.invalid_tickers && result.invalid_tickers.length > 0 && (
        <div className="mb-4 p-3 bg-amber-900/20 border border-amber-700/50 rounded-lg text-xs text-amber-300">
          ⚠ No price data for <strong>{result.invalid_tickers.join(", ")}</strong> — excluded from optimisation.
          The result below uses only the valid tickers.
        </div>
      )}

      {/* Results */}
      {result && (
        <>
          {/* Stat cards + Save */}
          <div className="flex items-start gap-4 mb-6">
            <div className="grid grid-cols-3 gap-4 flex-1">
              <StatCard
                label="Expected Return (ann.)"
                value={fmtPct(result.expected_return)}
                color={returnColor(result.expected_return)}
              />
              <StatCard
                label="Portfolio Volatility"
                value={fmtPct(result.volatility)}
              />
              <StatCard
                label="Sharpe Ratio"
                value={fmtFixed(result.sharpe)}
                color={sharpeColor(result.sharpe)}
              />
            </div>

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
              <ResponsiveContainer width="100%" height={Math.max(180, barData.length * 36)}>
                <BarChart data={barData} layout="vertical">
                  <XAxis
                    type="number"
                    tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                    tick={{ fill: "#94a3b8", fontSize: 11 }}
                  />
                  <YAxis
                    type="category" dataKey="ticker" width={60}
                    tick={{ fill: "#cbd5e1", fontSize: 12 }}
                  />
                  <Tooltip
                    formatter={(v: number) => fmtPct(v)}
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
                      const blRet = result.bl_returns?.[ticker] ?? null;
                      return (
                        <tr key={ticker} className="text-slate-300">
                          <td className="py-2 font-bold text-slate-100">{ticker}</td>
                          <td className={`py-2 text-right font-mono text-xs ${returnColor(blRet)}`}>
                            {blRet != null && blRet > 0 ? "+" : ""}{fmtPct(blRet)}
                          </td>
                          <td className="py-2 text-right font-mono text-xs text-sky-400">
                            {fmtPct(weight)}
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
