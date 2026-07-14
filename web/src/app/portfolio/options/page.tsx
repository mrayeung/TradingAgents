"use client";

import { useState, useEffect, useCallback } from "react";

const API = "http://localhost:8765";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TradeIdea {
  strategy: string;
  direction: string;
  ivRegime: string;
  ivRvRatio: number;
  expiry: string;
  dte: number;
  legs: string[];
  rationale: string;
  probProfit: string;
  maxProfit: string;
  maxLoss: string;
}

interface OptionRow {
  strike: number;
  bid: number;
  ask: number;
  mid: number;
  iv: number;
  volume: number;
  oi: number;
}

interface UnusualEntry {
  type: "CALL" | "PUT";
  strike: number;
  expiry: string;
  iv: number;
  volume: number;
  openInterest: number;
  uaRatio: number;
  bid: number;
  ask: number;
  mid: number;
}

interface ExpiryData {
  expiry: string;
  dte: number;
  atmIV: number | null;
  atmIVPct: string;
  expectedMove: number | null;
  expectedMovePct: number | null;
  pcrVolume: number | null;
  pcrOI: number | null;
  callVolume: number;
  putVolume: number;
  callOI: number;
  putOI: number;
  unusualActivity: UnusualEntry[];
  calls: OptionRow[];
  puts: OptionRow[];
  tradeIdeas?: TradeIdea[];
  error?: string;
}

interface OptionsData {
  ticker: string;
  currentPrice: number | null;
  rv30d: number | null;
  rv30dPct: string;
  ivRvRatio: number | null;
  ivRegime: "high" | "normal" | "low";
  expirations: ExpiryData[];
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtPrice(n: number | null | undefined) {
  return n == null ? "—" : `$${n.toFixed(2)}`;
}
function fmtPct(n: number | null | undefined) {
  return n == null ? "—" : `${(n * 100).toFixed(1)}%`;
}
function fmtVol(n: number | null | undefined) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toString();
}

// ── IV Regime badge ───────────────────────────────────────────────────────────

function IVRegimeBadge({ regime }: { regime: string }) {
  const map: Record<string, string> = {
    high:   "bg-rose-400/10 border-rose-400/25 text-rose-400",
    normal: "bg-amber-400/10 border-amber-400/25 text-amber-400",
    low:    "bg-emerald-400/10 border-emerald-400/25 text-emerald-400",
  };
  const label: Record<string, string> = {
    high: "IV Rich", normal: "IV Normal", low: "IV Cheap"
  };
  return (
    <span className={`text-xs px-2.5 py-0.5 rounded-full border font-semibold ${map[regime] ?? map.normal}`}>
      {label[regime] ?? regime}
    </span>
  );
}

// ── Trade idea card ───────────────────────────────────────────────────────────

const DIRECTION_COLOR: Record<string, string> = {
  bullish: "text-emerald-400",
  bearish: "text-rose-400",
  neutral: "text-slate-400",
};

function TradeIdeaCard({ idea }: { idea: TradeIdea }) {
  const dirColor =
    DIRECTION_COLOR[idea.direction.toLowerCase().split("/")[0].trim()] ??
    "text-slate-400";

  const stratIcon: Record<string, string> = {
    "Iron Condor": "🦅",
    "Cash-Secured Put": "🏦",
    "Covered Call": "📞",
    "Bull Call Spread": "↗",
    "Bear Put Spread": "↘",
    "Long Straddle": "⇔",
    "Short Strangle": "🤏",
    "Put Credit Spread": "🔻",
  };
  const icon = stratIcon[idea.strategy] ?? "📋";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl">{icon}</span>
            <span className="font-semibold text-slate-100 text-sm">{idea.strategy}</span>
          </div>
          <p className={`text-xs mt-0.5 font-medium ${dirColor}`}>{idea.direction}</p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-slate-500">P(profit)</p>
          <p className="text-sm font-bold text-emerald-400">{idea.probProfit}</p>
        </div>
      </div>

      {/* Legs */}
      <div className="bg-slate-800 rounded-lg p-2.5 space-y-1">
        {idea.legs.map((leg, i) => (
          <p key={i} className="text-xs font-mono text-sky-300">{leg}</p>
        ))}
        <p className="text-xs text-slate-500 mt-1">{idea.expiry} · {idea.dte}d to expiry</p>
      </div>

      {/* Rationale */}
      <p className="text-xs text-slate-400 leading-relaxed">{idea.rationale}</p>

      {/* P&L summary */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-emerald-400/5 border border-emerald-400/15 rounded-lg p-2">
          <p className="text-emerald-500 font-medium mb-0.5">Max Profit</p>
          <p className="text-slate-300">{idea.maxProfit}</p>
        </div>
        <div className="bg-rose-400/5 border border-rose-400/15 rounded-lg p-2">
          <p className="text-rose-500 font-medium mb-0.5">Max Loss</p>
          <p className="text-slate-300">{idea.maxLoss}</p>
        </div>
      </div>
    </div>
  );
}

