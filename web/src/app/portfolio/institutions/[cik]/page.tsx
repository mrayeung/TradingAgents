"use client";

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { INSTITUTIONS, CATEGORY_META } from "@/lib/institutions";
import type { HoldingsPayload, ProcessedHolding } from "@/lib/holdings-types";

// ── Formatting ────────────────────────────────────────────────────────────────

function fmtMM(mm: number | null | undefined): string {
  if (mm == null) return "—";
  if (mm >= 1_000_000) return `$${(mm / 1_000_000).toFixed(2)}T`;
  if (mm >= 1_000)     return `$${(mm / 1_000).toFixed(1)}B`;
  return `$${mm}M`;
}

function fmtShares(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

// ── Change UI helpers ─────────────────────────────────────────────────────────

type ChangeFilter = "all" | "new" | "increased" | "decreased" | "unchanged";

function ChangePill({ change, pct }: { change: ProcessedHolding["change"]; pct: number | null }) {
  if (change === "new") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-400/10 border border-emerald-400/25 text-emerald-400 font-medium">
        ✦ New
      </span>
    );
  }
  if (change === "increased") {
    const absPct = pct != null ? Math.abs(pct) : null;
    const label = absPct == null ? "Added" : absPct > 999 ? ">999%" : `${absPct.toFixed(0)}%`;
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-sky-400/10 border border-sky-400/25 text-sky-400 font-medium">
        ↑ {label}
      </span>
    );
  }
  if (change === "decreased") {
    const absPct = pct != null ? Math.abs(pct) : null;
    const label = absPct == null ? "Reduced" : absPct > 999 ? ">999%" : `${absPct.toFixed(0)}%`;
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-rose-400/10 border border-rose-400/25 text-rose-400 font-medium">
        ↓ {label}
      </span>
    );
  }
  return <span className="text-xs text-slate-600">—</span>;
}

// ── Concentration bar (top 5 summary) ────────────────────────────────────────

