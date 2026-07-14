"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { INSTITUTIONS } from "@/lib/institutions";
import type { HoldingsPayload } from "@/lib/holdings-types";

// ── Cache helpers (mirrors institutions/page.tsx) ──────────────────────────────
const CACHE_TTL_MS = 90 * 24 * 60 * 60 * 1000;
const LS_PREFIX    = "edgar_13f_";

function lsRead(id: string): HoldingsPayload | null {
  try {
    const raw = localStorage.getItem(`${LS_PREFIX}${id}`);
    if (!raw) return null;
    const entry = JSON.parse(raw) as { data: HoldingsPayload; cachedAt: number };
    if (Date.now() - entry.cachedAt > CACHE_TTL_MS) {
      localStorage.removeItem(`${LS_PREFIX}${id}`);
      return null;
    }
    return entry.data;
  } catch { return null; }
}

function lsWrite(id: string, data: HoldingsPayload): void {
  try {
    localStorage.setItem(`${LS_PREFIX}${id}`, JSON.stringify({ data, cachedAt: Date.now() }));
  } catch {}
}

// ── Formatting helpers ─────────────────────────────────────────────────────────
function fmtMM(mm: number): string {
  if (mm >= 1_000_000) return `$${(mm / 1_000_000).toFixed(2)}T`;
  if (mm >= 1_000)     return `$${(mm / 1_000).toFixed(1)}B`;
  return `$${mm.toFixed(0)}M`;
}

function fmtPct(n: number): string {
  return `${n.toFixed(1)}%`;
}