// ── Expected move card ────────────────────────────────────────────────────────

function ExpectedMoveCard({ exp, price }: { exp: ExpiryData; price: number | null }) {
  if (exp.error) return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 text-xs text-slate-600 italic">
      {exp.expiry} — {exp.error}
    </div>
  );

  const upper = price != null && exp.expectedMove != null ? price + exp.expectedMove : null;
  const lower = price != null && exp.expectedMove != null ? price - exp.expectedMove : null;

  // P/C sentiment
  const pcr = exp.pcrVolume;
  const pcrLabel = pcr == null ? "—" : pcr < 0.7 ? "Bullish" : pcr > 1.2 ? "Bearish" : "Neutral";
  const pcrColor = pcr == null ? "text-slate-500"
    : pcr < 0.7 ? "text-emerald-400"
    : pcr > 1.2 ? "text-rose-400"
    : "text-amber-400";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-sm font-semibold text-slate-200">{exp.expiry}</p>
          <p className="text-xs text-slate-500">{exp.dte} days to expiry</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-500">ATM IV</p>
          <p className="text-sm font-bold text-slate-200">{exp.atmIVPct}</p>
        </div>
      </div>

      {/* Expected move range */}
      <div className="bg-slate-800 rounded-lg p-3 mb-3">
        <p className="text-xs text-slate-500 mb-2">Expected Move (±1σ)</p>
        <div className="flex items-center justify-between">
          <div className="text-center">
            <p className="text-xs text-rose-400 font-medium">Low</p>
            <p className="text-sm font-bold text-slate-200">{fmtPrice(lower)}</p>
          </div>
          <div className="flex-1 mx-2">
            {/* Price bar */}
            <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-rose-500/50 via-sky-500 to-emerald-500/50 rounded-full" />
            </div>
            <p className="text-center text-[10px] text-slate-500 mt-1">
              ±{fmtPrice(exp.expectedMove)} · ±{fmtPct(exp.expectedMovePct)}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-emerald-400 font-medium">High</p>
            <p className="text-sm font-bold text-slate-200">{fmtPrice(upper)}</p>
          </div>
        </div>
      </div>

      {/* P/C & volume */}
      <div className="grid grid-cols-3 gap-2 text-center text-xs">
        <div>
          <p className="text-slate-500">P/C Vol</p>
          <p className={`font-semibold ${pcrColor}`}>{pcr?.toFixed(2) ?? "—"}</p>
          <p className={`text-[10px] ${pcrColor}`}>{pcrLabel}</p>
        </div>
        <div>
          <p className="text-slate-500">Call Vol</p>
          <p className="text-slate-200 font-semibold">{fmtVol(exp.callVolume)}</p>
        </div>
        <div>
          <p className="text-slate-500">Put Vol</p>
          <p className="text-slate-200 font-semibold">{fmtVol(exp.putVolume)}</p>
        </div>
      </div>
    </div>
  );
}

// ── Options chain mini-table ──────────────────────────────────────────────────