function ConcentrationBar({ holdings }: { holdings: ProcessedHolding[] }) {
  const safe = holdings ?? [];
  const top5 = safe.slice(0, 5);
  const others = safe.slice(5);
  const othersPct = others.reduce((s, h) => s + h.pctPortfolio, 0);

  const COLORS = [
    "bg-sky-500",
    "bg-violet-500",
    "bg-amber-500",
    "bg-emerald-500",
    "bg-rose-500",
  ];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <h3 className="text-xs font-medium text-slate-400 mb-3 uppercase tracking-wider">Top 5 Concentration</h3>
      {/* Stacked bar */}
      <div className="flex h-3 rounded-full overflow-hidden gap-0.5 mb-4">
        {top5.map((h, i) => (
          <div
            key={h.cusip ?? i}
            className={`${COLORS[i]} transition-all`}
            style={{ width: `${h.pctPortfolio}%` }}
            title={`${h.name}: ${h.pctPortfolio.toFixed(1)}%`}
          />
        ))}
        {othersPct > 0 && (
          <div
            className="bg-slate-700"
            style={{ width: `${othersPct}%` }}
            title={`Others: ${othersPct.toFixed(1)}%`}
          />
        )}
      </div>
      {/* Legend */}
      <div className="space-y-1.5">
        {top5.map((h, i) => (
          <div key={h.cusip} className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full shrink-0 ${COLORS[i]}`} />
            <span className="text-xs text-slate-300 flex-1 truncate">{h.name}</span>
            <span className="text-xs font-medium text-slate-200">{h.pctPortfolio.toFixed(1)}%</span>
          </div>
        ))}
        {othersPct > 0 && (
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full shrink-0 bg-slate-700" />
            <span className="text-xs text-slate-500 flex-1">All other positions</span>
            <span className="text-xs text-slate-500">{othersPct.toFixed(1)}%</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function InstitutionDetailPage() {
  const params = useParams();
  const cik = params?.cik as string;

  const institution = INSTITUTIONS.find((i) => i.id === cik);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<HoldingsPayload | null>(null);

  const [changeFilter, setChangeFilter] = useState<ChangeFilter>("all");
  const [sortKey, setSortKey] = useState<"rank" | "change">("rank");

  // localStorage helpers — 90-day TTL matches the server-side file cache
  const LS_PREFIX    = "edgar_13f_";
  const CACHE_TTL_MS = 90 * 24 * 60 * 60 * 1000;

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

  function lsWrite(id: string, payload: HoldingsPayload): void {
    try {
      localStorage.setItem(`${LS_PREFIX}${id}`, JSON.stringify({ data: payload, cachedAt: Date.now() }));
    } catch { /* quota exceeded — ignore */ }
  }

  const doFetch = (id: string) => {
    setLoading(true);
    setError(null);
    fetch(`/api/institutions/${id}`, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<HoldingsPayload>;
      })
      .then((d) => {
        lsWrite(id, d);
        setData(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  };

  useEffect(() => {
    if (!cik) return;
    // Try localStorage first — avoids a 30-60s EDGAR round-trip on repeat visits
    const stored = lsRead(cik);
    if (stored) {
      setData(stored);
      setLoading(false);
      return;
    }
    doFetch(cik);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cik]);

  const filtered = useMemo(() => {
    const holdings = data?.holdings ?? [];
    let rows = changeFilter === "all" ? holdings : holdings.filter((h) => h.change === changeFilter);
    if (sortKey === "change") {
      const ORDER: Record<string, number> = { new: 0, increased: 1, decreased: 2, unchanged: 3 };
      rows = [...rows].sort((a, b) => (ORDER[a.change] ?? 9) - (ORDER[b.change] ?? 9));
    }
    return rows;
  }, [data, changeFilter, sortKey]);

  // Change summary counts
  const changeCounts = useMemo(() => {
    const holdings = data?.holdings ?? [];
    return holdings.reduce(
      (acc, h) => { acc[h.change]++; return acc; },
      { new: 0, increased: 0, decreased: 0, unchanged: 0 } as Record<string, number>
    );
  }, [data]);

  if (!institution) {
    return (
      <div className="p-6">
        <Link href="/portfolio/institutions" className="text-sky-400 text-sm hover:underline">← Back</Link>
        <p className="mt-4 text-slate-400">Institution not found.</p>
      </div>
    );
  }

  const meta = CATEGORY_META[institution.category];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Back */}
      <Link href="/portfolio/institutions" className="text-xs text-slate-500 hover:text-sky-400 transition-colors">
        ← All Institutions
      </Link>

      {/* Institution header */}
      <div className="mt-4 mb-6 flex items-start gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-bold text-slate-100">{institution.name}</h1>
            <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${meta.badgeCls}`}>
              {meta.label}
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">{institution.manager}</p>
          <p className="text-xs text-slate-600 mt-0.5">{institution.description}</p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-slate-600">SEC CIK</p>
          <p className="text-xs font-mono text-slate-500">{institution.cik}</p>
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-16 bg-slate-900 border border-slate-800 rounded-xl animate-pulse" />
            ))}
          </div>
          <div className="h-64 bg-slate-900 border border-slate-800 rounded-xl animate-pulse" />
        </div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div className="bg-rose-500/10 border border-rose-500/25 rounded-xl p-6 text-center">
          <p className="text-rose-400 text-sm font-medium mb-1">Could not load SEC EDGAR data</p>
          <p className="text-rose-400/60 text-xs">{error}</p>
          <button
            onClick={() => doFetch(cik)}
            className="mt-3 text-xs text-rose-400 border border-rose-400/30 rounded px-3 py-1 hover:bg-rose-400/10"
          >
            Retry
          </button>
        </div>
      )}

      {/* Data loaded */}
      {!loading && data && (
        <>
          {/* Stats strip */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">Total Equity Value</p>
              <p className="text-lg font-bold text-slate-100">{fmtMM(data.totalValueMM)}</p>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">Positions</p>
              <p className="text-lg font-bold text-slate-100">{data.positionCount}</p>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">Latest Filing</p>
              <p className="text-lg font-bold text-slate-100">{data.quarter}</p>
              <p className="text-xs text-slate-600">{data.filingDate}</p>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">Prior Quarter</p>
              <p className="text-lg font-bold text-slate-100">{data.prevQuarter ?? "—"}</p>
              {data.prevFilingDate && <p className="text-xs text-slate-600">{data.prevFilingDate}</p>}
            </div>
          </div>

          {/* Concentration + QoQ summary */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            {/* Top 5 bar */}
            <div className="md:col-span-1">
              <ConcentrationBar holdings={data.holdings ?? []} />
            </div>

            {/* QoQ change counts */}
            <div className="md:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-4">
              <h3 className="text-xs font-medium text-slate-400 mb-3 uppercase tracking-wider">
                Quarter-over-Quarter Changes
                {data.prevQuarter && (
                  <span className="normal-case ml-1 text-slate-600">vs {data.prevQuarter}</span>
                )}
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="text-center">
                  <p className="text-2xl font-bold text-emerald-400">{changeCounts.new}</p>
                  <p className="text-xs text-slate-500 mt-0.5">New Positions</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-sky-400">{changeCounts.increased}</p>
                  <p className="text-xs text-slate-500 mt-0.5">Increased</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-rose-400">{changeCounts.decreased}</p>
                  <p className="text-xs text-slate-500 mt-0.5">Decreased</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-slate-400">{changeCounts.unchanged}</p>
                  <p className="text-xs text-slate-500 mt-0.5">Unchanged</p>
                </div>
              </div>
            </div>
          </div>

          {/* Holdings table */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            {/* Table header + filters */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-800 flex-wrap">
              <span className="text-sm font-semibold text-slate-200">All Holdings</span>
              <span className="text-xs text-slate-600">({filtered.length})</span>

              {/* Change filter chips */}
              <div className="flex gap-1 ml-auto flex-wrap">
                {(["all", "new", "increased", "decreased", "unchanged"] as ChangeFilter[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => setChangeFilter(f)}
                    className={`text-xs px-2.5 py-1 rounded-full border transition-all capitalize ${
                      changeFilter === f
                        ? "bg-slate-700 border-slate-600 text-slate-100"
                        : "border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-700"
                    }`}
                  >
                    {f === "all" ? `All (${data.positionCount})` : `${f} (${changeCounts[f] ?? 0})`}
                  </button>
                ))}
              </div>

              {/* Sort */}
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as typeof sortKey)}
                className="text-xs bg-slate-800 border border-slate-700 text-slate-300 rounded px-2 py-1"
              >
                <option value="rank">Sort: By Value</option>
                <option value="change">Sort: By Change</option>
              </select>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500">
                    <th className="text-left px-4 py-2 font-medium w-8">#</th>
                    <th className="text-left px-4 py-2 font-medium">Company</th>
                    <th className="text-left px-3 py-2 font-medium hidden md:table-cell">CUSIP</th>
                    <th className="text-right px-3 py-2 font-medium">Value</th>
                    <th className="text-right px-3 py-2 font-medium">Portfolio %</th>
                    <th className="text-right px-3 py-2 font-medium hidden lg:table-cell">Shares</th>
                    <th className="text-center px-3 py-2 font-medium">QoQ Change</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={7} className="text-center py-8 text-slate-600">
                        No holdings match this filter
                      </td>
                    </tr>
                  )}
                  {filtered.map((h) => (
                    <tr key={h.cusip} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-2.5 text-slate-600 w-8">{h.rank}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          {/* mini % bar */}
                          <div className="w-12 shrink-0 hidden sm:block">
                            <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
                              <div
                                className="h-full rounded-full bg-sky-500/50"
                                style={{ width: `${Math.min(h.pctPortfolio * 3, 100)}%` }}
                              />
                            </div>
                          </div>
                          <span className="text-slate-200 font-medium truncate max-w-[160px] md:max-w-none">
                            {h.name}
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-slate-600 hidden md:table-cell">
                        {h.cusip}
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-200 font-medium">
                        {fmtMM(h.valueMM)}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <span className="text-slate-300">{h.pctPortfolio.toFixed(2)}%</span>
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-500 hidden lg:table-cell">
                        {fmtShares(h.shares)}
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <ChangePill change={h.change} pct={h.changePctShares} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Footer */}
            <div className="px-4 py-2 border-t border-slate-800 text-xs text-slate-700 flex justify-between">
              <span>13F-HR filed {data.filingDate} · Values in USD thousands as reported</span>
              <a
                href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${institution.cik}&type=13F-HR&dateb=&owner=include&count=10`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-600 hover:text-sky-400 transition-colors"
                onClick={(e) => e.stopPropagation()}
              >
                View on EDGAR ↗
              </a>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
