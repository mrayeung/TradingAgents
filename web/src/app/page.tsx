"use client";

import { useState, useEffect, useCallback } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────
interface MacroTraffic {
  sofr: number | null;
  iorb: number | null;
  sofr_iorb_spread: number | null;
  spread_status: string;
  rrp_balance_bn: number | null;
  rrp_status: string;
}

interface DrainItem {
  settlement_date: string;
  auction_date: string;
  type: string;
  amount_bn: number;
}

interface TreasuryDrain {
  upcoming: DrainItem[];
  next_drain: { date: string; amount_bn: number; type: string; status: string } | null;
  weekly_net_bn: number | null;
  status: string;
}

interface CalendarEvent {
  date: string;
  event: string;
  category: string;
  severity: string;
  tickers: string[];
  notes: string;
}

interface PositionRow {
  ticker: string;
  strategy: string;
  next_event: string;
  event_date: string | null;
  days_to_event: number | null;
  risk_level: string;
  risk_tags: string[];
  recommendation: string;
}

interface InsiderSignal {
  ticker: string;
  type: string;
  officer: string;
  action: string;
  shares: number;
  value_usd: number;
  date: string;
  is_cluster: boolean;
  note: string;
}

interface DashboardData {
  generated_at: string;
  watchlist: string[];
  macro_traffic: MacroTraffic;
  treasury_drain: TreasuryDrain;
  calendar: CalendarEvent[];
  position_matrix: PositionRow[];
  insider_signals: InsiderSignal[];
  warnings: string[];
}

// ── Color helpers ─────────────────────────────────────────────────────────────
function spreadStatusCls(s: string) {
  const m: Record<string, string> = {
    GREEN: "text-emerald-400 bg-emerald-900/30 border-emerald-700",
    YELLOW: "text-amber-300 bg-amber-900/30 border-amber-700",
    RED: "text-rose-400 bg-rose-900/30 border-rose-700",
    UNKNOWN: "text-slate-400 bg-slate-800 border-slate-700",
  };
  return m[s] ?? m.UNKNOWN;
}

function rrpStatusCls(s: string) {
  const m: Record<string, string> = {
    ABUNDANT: "text-sky-400 bg-sky-900/30 border-sky-700",
    LOW: "text-amber-300 bg-amber-900/30 border-amber-700",
    CRITICAL: "text-rose-400 bg-rose-900/30 border-rose-700",
    UNKNOWN: "text-slate-400 bg-slate-800 border-slate-700",
  };
  return m[s] ?? m.UNKNOWN;
}

function drainStatusCls(s: string) {
  const m: Record<string, string> = {
    NORMAL: "text-emerald-400 bg-emerald-900/30 border-emerald-700",
    MONITOR: "text-amber-300 bg-amber-900/30 border-amber-700",
    CODE_RED: "text-rose-400 bg-rose-900/30 border-rose-700 animate-pulse",
    UNKNOWN: "text-slate-400 bg-slate-800 border-slate-700",
  };
  return m[s] ?? m.UNKNOWN;
}

function categoryColor(cat: string): string {
  const m: Record<string, string> = {
    MACRO: "text-violet-300 bg-violet-900/30",
    EARNINGS: "text-sky-300 bg-sky-900/30",
    DIVIDEND: "text-emerald-300 bg-emerald-900/30",
    COMMODITY: "text-amber-300 bg-amber-900/30",
    LIQUIDITY: "text-rose-300 bg-rose-900/30",
    OPEX: "text-indigo-300 bg-indigo-900/30",
  };
  return m[cat] ?? "text-slate-300 bg-slate-800";
}

function severityDot(s: string): string {
  const m: Record<string, string> = {
    HIGH: "bg-rose-500",
    MEDIUM: "bg-amber-400",
    LOW: "bg-slate-500",
  };
  return m[s] ?? "bg-slate-600";
}

