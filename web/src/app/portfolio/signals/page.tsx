"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, SignalRow } from "@/lib/api";
import { usePortfolioStore, ActiveRun } from "@/lib/portfolio-store";
import clsx from "clsx";

// ─── Constants ────────────────────────────────────────────────────────────────

const ALL_ANALYSTS = [
  { key: "market",            label: "Market" },
  { key: "social",            label: "Sentiment" },
  { key: "news",              label: "News" },
  { key: "fundamentals",      label: "Fundamentals" },
  { key: "valuation",         label: "Valuation" },
  { key: "market_technician", label: "Technician" },
];

const ANALYSTS = ["market", "sentiment", "news", "fundamentals", "market_technician", "quantitative"] as const;

// ─── Helpers ─────────────────────────────────────────────────────────────────

function ratingColor(rating: string) {
  switch (rating) {
    case "Buy":         return "text-emerald-400 bg-emerald-400/10";
    case "Overweight":  return "text-teal-400 bg-teal-400/10";
    case "Hold":        return "text-amber-400 bg-amber-400/10";
    case "Underweight": return "text-orange-400 bg-orange-400/10";
    case "Sell":        return "text-red-400 bg-red-400/10";
    case "BUY":         return "text-emerald-400 bg-emerald-400/10";
    case "SELL":        return "text-red-400 bg-red-400/10";
    default:            return "text-amber-400 bg-amber-400/10";
  }
}

function verdictColor(v: string) {
  const lv = v.toLowerCase();
  if (lv.includes("significantly under")) return "text-emerald-400";
  if (lv.includes("moderately under"))   return "text-emerald-300";
  if (lv.includes("fairly"))             return "text-slate-400";
  if (lv.includes("moderately over"))    return "text-orange-400";
  if (lv.includes("significantly over")) return "text-red-400";
  return "text-slate-400";
}

function sentimentColor(s: string) {
  if (s === "bullish") return "text-emerald-400";
  if (s === "bearish") return "text-red-400";
  return "text-slate-500";
}

function ConvictionBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 bg-slate-700 rounded-full overflow-hidden">
        <div className={clsx("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-400 w-7">{pct}%</span>
    </div>
  );
}

function elapsed(ms: number) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

// ─── Debate engine options ─────────────────────────────────────────────────────

// All debate engines route through OpenRouter (single subscription, one API key).
// Model strings match the OpenRouter catalog — check GET /openrouter/models for latest IDs.
const DEBATE_ENGINES = [
  {
    key: "inherit",
    label: "Inherit (main model)",
    desc: "Debate nodes use the same model as the rest of the run",
    extra: {},
  },
  {
    key: "gemini",
    label: "⚡ Gemini 3 Flash",
    desc: "Fast & precise — ideal for live/interactive runs",
    extra: {
      debate_llm_provider: "openrouter",
      debate_llm_model: "google/gemini-flash-3",
      debate_backend_url: "https://openrouter.ai/api/v1",
    },
  },
  {
    key: "deepseek",
    label: "🔋 DeepSeek V4 Flash",
    desc: "Ultra-cheap — ideal for overnight batch sweeps",
    extra: {
      debate_llm_provider: "openrouter",
      debate_llm_model: "deepseek/deepseek-v4-flash",
      debate_backend_url: "https://openrouter.ai/api/v1",
    },
  },
] as const;

type DebateEngineKey = (typeof DEBATE_ENGINES)[number]["key"];

// ─── New Analysis Panel ───────────────────────────────────────────────────────