// ── Per-stock aggregate type ───────────────────────────────────────────────────
interface StockStats {
  name: string;
  cusip: string;
  totalValueMM: number;
  fundCount: number;
  fundNames: string[];      // all funds holding this stock
  newFundNames: string[];   // funds where change === "new"
  addCount: number;         // change === "increased"
  newCount: number;         // change === "new"
  sellCount: number;        // change === "decreased"
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function InstitutionsAnalyticsPage() {
  const [fundData, setFundData] = useState<Map<string, HoldingsPayload>>(new Map());
  const [fetchingIds, setFetchingIds] = useState<Set<string>>(new Set());
  const [mounted, setMounted] = useState(false);

  // Hydrate from localStorage on first render
  useEffect(() => {
    const loaded = new Map<string, HoldingsPayload>();
    for (const inst of INSTITUTIONS) {
      const cached = lsRead(inst.id);
      if (cached) loaded.set(inst.id, cached);
    }
    setFundData(loaded);
    setMounted(true);
  }, []);

  // Staggered load of every uncached fund
  const loadAll = useCallback(async () => {
    const uncached = INSTITUTIONS.filter(i => !fundData.has(i.id));
    for (let i = 0; i < uncached.length; i++) {
      const inst = uncached[i];
      setFetchingIds(prev => new Set([...prev, inst.id]));
      try {
        const r = await fetch(`/api/institutions/${inst.id}`, { cache: "no-store" });
        if (r.ok) {
          const data = await r.json() as HoldingsPayload;
          lsWrite(inst.id, data);
          setFundData(prev => new Map([...prev, [inst.id, data]]));
        }
      } catch { /* skip on error */ }
      setFetchingIds(prev => { const n = new Set(prev); n.delete(inst.id); return n; });
      if (i < uncached.length - 1) await new Promise(res => setTimeout(res, 500));
    }
  }, [fundData]);

  // ── Aggregation ──────────────────────────────────────────────────────────────
  const analytics = useMemo(() => {
    const allData = [...fundData.values()];
    if (allData.length === 0) return null;

    // Overview numbers
    const totalAUM     = allData.reduce((s, d) => s + d.totalValueMM, 0);
    const avgHoldings  = allData.reduce((s, d) => s + d.positionCount, 0) / allData.length;
    const top5Weights  = allData.map(d =>
      d.holdings.slice(0, 5).reduce((s, h) => s + h.pctPortfolio, 0)
    );
    const avgTop5Conc  = top5Weights.reduce((s, n) => s + n, 0) / top5Weights.length;

    // Build per-stock aggregate map keyed by CUSIP
    const byCusip = new Map<string, StockStats>();
    for (const [id, data] of fundData.entries()) {
      const fundName = INSTITUTIONS.find(i => i.id === id)?.name ?? id;
      for (const h of data.holdings) {
        if (!h.cusip) continue;
        const ex = byCusip.get(h.cusip);
        if (ex) {
          ex.totalValueMM += h.valueMM;
          ex.fundCount++;
          ex.fundNames.push(fundName);
          if (h.change === "increased") ex.addCount++;
          if (h.change === "new")       { ex.newCount++; ex.newFundNames.push(fundName); }
          if (h.change === "decreased") ex.sellCount++;
        } else {
          byCusip.set(h.cusip, {
            name: h.name,
            cusip: h.cusip,
            totalValueMM: h.valueMM,
            fundCount: 1,
            fundNames: [fundName],
            newFundNames: h.change === "new" ? [fundName] : [],
            addCount:  h.change === "increased" ? 1 : 0,
            newCount:  h.change === "new"       ? 1 : 0,
            sellCount: h.change === "decreased" ? 1 : 0,
          });
        }
      }
    }

    const allStocks  = [...byCusip.values()];
    const totalStocks = allStocks.length;

    // Rank lists
    const mostHeld       = [...allStocks].sort((a, b) => b.fundCount - a.fundCount).slice(0, 15);
    const largestByValue = [...allStocks].sort((a, b) => b.totalValueMM - a.totalValueMM).slice(0, 15);
    const topBuys        = [...allStocks]
                             .filter(s => s.addCount + s.newCount > 0)
                             .sort((a, b) => (b.addCount + b.newCount) - (a.addCount + a.newCount))
                             .slice(0, 10);
    const topSells       = [...allStocks]
                             .filter(s => s.sellCount > 0)
                             .sort((a, b) => b.sellCount - a.sellCount)
                             .slice(0, 10);
    const topNew         = [...allStocks]
                             .filter(s => s.newCount > 0)
                             .sort((a, b) => b.newCount - a.newCount)
                             .slice(0, 10);

    // Consensus builds: multi-fund stocks where buyers > sellers
    const consensus = [...allStocks]
      .filter(s => s.fundCount >= 2 && (s.addCount + s.newCount) > s.sellCount)
      .sort((a, b) => {
        const ratioA = (a.addCount + a.newCount) / Math.max(a.addCount + a.newCount + a.sellCount, 1);
        const ratioB = (b.addCount + b.newCount) / Math.max(b.addCount + b.newCount + b.sellCount, 1);
        return ratioB - ratioA || (b.addCount + b.newCount) - (a.addCount + a.newCount);
      })
      .slice(0, 10);

    // Fund AUM ranking
    const byAUM = [...fundData.entries()]
      .map(([id, d]) => ({
        id,
        name: INSTITUTIONS.find(i => i.id === id)?.name ?? id,
        totalValueMM: d.totalValueMM,
        positionCount: d.positionCount,
        quarter: d.quarter,
      }))
      .sort((a, b) => b.totalValueMM - a.totalValueMM);

    // Fund concentration ranking (top-5 weight)
    const byConc = [...fundData.entries()]
      .map(([id, d]) => {
        const top5pct = d.holdings.slice(0, 5).reduce((s, h) => s + h.pctPortfolio, 0);
        return {
          id,
          name: INSTITUTIONS.find(i => i.id === id)?.name ?? id,
          top5pct,
          positionCount: d.positionCount,
        };
      })
      .filter(f => f.positionCount > 0)
      .sort((a, b) => b.top5pct - a.top5pct);

    return {
      totalAUM, avgHoldings, avgTop5Conc,
      fundsLoaded: allData.length,
      totalStocks,
      mostHeld, largestByValue, topBuys, topSells, topNew,
      byAUM, byConc, consensus,
    };
  }, [fundData]);

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="p-6 max-w-7xl mx-auto">

      {/* Page header */}
      <div className="flex items-start justify-between mb-6 gap-4 flex-wrap">
        <div>
          <Link
            href="/portfolio/institutions"
            className="text-xs text-slate-500 hover:text-sky-400 transition-colors"
          >
            ← Institutions
          </Link>
          <h1 className="text-2xl font-bold text-slate-100 mt-1">Institutional Intelligence</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Cross-fund 13F analytics · {INSTITUTIONS.length} funds tracked
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-xs text-slate-500 mb-1.5">
            {mounted
              ? `${fundData.size} / ${INSTITUTIONS.length} funds cached`
              : "Checking cache…"}
          </p>
          <button
            onClick={loadAll}
            disabled={!mounted || fetchingIds.size > 0 || (mounted && fundData.size === INSTITUTIONS.length)}
            className="text-xs px-3 py-1.5 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/25
                       hover:bg-sky-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {fetchingIds.size > 0
              ? `Loading ${fetchingIds.size} fund${fetchingIds.size !== 1 ? "s" : ""}…`
              : fundData.size === INSTITUTIONS.length
              ? "All funds loaded ✓"
              : `Load ${INSTITUTIONS.length - fundData.size} missing funds`}
          </button>
        </div>
      </div>

      {/* Body */}
      {!mounted ? (
        <div className="text-slate-500 text-sm text-center py-20 animate-pulse">Reading cache…</div>
      ) : !analytics ? (
        <div className="text-center py-20 space-y-3">
          <p className="text-slate-400 text-sm">No fund data in cache yet.</p>
          <p className="text-xs text-slate-600">
            Visit the{" "}
            <Link href="/portfolio/institutions" className="text-sky-400 hover:underline">
              Institutions page
            </Link>{" "}
            to load individual tiles, or click <span className="text-slate-400 font-medium">Load Missing Funds</span> above
            to pull everything from SEC EDGAR.
          </p>
        </div>
      ) : (
        <div className="space-y-6">

          {/* ── Overview cards ───────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              { label: "Funds Loaded",    value: `${analytics.fundsLoaded} / ${INSTITUTIONS.length}`, color: "text-sky-400",   sub: "cached 13F data" },
              { label: "Combined AUM",    value: fmtMM(analytics.totalAUM),                           color: "text-slate-100", sub: "13F equity value" },
              { label: "Unique Stocks",   value: analytics.totalStocks.toLocaleString(),               color: "text-slate-100", sub: "distinct CUSIPs" },
              { label: "Avg Holdings",    value: analytics.avgHoldings.toFixed(0),                    color: "text-slate-100", sub: "positions per fund" },
              { label: "Avg Top-5 Conc.", value: fmtPct(analytics.avgTop5Conc),                       color: "text-amber-400", sub: "of each portfolio" },
            ].map(({ label, value, color, sub }) => (
              <div key={label} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</p>
                <p className={`text-xl font-bold ${color}`}>{value}</p>
                <p className="text-[10px] text-slate-600 mt-0.5">{sub}</p>
              </div>
            ))}
          </div>

          {/* ── Most widely held + Largest aggregate positions ───────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            <Panel
              title="🏆 Most Widely Held"
              subtitle="Stocks held across the most funds — the true crowded trade basket"
            >
              {analytics.mostHeld.slice(0, 10).map((s, i) => (
                <StockRow
                  key={s.cusip}
                  rank={i + 1}
                  name={s.name}
                  bar={s.fundCount / analytics.mostHeld[0].fundCount}
                  barColor="bg-sky-500/50"
                  right={<CountBadge n={s.fundCount} label="funds" color="text-sky-400" />}
                  sub={s.fundNames.slice(0, 4).join(", ") + (s.fundNames.length > 4 ? ` +${s.fundNames.length - 4} more` : "")}
                />
              ))}
            </Panel>

            <Panel
              title="💰 Largest Aggregate Positions"
              subtitle="By combined 13F $ value — where institutional capital is concentrated"
            >
              {analytics.largestByValue.slice(0, 10).map((s, i) => (
                <StockRow
                  key={s.cusip}
                  rank={i + 1}
                  name={s.name}
                  bar={s.totalValueMM / analytics.largestByValue[0].totalValueMM}
                  barColor="bg-emerald-500/40"
                  right={<span className="text-emerald-400 text-xs font-medium tabular-nums">{fmtMM(s.totalValueMM)}</span>}
                  sub={`across ${s.fundCount} fund${s.fundCount !== 1 ? "s" : ""}`}
                />
              ))}
            </Panel>
          </div>

          {/* ── Top buys + Top sells ─────────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            <Panel
              title="↑ Top Buys This Quarter"
              subtitle="Most funds increasing or initiating a position QoQ"
            >
              {analytics.topBuys.map((s, i) => {
                const total = s.addCount + s.newCount;
                const maxTotal = analytics.topBuys[0].addCount + analytics.topBuys[0].newCount;
                return (
                  <StockRow
                    key={s.cusip}
                    rank={i + 1}
                    name={s.name}
                    bar={total / maxTotal}
                    barColor="bg-emerald-500/40"
                    right={<CountBadge n={total} label="funds buying" color="text-emerald-400" />}
                    sub={[
                      s.newCount > 0 ? `${s.newCount} new entry` : "",
                      s.addCount > 0 ? `${s.addCount} increased` : "",
                    ].filter(Boolean).join(" · ")}
                  />
                );
              })}
            </Panel>

            <Panel
              title="↓ Top Sells This Quarter"
              subtitle="Most funds reducing or exiting a position QoQ"
            >
              {analytics.topSells.map((s, i) => (
                <StockRow
                  key={s.cusip}
                  rank={i + 1}
                  name={s.name}
                  bar={s.sellCount / analytics.topSells[0].sellCount}
                  barColor="bg-rose-500/40"
                  right={<CountBadge n={s.sellCount} label="funds reducing" color="text-rose-400" />}
                  sub={`held by ${s.fundCount} fund${s.fundCount !== 1 ? "s" : ""} total`}
                />
              ))}
            </Panel>
          </div>

          {/* ── New positions + Consensus builds ────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            <Panel
              title="✦ New Positions This Quarter"
              subtitle="Stocks freshly entered by the most funds — potential emerging conviction"
            >
              {analytics.topNew.map((s, i) => (
                <StockRow
                  key={s.cusip}
                  rank={i + 1}
                  name={s.name}
                  bar={s.newCount / analytics.topNew[0].newCount}
                  barColor="bg-violet-500/40"
                  right={
                    <span className="text-violet-400 text-xs font-medium">
                      {s.newCount}× <span className="text-[10px] font-normal text-slate-600">NEW</span>
                    </span>
                  }
                  sub={s.newFundNames.slice(0, 3).join(", ") + (s.newFundNames.length > 3 ? ` +${s.newFundNames.length - 3}` : "")}
                />
              ))}
            </Panel>

            <Panel
              title="📈 Consensus Builds"
              subtitle="Multi-fund stocks where buyers clearly outnumber sellers — institutional momentum"
            >
              {analytics.consensus.map((s, i) => {
                const buyTotal  = s.addCount + s.newCount;
                const total     = buyTotal + s.sellCount;
                const bullRatio = total > 0 ? buyTotal / total : 1;
                return (
                  <div key={s.cusip} className="flex items-center gap-2 py-2 border-b border-slate-800/40 last:border-0">
                    <span className="text-xs text-slate-600 w-5 shrink-0 text-right">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-slate-300 truncate">{s.name}</p>
                      <p className="text-[10px] text-slate-600">{s.fundCount} funds · {fmtMM(s.totalValueMM)}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <div className="text-right">
                        <span className="text-[10px] text-emerald-400">{buyTotal}▲</span>
                        {s.sellCount > 0 && (
                          <span className="text-[10px] text-rose-400 ml-1">{s.sellCount}▼</span>
                        )}
                      </div>
                      <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-emerald-500 rounded-full transition-all"
                          style={{ width: `${bullRatio * 100}%` }}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </Panel>
          </div>

          {/* ── Fund AUM ranking + Concentration leaderboard ────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            <Panel
              title="📊 Fund AUM Ranking"
              subtitle="13F equity value by fund, latest available filing"
            >
              {analytics.byAUM.slice(0, 15).map((f, i) => (
                <div key={f.id} className="flex items-center gap-2 py-1.5 border-b border-slate-800/40 last:border-0">
                  <span className="text-xs text-slate-600 w-5 shrink-0 text-right">{i + 1}</span>
                  <Link
                    href={`/portfolio/institutions/${f.id}`}
                    className="text-xs text-slate-300 flex-1 hover:text-sky-400 transition-colors truncate"
                  >
                    {f.name}
                  </Link>
                  <span className="text-[10px] text-slate-600 shrink-0">{f.positionCount}pos</span>
                  <span className="text-[10px] text-slate-600 shrink-0">{f.quarter}</span>
                  <span className="text-xs font-medium text-slate-200 shrink-0 w-20 text-right tabular-nums">
                    {fmtMM(f.totalValueMM)}
                  </span>
                </div>
              ))}
            </Panel>

            <Panel
              title="🎯 Conviction Leaderboard"
              subtitle="Top-5 weight as % of portfolio — higher = more concentrated bets"
            >
              {analytics.byConc.slice(0, 15).map((f, i) => {
                const isHigh   = f.top5pct > 80;
                const isMedium = f.top5pct > 60;
                const barCls   = isHigh ? "bg-amber-500" : isMedium ? "bg-orange-400" : "bg-sky-500";
                const lblCls   = isHigh ? "text-amber-400" : isMedium ? "text-orange-400" : "text-sky-400";
                return (
                  <div key={f.id} className="flex items-center gap-2 py-1.5 border-b border-slate-800/40 last:border-0">
                    <span className="text-xs text-slate-600 w-5 shrink-0 text-right">{i + 1}</span>
                    <Link
                      href={`/portfolio/institutions/${f.id}`}
                      className="text-xs text-slate-300 flex-1 hover:text-sky-400 transition-colors truncate"
                    >
                      {f.name}
                    </Link>
                    <div className="flex items-center gap-2 shrink-0">
                      <div className="w-20 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${barCls}`}
                          style={{ width: `${Math.min(f.top5pct, 100)}%` }}
                        />
                      </div>
                      <span className={`text-xs font-medium w-11 text-right tabular-nums ${lblCls}`}>
                        {fmtPct(f.top5pct)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </Panel>
          </div>

          {/* ── Footer note ──────────────────────────────────────────────────── */}
          <p className="text-[11px] text-slate-700 text-center pb-4">
            Analytics based on {analytics.fundsLoaded} of {INSTITUTIONS.length} cached funds ·
            13F holdings reported 45 days after quarter-end ·
            Large quant funds (Jane Street, Citadel, D.E. Shaw) hold thousands of positions and may skew aggregate counts
          </p>

        </div>
      )}
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-slate-200 mb-0.5">{title}</h2>
      <p className="text-[11px] text-slate-500 mb-3">{subtitle}</p>
      <div>{children}</div>
    </div>
  );
}

function StockRow({
  rank,
  name,
  bar,
  barColor,
  right,
  sub,
}: {
  rank: number;
  name: string;
  bar: number;
  barColor: string;
  right: React.ReactNode;
  sub?: string;
}) {
  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-slate-800/40 last:border-0">
      <span className="text-xs text-slate-600 w-5 shrink-0 text-right">{rank}</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-slate-300 truncate">{name}</p>
        {sub && <p className="text-[10px] text-slate-600 truncate">{sub}</p>}
        <div className="mt-0.5 h-0.5 bg-slate-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${barColor}`}
            style={{ width: `${Math.max(bar * 100, 2)}%` }}
          />
        </div>
      </div>
      <div className="shrink-0 min-w-[80px] text-right">{right}</div>
    </div>
  );
}

function CountBadge({
  n,
  label,
  color,
}: {
  n: number;
  label: string;
  color: string;
}) {
  return (
    <span className="text-xs tabular-nums">
      <span className={`font-semibold ${color}`}>{n}</span>{" "}
      <span className="text-slate-600 font-normal">{label}</span>
    </span>
  );
}