function ChainTable({ exp, price }: { exp: ExpiryData; price: number | null }) {
  const [open, setOpen] = useState(false);
  if (exp.error) return null;
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-300 hover:bg-slate-800 transition-colors"
      >
        <span>{exp.expiry} · Chain (±15% ATM)</span>
        <span className="text-slate-600">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-y border-slate-800 text-slate-500 bg-slate-800/50">
                <th colSpan={4} className="text-left px-3 py-2 text-sky-400 font-medium">CALLS</th>
                <th className="px-3 py-2 text-center font-medium text-slate-400">Strike</th>
                <th colSpan={4} className="text-right px-3 py-2 text-rose-400 font-medium">PUTS</th>
              </tr>
              <tr className="border-b border-slate-800 text-slate-600">
                <th className="text-left px-3 py-1.5">Bid</th>
                <th className="text-left px-2 py-1.5">Ask</th>
                <th className="text-left px-2 py-1.5">Vol</th>
                <th className="text-left px-2 py-1.5">IV</th>
                <th className="px-3 py-1.5 text-center font-semibold text-slate-400">—</th>
                <th className="text-right px-2 py-1.5">IV</th>
                <th className="text-right px-2 py-1.5">Vol</th>
                <th className="text-right px-2 py-1.5">Ask</th>
                <th className="text-right px-3 py-1.5">Bid</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {exp.calls.map((call, i) => {
                const put  = exp.puts.find((p) => p.strike === call.strike);
                const isAtm = price != null && Math.abs(call.strike - price) < 2.6;
                return (
                  <tr key={i} className={`${isAtm ? "bg-sky-500/5" : "hover:bg-slate-800/30"} transition-colors`}>
                    <td className="px-3 py-2 text-emerald-400">{fmtPrice(call.bid)}</td>
                    <td className="px-2 py-2 text-slate-300">{fmtPrice(call.ask)}</td>
                    <td className="px-2 py-2 text-slate-500">{fmtVol(call.volume)}</td>
                    <td className="px-2 py-2 text-slate-400">{fmtPct(call.iv)}</td>
                    <td className={`px-3 py-2 text-center font-mono font-semibold ${isAtm ? "text-sky-400" : "text-slate-300"}`}>
                      {fmtPrice(call.strike)}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-400">{put ? fmtPct(put.iv) : "—"}</td>
                    <td className="px-2 py-2 text-right text-slate-500">{put ? fmtVol(put.volume) : "—"}</td>
                    <td className="px-2 py-2 text-right text-slate-300">{put ? fmtPrice(put.ask) : "—"}</td>
                    <td className="px-3 py-2 text-right text-rose-400">{put ? fmtPrice(put.bid) : "—"}</td>
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

// ── Unusual activity table ────────────────────────────────────────────────────

function UnusualActivity({ entries }: { entries: UnusualEntry[] }) {
  if (entries.length === 0) return (
    <p className="text-xs text-slate-600 italic">No unusual activity detected for this expiry</p>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-800 text-slate-500">
            <th className="text-left px-3 py-2">Type</th>
            <th className="text-right px-3 py-2">Strike</th>
            <th className="text-left px-3 py-2">Expiry</th>
            <th className="text-right px-3 py-2">Volume</th>
            <th className="text-right px-3 py-2">OI</th>
            <th className="text-right px-3 py-2">Vol/OI</th>
            <th className="text-right px-3 py-2">Mid</th>
            <th className="text-right px-3 py-2">IV</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {entries.map((e, i) => (
            <tr key={i} className="hover:bg-slate-800/30">
              <td className="px-3 py-2">
                <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
                  e.type === "CALL"
                    ? "bg-emerald-400/10 text-emerald-400"
                    : "bg-rose-400/10 text-rose-400"
                }`}>{e.type}</span>
              </td>
              <td className="px-3 py-2 text-right font-mono text-slate-200">{fmtPrice(e.strike)}</td>
              <td className="px-3 py-2 text-slate-400">{e.expiry}</td>
              <td className="px-3 py-2 text-right font-semibold text-slate-200">{fmtVol(e.volume)}</td>
              <td className="px-3 py-2 text-right text-slate-500">{fmtVol(e.openInterest)}</td>
              <td className={`px-3 py-2 text-right font-semibold ${e.uaRatio >= 5 ? "text-amber-400" : "text-slate-300"}`}>
                {e.uaRatio?.toFixed(1) ?? "—"}×
              </td>
              <td className="px-3 py-2 text-right text-slate-300">{fmtPrice(e.mid)}</td>
              <td className="px-3 py-2 text-right text-slate-400">{fmtPct(e.iv)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OptionsPage() {
  const [tickerInput, setTickerInput] = useState("AAPL");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<OptionsData | null>(null);
  const [selectedExpiry, setSelectedExpiry] = useState(0);

  const fetchOptions = useCallback(async (ticker: string) => {
    setLoading(true);
    setError(null);
    setData(null);
    setSelectedExpiry(0);
    try {
      const res = await fetch(`${API}/options/${ticker.trim().toUpperCase()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail ?? "Unknown error");
      }
      const json: OptionsData = await res.json();
      setData(json);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOptions("AAPL");
  }, [fetchOptions]);

  const validExps = data?.expirations.filter((e) => !e.error) ?? [];
  const activeExp = validExps[selectedExpiry] ?? validExps[0];
  const allUnusual = (data?.expirations ?? [])
    .filter((e) => !e.error)
    .flatMap((e) => e.unusualActivity ?? [])
    .sort((a, b) => b.volume - a.volume)
    .slice(0, 20);

  const ideas = data?.expirations.find((e) => e.tradeIdeas)?.tradeIdeas ?? [];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Options Action</h1>
          <p className="text-sm text-slate-500 mt-1">
            Expected move · IV regime · AI trade ideas · Unusual activity
          </p>
        </div>

        {/* Ticker search */}
        <form
          onSubmit={(e) => { e.preventDefault(); if (tickerInput.trim()) fetchOptions(tickerInput); }}
          className="flex gap-2"
        >
          <input
            value={tickerInput}
            onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
            placeholder="AAPL"
            className="bg-slate-800 border border-slate-700 text-slate-200 placeholder-slate-600 rounded-lg px-3 py-2 text-sm w-28 font-mono focus:outline-none focus:border-sky-500"
          />
          <button
            type="submit"
            disabled={loading}
            className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            {loading ? "Loading…" : "Fetch"}
          </button>
        </form>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-rose-500/10 border border-rose-500/25 rounded-xl p-4 text-rose-400 text-sm">
          {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-16 bg-slate-900 border border-slate-800 rounded-xl animate-pulse" />
            ))}
          </div>
          <div className="h-48 bg-slate-900 border border-slate-800 rounded-xl animate-pulse" />
        </div>
      )}

      {/* Data loaded */}
      {!loading && data && (
        <>
          {/* Stats strip */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">Current Price</p>
              <p className="text-xl font-bold text-slate-100">{fmtPrice(data.currentPrice)}</p>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">30d Realized Vol</p>
              <p className="text-xl font-bold text-slate-100">{data.rv30dPct}</p>
            </div>
            {validExps[0] && (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-3">
                <p className="text-xs text-slate-500 mb-1">Nearest ATM IV</p>
                <p className="text-xl font-bold text-slate-100">{validExps[0].atmIVPct}</p>
              </div>
            )}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">IV / RV Ratio</p>
              <p className="text-xl font-bold text-slate-100">{data.ivRvRatio?.toFixed(2) ?? "—"}×</p>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex items-center gap-2">
              <div>
                <p className="text-xs text-slate-500 mb-1">IV Regime</p>
                <IVRegimeBadge regime={data.ivRegime} />
              </div>
            </div>
          </div>

          {/* Expected moves */}
          <section>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Expected Move by Expiry
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
              {data.expirations.map((exp) => (
                <ExpectedMoveCard key={exp.expiry} exp={exp} price={data.currentPrice} />
              ))}
            </div>
          </section>

          {/* AI Trade Ideas */}
          {ideas.length > 0 && (
            <section>
              <div className="flex items-center gap-3 mb-3">
                <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
                  AI Trade Ideas
                </h2>
                <IVRegimeBadge regime={data.ivRegime} />
                <span className="text-xs text-slate-600">
                  IV {data.ivRvRatio?.toFixed(1) ?? "—"}× 30d realized vol →
                  {data.ivRegime === "high" ? " premium selling favored"
                    : data.ivRegime === "low" ? " premium buying favored"
                    : " balanced strategies"}
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {ideas.map((idea, i) => <TradeIdeaCard key={i} idea={idea} />)}
              </div>
            </section>
          )}

          {/* Unusual Activity (all expiries combined) */}
          <section>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Unusual Activity — All Expiries
            </h2>
            <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-800 text-xs text-slate-600">
                Volume/OI ≥ 2× or volume ≥ 500 contracts · sorted by volume
              </div>
              <UnusualActivity entries={allUnusual} />
            </div>
          </section>

          {/* Options Chain (per expiry) */}
          <section>
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
                Options Chain
              </h2>
              {validExps.map((exp, i) => (
                <button
                  key={exp.expiry}
                  onClick={() => setSelectedExpiry(i)}
                  className={`text-xs px-3 py-1 rounded-full border transition-all ${
                    selectedExpiry === i
                      ? "bg-slate-700 border-slate-600 text-slate-100"
                      : "border-slate-800 text-slate-500 hover:text-slate-300"
                  }`}
                >
                  {exp.expiry} ({exp.dte}d)
                </button>
              ))}
            </div>
            {activeExp && !activeExp.error && (
              <ChainTable exp={activeExp} price={data.currentPrice} />
            )}
          </section>
        </>
      )}
    </div>
  );
}
