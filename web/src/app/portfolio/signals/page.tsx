"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
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

// Debate model is configured server-side via TRADINGAGENTS_DEBATE_LLM_MODEL in .env
// (all 5 advocate nodes share a single model to avoid stylistic bias from
// role-locked assignments). No per-run selection needed in the UI.

// ─── New Analysis Panel ───────────────────────────────────────────────────────

// ─── Provider + model catalogue ───────────────────────────────────────────────
// Each provider drives llm_provider in the run config, which the backend uses
// to select the correct LLM client (OpenAI-compat, Google, NVIDIA NIM, etc.).
//
// parallelSafe = provider / model can handle 3–6 simultaneous LLM calls without
// hitting rate limits.  Free-tier and NIM free endpoints are NOT parallel-safe.

interface ModelEntry { id: string; label: string; parallelSafe: boolean; }

interface ProviderDef {
  label:           string;    // display name in the tab strip
  apiKeyEnv:       string;    // .env key the server needs
  backendUrl:      string | null;  // forwarded as backend_url (null = provider default)
  parallelDefault: boolean;   // default parallel toggle for this provider
  deepDefault:     string;    // initial deep-model selection
  quickDefault:    string;    // initial quick-model selection
  models:          ModelEntry[];
}

const PROVIDER_CATALOG: Record<string, ProviderDef> = {

  // ── OpenRouter ── (one API key covers every model family)
  openrouter: {
    label: "OpenRouter", apiKeyEnv: "OPENROUTER_API_KEY",
    backendUrl: "https://openrouter.ai/api/v1",
    parallelDefault: true,
    deepDefault:  "openai/gpt-5.6-sol-pro",
    quickDefault: "google/gemini-3.5-flash",
    models: [
      // Paid → parallel-safe (OR pool is 200+ RPM per key)
      { id: "openai/gpt-5.6-sol-pro",         label: "OpenAI  ·  GPT-5.6 Sol Pro",        parallelSafe: true },
      { id: "openai/gpt-5.6-sol",             label: "OpenAI  ·  GPT-5.6 Sol",            parallelSafe: true },
      { id: "openai/gpt-5.6-terra-pro",       label: "OpenAI  ·  GPT-5.6 Terra Pro",      parallelSafe: true },
      { id: "openai/gpt-5.6-terra",           label: "OpenAI  ·  GPT-5.6 Terra",          parallelSafe: true },
      { id: "openai/gpt-5.6-luna-pro",        label: "OpenAI  ·  GPT-5.6 Luna Pro",       parallelSafe: true },
      { id: "openai/gpt-5.6-luna",            label: "OpenAI  ·  GPT-5.6 Luna",           parallelSafe: true },
      { id: "openai/gpt-5.4-pro",             label: "OpenAI  ·  GPT-5.4 Pro",            parallelSafe: true },
      { id: "openai/gpt-5-mini",              label: "OpenAI  ·  GPT-5 Mini",             parallelSafe: true },
      { id: "anthropic/claude-opus-4.8",      label: "Anthropic  ·  Claude Opus 4.8",     parallelSafe: true },
      { id: "anthropic/claude-opus-4.8-fast", label: "Anthropic  ·  Claude Opus 4.8 Fast",parallelSafe: true },
      { id: "anthropic/claude-fable-5",       label: "Anthropic  ·  Fable 5",             parallelSafe: true },
      { id: "anthropic/claude-sonnet-5",      label: "Anthropic  ·  Claude Sonnet 5",     parallelSafe: true },
      { id: "~anthropic/claude-haiku-latest", label: "Anthropic  ·  Claude Haiku (latest)",parallelSafe: true },
      { id: "google/gemini-3.5-flash",        label: "Google  ·  Gemini 3.5 Flash",       parallelSafe: true },
      { id: "google/gemini-3.1-flash-lite",   label: "Google  ·  Gemini 3.1 Flash Lite",  parallelSafe: true },
      { id: "google/gemini-2.5-pro",          label: "Google  ·  Gemini 2.5 Pro",         parallelSafe: true },
      { id: "google/gemini-2.5-flash",        label: "Google  ·  Gemini 2.5 Flash",       parallelSafe: true },
      { id: "deepseek/deepseek-v4-pro",       label: "DeepSeek  ·  V4 Pro",               parallelSafe: true },
      { id: "deepseek/deepseek-v4-flash",     label: "DeepSeek  ·  V4 Flash",             parallelSafe: true },
      { id: "moonshotai/kimi-k3",             label: "Moonshot  ·  Kimi K3",              parallelSafe: true },
      { id: "moonshotai/kimi-k2.7-code",      label: "Moonshot  ·  Kimi K2.7 Code",       parallelSafe: true },
      { id: "meta-llama/llama-3.1-405b-instruct", label: "Meta  ·  Llama 3.1 405B",       parallelSafe: true },
      { id: "meta-llama/llama-4-scout",       label: "Meta  ·  Llama 4 Scout",            parallelSafe: true },
      // Free tier → sequential only (10–20 RPM, no credits consumed)
      { id: "deepseek/deepseek-r1:free",      label: "DeepSeek  ·  R1 (free) ⚠",         parallelSafe: false },
    ],
  },

  // ── OpenAI Direct ── (OPENAI_API_KEY; 3 500+ RPM — always parallel-safe)
  openai: {
    label: "OpenAI Direct", apiKeyEnv: "OPENAI_API_KEY",
    backendUrl: null,
    parallelDefault: true,
    deepDefault:  "gpt-4o",
    quickDefault: "gpt-4o-mini",
    models: [
      { id: "gpt-4o",        label: "GPT-4o",          parallelSafe: true },
      { id: "gpt-4o-mini",   label: "GPT-4o Mini",     parallelSafe: true },
      { id: "gpt-4.1",       label: "GPT-4.1",         parallelSafe: true },
      { id: "gpt-4.1-mini",  label: "GPT-4.1 Mini",    parallelSafe: true },
      { id: "o3",            label: "o3 (reasoning)",   parallelSafe: true },
      { id: "o4-mini",       label: "o4-mini (reasoning)", parallelSafe: true },
    ],
  },

  // ── Google Direct ── (GOOGLE_API_KEY; paid Flash ≥ 1 000 RPM → parallel-safe)
  google: {
    label: "Google Direct", apiKeyEnv: "GOOGLE_API_KEY",
    backendUrl: null,
    parallelDefault: true,
    deepDefault:  "gemini-2.5-pro",
    quickDefault: "gemini-2.5-flash",
    models: [
      { id: "gemini-2.5-pro",          label: "Gemini 2.5 Pro (paid)",             parallelSafe: true  },
      { id: "gemini-2.5-flash",        label: "Gemini 2.5 Flash (paid)",           parallelSafe: true  },
      { id: "gemini-2.0-flash-exp",    label: "Gemini 2.0 Flash Exp (free ⚠)",     parallelSafe: false },
      { id: "gemini-1.5-flash",        label: "Gemini 1.5 Flash (paid)",           parallelSafe: true  },
      { id: "gemini-1.5-flash-8b",     label: "Gemini 1.5 Flash-8B (free tier ⚠)", parallelSafe: false },
    ],
  },

  // ── NVIDIA NIM ── (NVIDIA_NIM_API_KEY; free-tier ~5 RPM → sequential only)
  nvidia_nim: {
    label: "NVIDIA NIM", apiKeyEnv: "NVIDIA_NIM_API_KEY",
    backendUrl: null,   // backend registry sets https://integrate.api.nvidia.com/v1
    parallelDefault: false,
    deepDefault:  "meta-llama/llama-3.1-405b-instruct",
    quickDefault: "meta-llama/llama-3.1-70b-instruct",
    models: [
      { id: "meta-llama/llama-3.1-405b-instruct", label: "Llama 3.1 405B",          parallelSafe: false },
      { id: "meta-llama/llama-3.1-70b-instruct",  label: "Llama 3.1 70B",           parallelSafe: false },
      { id: "meta-llama/llama-4-scout",            label: "Llama 4 Scout",           parallelSafe: false },
      { id: "deepseek-ai/deepseek-v4-flash",       label: "DeepSeek V4 Flash",       parallelSafe: false },
      { id: "deepseek-ai/deepseek-v4-pro",         label: "DeepSeek V4 Pro",         parallelSafe: false },
    ],
  },

} as const;