function NewAnalysisPanel({
  onStarted,
  onClose,
}: {
  onStarted: (run: ActiveRun) => void;
  onClose: () => void;
}) {
  const [ticker, setTicker] = useState("");
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().split("T")[0]);
  const [selectedAnalysts, setSelectedAnalysts] = useState(ALL_ANALYSTS.map(a => a.key));
  const [debateEngine, setDebateEngine] = useState<DebateEngineKey>("inherit");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleAnalyst = (key: string) => {
    setSelectedAnalysts(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
  };

  const handleStart = async () => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setLoading(true);
    setError(null);

    const engine = DEBATE_ENGINES.find(e => e.key === debateEngine)!;
    const debateExtra = debateEngine === "inherit" ? {} : engine.extra;

    try {
      const res = await api.startRun({
        ticker: t,
        trade_date: tradeDate,
        analysts: selectedAnalysts,
        ...debateExtra,
      });
      onStarted({
        runId: res.run_id,
        ticker: t,
        status: "pending",
        startedAt: Date.now(),
      });
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mb-5 bg-slate-900 border border-sky-800/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">New Analysis</h2>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-xs">✕ close</button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-slate-400 block mb-1.5">Ticker</label>
          <input
            value={ticker}
            onChange={e => setTicker(e.target.value.toUpperCase())}
            onKeyDown={e => e.key === "Enter" && handleStart()}
            placeholder="AAPL"
            autoFocus
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-slate-100 font-mono text-sm focus:outline-none focus:border-sky-500 uppercase"
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1.5">Trade Date</label>
          <input
            type="date"
            value={tradeDate}
            onChange={e => setTradeDate(e.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-sky-500"
          />
        </div>
      </div>

      <div>
        <label className="text-xs text-slate-400 block mb-2">Analysts</label>
        <div className="flex flex-wrap gap-2">
          {ALL_ANALYSTS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => toggleAnalyst(key)}
              className={clsx(
                "px-3 py-1 rounded-full text-xs font-medium transition-colors",
                selectedAnalysts.includes(key)
                  ? "bg-sky-600 text-white"
                  : "bg-slate-700 text-slate-400 hover:bg-slate-600"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Debate Engine ── */}
      <div>
        <label className="text-xs text-slate-400 block mb-2">Debate Engine</label>
        <div className="flex flex-col gap-1.5">
          {DEBATE_ENGINES.map(({ key, label, desc }) => (
            <button
              key={key}
              onClick={() => setDebateEngine(key)}
              className={clsx(
                "flex items-start gap-3 px-3 py-2.5 rounded-lg border text-left transition-colors",
                debateEngine === key
                  ? "bg-sky-900/40 border-sky-600/60 text-slate-100"
                  : "bg-slate-800/50 border-slate-700/50 text-slate-400 hover:border-slate-600"
              )}
            >
              <span className={clsx(
                "mt-0.5 w-3 h-3 rounded-full border-2 shrink-0",
                debateEngine === key ? "border-sky-400 bg-sky-400" : "border-slate-600"
              )} />
              <span>
                <span className="text-xs font-medium block">{label}</span>
                <span className="text-xs text-slate-500">{desc}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="text-red-400 text-xs bg-red-900/20 border border-red-800/40 rounded p-2">{error}</div>
      )}

      <button
        onClick={handleStart}
        disabled={loading || !ticker.trim()}
        className="px-5 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
      >
        {loading ? "Starting…" : "▶ Start Analysis"}
      </button>
      <p className="text-xs text-slate-500">
        Runs typically take 5–10 minutes. Results appear automatically when done.
      </p>
    </div>
  );
}

// ─── Active Runs Banner ───────────────────────────────────────────────────────

function ActiveRunsBanner({
  runs,
  onDismiss,
}: {
  runs: ActiveRun[];
  onDismiss: (runId: string) => void;
}) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (runs.length === 0) return null;

  return (
    <div className="mb-5 space-y-2">
      {runs.map(run => {
        const isDone = run.status === "done" || run.status === "error" || run.status === "cancelled";
        return (
          <div
            key={run.runId}
            className={clsx(
              "flex items-center gap-3 px-4 py-3 rounded-xl border text-sm",
              run.status === "done"      && "bg-emerald-900/20 border-emerald-800/40",
              run.status === "error"     && "bg-red-900/20 border-red-800/40",
              run.status === "cancelled" && "bg-slate-800 border-slate-700",
              !isDone                    && "bg-sky-900/20 border-sky-800/40"
            )}
          >
            {!isDone && (
              <span className="inline-block w-3 h-3 rounded-full bg-sky-400 animate-pulse shrink-0" />
            )}
            {run.status === "done"      && <span className="text-emerald-400 shrink-0">✓</span>}
            {run.status === "error"     && <span className="text-red-400 shrink-0">✗</span>}
            {run.status === "cancelled" && <span className="text-slate-400 shrink-0">—</span>}

            <span className="font-bold text-slate-100">{run.ticker}</span>
            <span className={clsx(
              "text-xs",
              run.status === "done"      ? "text-emerald-400" :
              run.status === "error"     ? "text-red-400"     :
              run.status === "cancelled" ? "text-slate-500"   : "text-sky-400"
            )}>
              {run.status === "pending"   ? "Queued…" :
               run.status === "warming"   ? "Warming up…" :
               run.status === "started"   ? "Analysing…" :
               run.status === "done"      ? "Complete — results updated" :
               run.status === "error"     ? "Run failed" :
               run.status === "cancelled" ? "Cancelled" : run.status}
            </span>

            <span className="text-xs text-slate-500 ml-auto">{elapsed(now - run.startedAt)}</span>

            {isDone && (
              <button
                onClick={() => onDismiss(run.runId)}
                className="text-slate-600 hover:text-slate-400 text-xs ml-2"
              >
                ✕
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function SignalsPage() {
  const { activeRuns, addRun, updateRun, dismissRun, setAllRuns } = usePortfolioStore();

  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showNewRun, setShowNewRun] = useState(false);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.signals();
      setSignals(data.signals);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Poll active runs every 8 seconds — runs are in the shared store so this
  // keeps ticking even when the user navigates away and comes back.
  useEffect(() => {
    const poll = async () => {
      const pending = activeRuns.filter(
        r => r.status !== "done" && r.status !== "error" && r.status !== "cancelled"
      );
      if (pending.length === 0) return;

      const updatedRuns = await Promise.all(
        activeRuns.map(async run => {
          if (run.status === "done" || run.status === "error" || run.status === "cancelled") return run;
          try {
            const res = await fetch(`/api/runs/${run.runId}/state`);
            if (!res.ok) return run;
            const state = await res.json();
            return { ...run, status: state.status as ActiveRun["status"] };
          } catch {
            return run;
          }
        })
      );

      // Detect transitions to "done" so we can refresh the signals table
      const justDone = updatedRuns.some((r, i) =>
        r.status === "done" && activeRuns[i]?.status !== "done"
      );
      setAllRuns(updatedRuns);
      if (justDone) load();
    };

    pollRef.current = setInterval(poll, 8000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [activeRuns, load, setAllRuns]);

  const handleRunStarted = (run: ActiveRun) => {
    addRun(run);
  };

  const handleRerun = async (ticker: string) => {
    try {
      const res = await api.startRun({
        ticker,
        trade_date: new Date().toISOString().split("T")[0],
        analysts: ALL_ANALYSTS.map(a => a.key),
      });
      addRun({
        runId: res.run_id,
        ticker,
        status: "pending",
        startedAt: Date.now(),
      });
    } catch (e: unknown) {
      alert(`Could not start run for ${ticker}: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Analyst Signals</h1>
          <p className="text-slate-500 text-sm mt-1">
            Conviction scores from saved TradingAgents reports · stale after 14 days
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowNewRun(v => !v)}
            className={clsx(
              "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
              showNewRun
                ? "bg-slate-700 text-slate-300 hover:bg-slate-600"
                : "bg-sky-600 hover:bg-sky-500 text-white"
            )}
          >
            {showNewRun ? "✕ Cancel" : "+ New Analysis"}
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-300 rounded-lg text-sm font-medium transition-colors"
          >
            {loading ? "…" : "↻ Refresh"}
          </button>
        </div>
      </div>

      {/* New analysis panel */}
      {showNewRun && (
        <NewAnalysisPanel
          onStarted={handleRunStarted}
          onClose={() => setShowNewRun(false)}
        />
      )}

      {/* Active runs — persisted in store, visible even after navigating away and back */}
      <ActiveRunsBanner runs={activeRuns} onDismiss={dismissRun} />

      {/* Error */}
      {error && (
        <div className="mb-4 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && signals.length === 0 && !error && (
        <div className="text-center py-20 text-slate-500">
          No saved reports found.{" "}
          <button onClick={() => setShowNewRun(true)} className="text-sky-400 hover:underline">
            Run your first analysis →
          </button>
        </div>
      )}

      {/* Signals table */}
      {signals.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/60">
                <th className="text-left px-4 py-3 font-medium text-slate-400">Ticker</th>
                <th className="text-left px-4 py-3 font-medium text-slate-400">Rating</th>
                <th className="text-left px-4 py-3 font-medium text-slate-400">Conviction</th>
                <th className="text-left px-4 py-3 font-medium text-slate-400">Exp. Return</th>
                <th className="text-left px-4 py-3 font-medium text-slate-400">Win Prob</th>
                <th className="text-left px-4 py-3 font-medium text-slate-400">Valuation Verdict</th>
                {ANALYSTS.map(a => (
                  <th key={a} className="text-left px-3 py-3 font-medium text-slate-400 capitalize">
                    {a.replace("_", " ")}
                  </th>
                ))}
                <th className="text-left px-4 py-3 font-medium text-slate-400">Age</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {signals.map(sig => {
                const isRunning = activeRuns.some(
                  r => r.ticker === sig.ticker &&
                       r.status !== "done" && r.status !== "error" && r.status !== "cancelled"
                );
                return (
                  <tr
                    key={sig.ticker}
                    className={clsx(
                      "hover:bg-slate-900/40 transition-colors",
                      sig.stale && !isRunning && "opacity-60",
                      isRunning && "bg-sky-900/10"
                    )}
                  >
                    <td className="px-4 py-3 font-bold text-slate-100">
                      {sig.ticker}
                      {isRunning && (
                        <span className="ml-2 inline-block w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={clsx("px-2 py-0.5 rounded-md text-xs font-bold", ratingColor(sig.rating))}>
                        {sig.rating}
                      </span>
                    </td>
                    <td className="px-4 py-3"><ConvictionBar value={sig.conviction} /></td>
                    <td className={clsx("px-4 py-3 font-mono text-sm",
                      sig.expected_return > 0 ? "text-emerald-400" : "text-red-400"
                    )}>
                      {sig.expected_return > 0 ? "+" : ""}{(sig.expected_return * 100).toFixed(1)}%
                    </td>
                    <td className="px-4 py-3 font-mono text-sm text-slate-300">
                      {(sig.win_prob * 100).toFixed(0)}%
                    </td>
                    <td className={clsx("px-4 py-3 text-xs", verdictColor(sig.analyst_verdicts.valuation))}>
                      {sig.analyst_verdicts.valuation || "—"}
                    </td>
                    {ANALYSTS.map(a => {
                      const v = sig.analyst_verdicts[a as keyof typeof sig.analyst_verdicts];
                      return (
                        <td key={a} className={clsx("px-3 py-3 text-xs", sentimentColor(v))}>
                          {v === "bullish" ? "▲" : v === "bearish" ? "▼" : "–"}
                        </td>
                      );
                    })}
                    <td className="px-4 py-3 text-xs text-slate-400 whitespace-nowrap">
                      {sig.stale
                        ? <span className="text-amber-400">⚠ {sig.age_days}d old</span>
                        : <span>{sig.age_days}d ago</span>
                      }
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleRerun(sig.ticker)}
                        disabled={isRunning}
                        className="px-2 py-1 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-slate-300 rounded text-xs transition-colors"
                      >
                        {isRunning ? "…" : "Re-run"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