function riskCls(level: string) {
  const m: Record<string, string> = {
    HIGH: "text-rose-400 bg-rose-900/30 border border-rose-700/60",
    MEDIUM: "text-amber-300 bg-amber-900/30 border border-amber-700/60",
    LOW: "text-emerald-400 bg-emerald-900/30 border border-emerald-700/60",
    NORMAL: "text-slate-300 bg-slate-800 border border-slate-700",
    UNKNOWN: "text-slate-400 bg-slate-800 border border-slate-700",
  };
  return m[level] ?? m.UNKNOWN;
}

function fmtDate(d: string) {
  const dt = new Date(d + "T12:00:00");
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" });
}

function fmtMoney(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function daysLabel(d: number | null): string {
  if (d === null) return "—";
  if (d === 0) return "Today";
  if (d === 1) return "Tomorrow";
  return `${d}d`;
}

// ── Traffic Light Card ────────────────────────────────────────────────────────
function TrafficCard({
  title,
  value,
  unit,
  badge,
  badgeCls,
  sub,
  icon,
}: {
  title: string;
  value: string;
  unit?: string;
  badge: string;
  badgeCls: string;
  sub: string;
  icon: string;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-slate-400 text-xs font-semibold uppercase tracking-widest">
          {icon} {title}
        </span>
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${badgeCls}`}>
          {badge}
        </span>
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-2xl font-mono font-bold text-white">{value}</span>
        {unit && <span className="text-sm text-slate-500">{unit}</span>}
      </div>
      <p className="text-xs text-slate-500 leading-relaxed">{sub}</p>
    </div>
  );
}

// ── Calendar Panel ────────────────────────────────────────────────────────────
function CalendarPanel({ events }: { events: CalendarEvent[] }) {
  const upcoming = events.filter((e) => e.date >= new Date().toISOString().slice(0, 10));

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden h-full flex flex-col">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <span className="text-slate-200 text-sm font-semibold">📅 Master Calendar</span>
        <span className="text-slate-500 text-xs ml-auto">{upcoming.length} events · 60d</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {upcoming.length === 0 && (
          <p className="text-slate-500 text-sm text-center py-8">No events in range</p>
        )}
        {upcoming.map((ev, i) => (
          <div
            key={i}
            className="px-4 py-3 border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors"
          >
            <div className="flex items-start gap-2">
              <span className={`mt-1 w-2 h-2 rounded-full shrink-0 ${severityDot(ev.severity)}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-white text-xs font-medium leading-snug">{ev.event}</span>
                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${categoryColor(ev.category)}`}>
                    {ev.category}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-slate-400 text-[11px] font-mono">{fmtDate(ev.date)}</span>
                  {ev.tickers.length > 0 && (
                    <span className="text-slate-600 text-[10px]">
                      {ev.tickers.slice(0, 3).join(" · ")}
                    </span>
                  )}
                </div>
                {ev.notes && (
                  <p className="text-slate-600 text-[10px] mt-0.5 leading-relaxed truncate">
                    {ev.notes}
                  </p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Treasury Drain Mini-List ──────────────────────────────────────────────────
function DrainSchedule({ drain }: { drain: TreasuryDrain }) {
  if (!drain.upcoming.length) return null;
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <span className="text-slate-200 text-sm font-semibold">🏦 T-Bill Settlement Schedule (14d)</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500">
              <th className="text-left px-4 py-2">Settlement</th>
              <th className="text-left px-4 py-2">Auction</th>
              <th className="text-left px-4 py-2">Type</th>
              <th className="text-right px-4 py-2">Amount</th>
            </tr>
          </thead>
          <tbody>
            {drain.upcoming.map((item, i) => (
              <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                <td className="px-4 py-2 font-mono text-white">{fmtDate(item.settlement_date)}</td>
                <td className="px-4 py-2 font-mono text-slate-400">{item.auction_date ? fmtDate(item.auction_date) : "—"}</td>
                <td className="px-4 py-2 text-slate-300">{item.type}</td>
                <td className="px-4 py-2 text-right font-mono text-amber-300">${item.amount_bn}B</td>
              </tr>
            ))}
          </tbody>
          {drain.weekly_net_bn !== null && (
            <tfoot>
              <tr className="border-t border-slate-700">
                <td colSpan={3} className="px-4 py-2 text-slate-500">7-day net drain</td>
                <td className="px-4 py-2 text-right font-mono font-bold text-amber-300">
                  ${drain.weekly_net_bn}B
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

// ── Position Risk Matrix ──────────────────────────────────────────────────────
function RiskMatrix({ rows }: { rows: PositionRow[] }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <span className="text-slate-200 text-sm font-semibold">
          🎯 Position Risk Matrix
        </span>
        <span className="text-slate-500 text-xs ml-2">agent-style risk cross-reference</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider text-[10px]">
              <th className="text-left px-4 py-2.5">Ticker</th>
              <th className="text-left px-4 py-2.5">Strategy</th>
              <th className="text-left px-4 py-2.5">Next Catalyst</th>
              <th className="text-center px-4 py-2.5">DTE</th>
              <th className="text-center px-4 py-2.5">Risk</th>
              <th className="text-left px-4 py-2.5 min-w-[280px]">Agent Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.ticker}
                className={`border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors
                  ${row.risk_level === "HIGH" ? "bg-rose-950/10" : ""}`}
              >
                {/* Ticker */}
                <td className="px-4 py-3">
                  <span className="text-white font-bold text-sm">{row.ticker}</span>
                </td>
                {/* Strategy */}
                <td className="px-4 py-3 text-slate-400 whitespace-nowrap">{row.strategy}</td>
                {/* Next event */}
                <td className="px-4 py-3">
                  <div className="text-slate-200 leading-snug">{row.next_event}</div>
                  {row.event_date && (
                    <div className="text-slate-500 font-mono mt-0.5">{fmtDate(row.event_date)}</div>
                  )}
                  {row.risk_tags.length > 0 && (
                    <div className="flex gap-1 mt-1 flex-wrap">
                      {row.risk_tags.map((tag) => (
                        <span
                          key={tag}
                          className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-slate-800 text-amber-400 border border-amber-900"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                {/* DTE */}
                <td className="px-4 py-3 text-center">
                  <span
                    className={`font-mono font-bold text-sm ${
                      row.days_to_event !== null && row.days_to_event <= 3
                        ? "text-rose-400"
                        : row.days_to_event !== null && row.days_to_event <= 10
                        ? "text-amber-300"
                        : "text-slate-300"
                    }`}
                  >
                    {daysLabel(row.days_to_event)}
                  </span>
                </td>
                {/* Risk badge */}
                <td className="px-4 py-3 text-center">
                  <span
                    className={`text-[10px] font-bold px-2 py-1 rounded-full ${riskCls(
                      row.risk_level
                    )}`}
                  >
                    {row.risk_level}
                  </span>
                </td>
                {/* Recommendation */}
                <td className="px-4 py-3 text-slate-400 leading-relaxed text-[11px] max-w-xs">
                  {row.recommendation}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Insider Signals ───────────────────────────────────────────────────────────
function InsiderPanel({ signals }: { signals: InsiderSignal[] }) {
  if (signals.length === 0) return null;
  return (
    <div className="bg-slate-900 border border-emerald-800/40 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <span className="text-emerald-400 text-sm font-semibold">★ Insider Cluster Signals</span>
        <span className="text-slate-500 text-xs">(48h window · Open Market Purchases only)</span>
      </div>
      <div className="divide-y divide-slate-800/60">
        {signals.map((s, i) => (
          <div key={i} className="px-4 py-3 flex items-start gap-4">
            <span className="text-white font-bold text-lg w-14 shrink-0">{s.ticker}</span>
            <div className="flex-1">
              <div className="text-slate-200 text-xs">{s.officer} — {s.action}</div>
              <div className="flex gap-4 mt-1 text-[11px]">
                <span className="text-slate-400">
                  {s.shares.toLocaleString()} shares
                </span>
                <span className="text-emerald-400 font-mono font-semibold">
                  {fmtMoney(s.value_usd)}
                </span>
                <span className="text-slate-600">{s.date}</span>
              </div>
              <p className="text-emerald-600 text-[10px] mt-1">{s.note}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Warnings Banner ───────────────────────────────────────────────────────────
function WarningsBanner({ warnings }: { warnings: string[] }) {
  const [open, setOpen] = useState(false);
  if (!warnings.length) return null;
  return (
    <div className="bg-amber-950/30 border border-amber-800/50 rounded-lg px-4 py-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 text-amber-400 text-xs font-semibold w-full"
      >
        <span>⚠ {warnings.length} data warning{warnings.length > 1 ? "s" : ""}</span>
        <span className="ml-auto text-amber-600">{open ? "▲ hide" : "▼ show"}</span>
      </button>
      {open && (
        <ul className="mt-2 space-y-0.5">
          {warnings.map((w, i) => (
            <li key={i} className="text-[10px] text-amber-600 font-mono">
              • {w}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const url = `http://localhost:8765/dashboard${forceRefresh ? "?refresh=true" : ""}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Auto-refresh every hour
    const iv = setInterval(() => fetchData(), 60 * 60 * 1000);
    return () => clearInterval(iv);
  }, [fetchData]);

  const generatedAt = data
    ? new Date(data.generated_at).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : null;

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* ── Header ───────────────────────────────────────────────────────────── */}
      <div className="sticky top-0 z-10 bg-slate-950/90 backdrop-blur border-b border-slate-800 px-6 py-3 flex items-center gap-4">
        <div>
          <h1 className="text-base font-bold text-white tracking-tight">
            Macro Risk &amp; Event Intelligence
          </h1>
          <p className="text-xs text-slate-500">
            Liquidity drain · sovereign events · position catalyst cross-reference
          </p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {generatedAt && (
            <span className="text-xs text-slate-600">Updated {generatedAt}</span>
          )}
          <button
            onClick={() => fetchData(true)}
            disabled={loading}
            className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors disabled:opacity-50"
          >
            {loading ? "⟳ Loading…" : "↺ Refresh"}
          </button>
        </div>
      </div>

      <div className="px-6 py-5 space-y-5">
        {/* ── Error ──────────────────────────────────────────────────────────── */}
        {error && !loading && (
          <div className="bg-rose-950/30 border border-rose-700/60 rounded-xl p-4 text-rose-400 text-sm">
            <span className="font-bold">⚠ Engine unreachable</span> — {error}
            <br />
            <span className="text-xs text-rose-600">
              Make sure{" "}
              <code className="font-mono">
                cd desk_server &amp;&amp; uvicorn app:app --port 8765
              </code>{" "}
              is running.
            </span>
          </div>
        )}

        {/* ── Skeleton ───────────────────────────────────────────────────────── */}
        {loading && !data && (
          <div className="grid grid-cols-3 gap-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-32 rounded-xl bg-slate-800/50 animate-pulse" />
            ))}
          </div>
        )}

        {data && (
          <>
            {/* ── Warnings ─────────────────────────────────────────────────── */}
            <WarningsBanner warnings={data.warnings} />

            {/* ── Top Banner: 3 Traffic Light Cards ───────────────────────── */}
            <div className="grid grid-cols-3 gap-4">
              {/* SOFR / IORB */}
              <TrafficCard
                title="SOFR / IORB Spread"
                icon="🔴"
                value={
                  data.macro_traffic.sofr_iorb_spread !== null
                    ? `${data.macro_traffic.sofr_iorb_spread > 0 ? "+" : ""}${(
                        data.macro_traffic.sofr_iorb_spread * 100
                      ).toFixed(0)}bps`
                    : "—"
                }
                badge={data.macro_traffic.spread_status}
                badgeCls={spreadStatusCls(data.macro_traffic.spread_status)}
                sub={
                  data.macro_traffic.sofr !== null && data.macro_traffic.iorb !== null
                    ? `SOFR ${data.macro_traffic.sofr.toFixed(2)}% · IORB ${data.macro_traffic.iorb.toFixed(2)}% — ${
                        data.macro_traffic.spread_status === "GREEN"
                          ? "Ample reserves — normal liquidity conditions"
                          : data.macro_traffic.spread_status === "YELLOW"
                          ? "Reserve tightening — monitor SOFR closely"
                          : "Reserve scarcity signal — risk-off pressure"
                      }`
                    : "FRED data unavailable"
                }
              />

              {/* Treasury Drain */}
              <TrafficCard
                title="Next Treasury Settlement"
                icon="🏦"
                value={
                  data.treasury_drain.next_drain
                    ? `$${data.treasury_drain.next_drain.amount_bn}B`
                    : "—"
                }
                unit={data.treasury_drain.next_drain?.type}
                badge={data.treasury_drain.status}
                badgeCls={drainStatusCls(data.treasury_drain.status)}
                sub={
                  data.treasury_drain.next_drain
                    ? `Settles ${fmtDate(data.treasury_drain.next_drain.date)} · 7d net drain $${data.treasury_drain.weekly_net_bn ?? "?"}B · ${
                        data.treasury_drain.status === "CODE_RED"
                          ? "⚠ Exceeds $100B — RRP near zero — CODE RED"
                          : data.treasury_drain.status === "MONITOR"
                          ? "Monitor — elevated drain can spook risk assets"
                          : "Normal settlement volume — no systemic risk"
                      }`
                    : "No Treasury auctions in next 14 days"
                }
              />

              {/* RRP Balance */}
              <TrafficCard
                title="RRP Balance (RRPONTSYD)"
                icon="💧"
                value={data.macro_traffic.rrp_balance_bn !== null ? `$${data.macro_traffic.rrp_balance_bn.toFixed(0)}B` : "—"}
                badge={data.macro_traffic.rrp_status}
                badgeCls={rrpStatusCls(data.macro_traffic.rrp_status)}
                sub={
                  data.macro_traffic.rrp_balance_bn !== null
                    ? `${
                        data.macro_traffic.rrp_status === "ABUNDANT"
                          ? "Ample buffer — RRP > $300B cushions liquidity drains"
                          : data.macro_traffic.rrp_status === "LOW"
                          ? "RRP buffer depleted — next $50B+ drain is systemic"
                          : "⚠ CRITICAL — RRP near zero; next drain hits bank reserves directly"
                      }`
                    : "FRED RRPONTSYD unavailable"
                }
              />
            </div>

            {/* ── Body: Calendar (left) + Risk Matrix (right) ─────────────── */}
            <div className="grid grid-cols-[300px_1fr] gap-4 min-h-[520px]">
              {/* Left: Calendar */}
              <CalendarPanel events={data.calendar} />

              {/* Right: Risk Matrix + Insiders + Drain Schedule */}
              <div className="flex flex-col gap-4">
                <RiskMatrix rows={data.position_matrix} />
                {data.insider_signals.length > 0 && (
                  <InsiderPanel signals={data.insider_signals} />
                )}
                <DrainSchedule drain={data.treasury_drain} />
              </div>
            </div>

            {/* ── Footer ───────────────────────────────────────────────────── */}
            <div className="text-center text-slate-700 text-[10px] pb-2">
              Data: FRED (SOFR · IORB · RRPONTSYD) · TreasuryDirect FiscalData API · yfinance · Finnhub (if key set)
              · FOMC/CPI/OpEx dates hardcoded from published 2026 Fed/BLS calendar
              · Cached 1h · Last built: {data.generated_at.slice(0, 19).replace("T", " ")}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