type ProviderId = keyof typeof PROVIDER_CATALOG;

const MAX_TICKERS = 6;

// Parse raw input → deduplicated uppercase tickers, capped at MAX_TICKERS
function parseTickers(raw: string): string[] {
  return [
    ...new Set(
      raw.split(/[,\s]+/)
        .map(t => t.trim().toUpperCase())
        .filter(t => t.length > 0)
    ),
  ].slice(0, MAX_TICKERS);
}

function NewAnalysisPanel({
  onStarted,
  onClose,
}: {
  onStarted: (run: ActiveRun) => void;
  onClose: () => void;
}) {
  const [tickerInput, setTickerInput] = useState("");
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().split("T")[0]);
  const [selectedAnalysts, setSelectedAnalysts] = useState(ALL_ANALYSTS.map(a => a.key));
  // Both models route through OpenRouter (OPENROUTER_API_KEY)
  const [llmProvider, setLlmProvider] = useState<ProviderId>("openrouter");
  const [deepModel,  setDeepModel]  = useState(PROVIDER_CATALOG.openrouter.deepDefault);
  const [quickModel, setQuickModel] = useState(PROVIDER_CATALOG.openrouter.quickDefault);
  const [debateMode, setDebateMode] = useState<"5" | "3">("5");
  const [parallelAnalysts, setParallelAnalysts] = useState(true);
  // Track whether the user manually overrode the auto-sync; if so don't override again
  // until they switch provider (which resets intent).
  const parallelUserOverride = useRef(false);

  // Auto-sync parallel toggle when provider or model selection changes.
  useEffect(() => {
    if (parallelUserOverride.current) return;
    const prov = PROVIDER_CATALOG[llmProvider];
    const deepSafe  = prov.models.find(m => m.id === deepModel)?.parallelSafe  ?? prov.parallelDefault;
    const quickSafe = prov.models.find(m => m.id === quickModel)?.parallelSafe ?? prov.parallelDefault;
    setParallelAnalysts(deepSafe && quickSafe);
  }, [deepModel, quickModel, llmProvider]);
  const [loading, setLoading] = useState(false);
  const [startedCount, setStartedCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const tickers = parseTickers(tickerInput);
  const atMax = tickers.length >= MAX_TICKERS;

  const removeTicker = (t: string) => {
    setTickerInput(tickers.filter(x => x !== t).join(", "));
  };

  const toggleAnalyst = (key: string) => {
    setSelectedAnalysts(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
  };

  // Queue all tickers as separate runs — backend serialises via max_workers=1
  const handleStart = async () => {
    if (tickers.length === 0) return;
    setLoading(true);
    setStartedCount(0);
    setError(null);
    const provDef = PROVIDER_CATALOG[llmProvider];
    const baseConfig: Record<string, unknown> = {
      trade_date: tradeDate,
      analysts: selectedAnalysts,
      llm_provider: llmProvider,
      deep_think_llm: deepModel,
      quick_think_llm: quickModel,
      debate_mode: debateMode,
      parallel_analysts: parallelAnalysts,
    };
    // backend_url is only sent when the provider needs an explicit override;
    // null means "use the provider registry default" (OpenAI, Google, NIM all
    // have their endpoints hardcoded in the client registry).
    if (provDef.backendUrl != null) {
      baseConfig.backend_url = provDef.backendUrl;
    }
    try {
      for (const t of tickers) {
        const res = await api.startRun({ ...baseConfig, ticker: t });
        onStarted({ runId: res.run_id, ticker: t, status: "pending", startedAt: Date.now() });
        setStartedCount(n => n + 1);
      }
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
        {/* ── Multi-ticker input ── */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-slate-400">Tickers</label>
            <span className={clsx(
              "text-[10px] font-mono font-bold tabular-nums",
              atMax ? "text-amber-400" : tickers.length > 0 ? "text-sky-400" : "text-slate-600"
            )}>
              {tickers.length} / {MAX_TICKERS}
            </span>
          </div>
          <input
            value={tickerInput}
            onChange={e => {
              const val = e.target.value.toUpperCase();
              if (parseTickers(val).length <= MAX_TICKERS) setTickerInput(val);
            }}
            onKeyDown={e => e.key === "Enter" && handleStart()}
            placeholder="AAPL, MSFT, NVDA, GOOGL …"
            autoFocus
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-slate-100 font-mono text-sm focus:outline-none focus:border-sky-500 uppercase placeholder:normal-case placeholder:text-slate-600"
          />
          <p className="text-[10px] text-slate-600 mt-1">
            Comma-separated · max {MAX_TICKERS} · runs queue serially (~5–10 min each)
          </p>
          {/* Parsed ticker pills */}
          {tickers.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {tickers.map(t => (
                <span key={t}
                  className="inline-flex items-center gap-1 px-2 py-0.5 bg-sky-900/50 border border-sky-700/50 rounded text-xs font-mono text-sky-300"
                >
                  {t}
                  <button onClick={() => removeTicker(t)}
                    className="text-sky-600 hover:text-sky-300 leading-none ml-0.5" title={`Remove ${t}`}
                  >×</button>
                </span>
              ))}
            </div>
          )}
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

      {/* ── Provider + Model Selection ── */}
      <div className="space-y-3">
        {/* Provider tab strip */}
        <div>
          <label className="text-xs text-slate-400 block mb-2">Provider</label>
          <div className="flex flex-wrap gap-1.5">
            {(Object.entries(PROVIDER_CATALOG) as [ProviderId, ProviderDef][]).map(([key, prov]) => (
              <button
                key={key}
                onClick={() => {
                  parallelUserOverride.current = false;   // reset override on provider switch
                  setLlmProvider(key);
                  setDeepModel(prov.deepDefault);
                  setQuickModel(prov.quickDefault);
                }}
                className={clsx(
                  "px-3 py-1 rounded-lg text-xs font-medium transition-colors",
                  llmProvider === key
                    ? "bg-sky-700 text-white"
                    : "bg-slate-700 text-slate-400 hover:bg-slate-600"
                )}
              >
                {prov.label}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-slate-600 mt-1">
            Needs <code className="text-sky-500">{PROVIDER_CATALOG[llmProvider].apiKeyEnv}</code> in your <code className="text-sky-500">.env</code>
            {llmProvider === "nvidia_nim" && " · free-tier models: ~5 RPM → use Sequential mode"}
          </p>
        </div>

        {/* Deep + Quick model dropdowns, filtered to the active provider */}
        <div className="grid grid-cols-2 gap-3">
          {(["deep", "quick"] as const).map(role => {
            const isDeep   = role === "deep";
            const value    = isDeep ? deepModel : quickModel;
            const onChange = isDeep
              ? (id: string) => setDeepModel(id)
              : (id: string) => setQuickModel(id);
            const models   = PROVIDER_CATALOG[llmProvider].models;
            const safeModels = models.filter(m => m.parallelSafe);
            const slowModels = models.filter(m => !m.parallelSafe);

            return (
              <div key={role}>
                <label className="text-xs text-slate-500 block mb-1.5">
                  {isDeep ? "🧠 Deep reasoning" : "⚡ Quick think"}
                  <span className="text-slate-600 ml-1 font-normal">
                    {isDeep ? "(analysts · manager)" : "(tools · debate)"}
                  </span>
                </label>
                <select
                  value={value}
                  onChange={e => onChange(e.target.value)}
                  className={clsx(
                    "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono focus:outline-none cursor-pointer",
                    isDeep ? "text-violet-300 focus:border-violet-500" : "text-sky-300 focus:border-sky-500"
                  )}
                >
                  {safeModels.length > 0 && slowModels.length > 0 ? (
                    <>
                      <optgroup label="⚡ Parallel-safe">
                        {safeModels.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                      </optgroup>
                      <optgroup label="🔁 Sequential only">
                        {slowModels.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                      </optgroup>
                    </>
                  ) : (
                    models.map(m => <option key={m.id} value={m.id}>{m.label}</option>)
                  )}
                </select>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Advocate Mode ── */}
      <div>
        <label className="text-xs text-slate-400 block mb-2">Advocate Mode</label>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setDebateMode("5")}
            className={clsx(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
              debateMode === "5"
                ? "bg-violet-700 text-white"
                : "bg-slate-700 text-slate-400 hover:bg-slate-600"
            )}
          >
            ⚔️ 5 Advocates
            <span className="ml-1.5 font-normal opacity-70">Bull · Bear · Agg · Con · Neutral</span>
          </button>
          <button
            onClick={() => setDebateMode("3")}
            className={clsx(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
              debateMode === "3"
                ? "bg-violet-700 text-white"
                : "bg-slate-700 text-slate-400 hover:bg-slate-600"
            )}
          >
            ⚡ 3 Advocates
            <span className="ml-1.5 font-normal opacity-70">Bull · Bear · Neutral</span>
          </button>
        </div>
        <p className="text-[10px] text-slate-600 mt-1.5">
          {debateMode === "3"
            ? "Skips Aggressive & Conservative risk analysts — ~40% fewer tokens, modest quality trade-off"
            : "Full risk debate across all 3 risk advocates — highest quality, more tokens"}
        </p>
      </div>

      {/* ── Analyst Execution Mode ── */}
      <div>
        <label className="text-xs text-slate-400 block mb-2">Analyst Execution</label>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { parallelUserOverride.current = true; setParallelAnalysts(true); }}
            className={clsx(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
              parallelAnalysts
                ? "bg-emerald-700 text-white"
                : "bg-slate-700 text-slate-400 hover:bg-slate-600"
            )}
          >
            ⚡ Parallel
            <span className="ml-1.5 font-normal opacity-70">All analysts at once</span>
          </button>
          <button
            onClick={() => { parallelUserOverride.current = true; setParallelAnalysts(false); }}
            className={clsx(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
              !parallelAnalysts
                ? "bg-emerald-700 text-white"
                : "bg-slate-700 text-slate-400 hover:bg-slate-600"
            )}
          >
            🔁 Sequential
            <span className="ml-1.5 font-normal opacity-70">One at a time</span>
          </button>
        </div>
        <p className="text-[10px] text-slate-600 mt-1.5">
          {parallelAnalysts
            ? "Analysts run concurrently — ~3× faster. Use with paid API tiers (OpenAI, Gemini, OpenRouter paid)."
            : "Analysts run one at a time — safer for low-RPM providers (NVIDIA NIM free, local Ollama)."}
        </p>
      </div>

      {/* ── Debate model — server-configured, shown read-only ── */}
      <div className="flex items-center gap-2 px-3 py-2 bg-slate-800/40 border border-slate-700/50 rounded-lg">
        <span className="text-xs text-slate-500">⚡ Debate model</span>
        <span className="text-xs font-mono text-slate-300 ml-1">
          set via <code className="text-sky-400">TRADINGAGENTS_DEBATE_LLM_MODEL</code>
        </span>
        <span className="text-xs text-slate-500 ml-auto">
          {debateMode === "3" ? "3" : "5"} advocate nodes share one model
        </span>
      </div>

      {error && (
        <div className="text-red-400 text-xs bg-red-900/20 border border-red-800/40 rounded p-2">{error}</div>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={handleStart}
          disabled={loading || tickers.length === 0}
          className="px-5 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
        >
          {loading
            ? `Queuing ${startedCount}/${tickers.length}…`
            : tickers.length > 1
              ? `▶ Start ${tickers.length} Analyses`
              : "▶ Start Analysis"}
        </button>
        {tickers.length > 1 && !loading && (
          <p className="text-[10px] text-slate-500">
            Est. {tickers.length * 5}–{tickers.length * 10} min total · runs are serialised
          </p>
        )}
      </div>
      <p className="text-xs text-slate-500">
        Each run takes ~5–10 min. Results appear in the signals table as each completes.
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
               run.status === "queued"    ? "Queued — waiting for active run" :
               run.status === "warming"   ? "Warming up…" :
               run.status === "started"   ? "Analysing…" :
               run.status === "done"      ? "Complete — results updated" :
               run.status === "error"     ? `Run failed${run.errorMessage ? `: ${run.errorMessage}` : ""}` :
               run.status === "cancelled" ? "Cancelled" : run.status}
            </span>

            {/* Show final duration for completed runs, live clock while running */}
            <span className="text-xs text-slate-500 ml-auto">
              {isDone && run.completedAt
                ? `⏱ ${elapsed(run.completedAt - run.startedAt)}`
                : elapsed(now - run.startedAt)}
            </span>

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
            const nowDone = (state.status === "done" || state.status === "error") && run.status !== state.status;
            return {
              ...run,
              status: state.status as ActiveRun["status"],
              ...(state.error_message && { errorMessage: state.error_message }),
              ...(nowDone && !run.completedAt && { completedAt: Date.now() }),
            };
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
                <th className="text-left px-4 py-3 font-medium text-slate-400">Report</th>
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
                      {sig.date ? (
                        <Link
                          href={`/portfolio/reports/${sig.ticker}/${sig.date}`}
                          className="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-sky-600 text-sky-400 hover:text-sky-300 rounded text-xs transition-colors whitespace-nowrap"
                        >
                          📄 View
                        </Link>
                      ) : (
                        <span className="text-slate-600 text-xs">—</span>
                      )}
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
