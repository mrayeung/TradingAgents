"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import {
  INSTITUTIONS,
  CATEGORY_META,
  ALL_CATEGORIES,
  type Institution,
  type InstitutionCategory,
} from "@/lib/institutions";
import type { HoldingsPayload, ProcessedHolding } from "@/lib/holdings-types";

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtMM(mm: number): string {
  if (mm >= 1_000_000) return `$${(mm / 1_000_000).toFixed(2)}T`;
  if (mm >= 1_000)     return `$${(mm / 1_000).toFixed(1)}B`;
  return `$${mm}M`;
}

function fmtPct(n: number): string {
  return `${n.toFixed(1)}%`;
}

// ── Change badge ──────────────────────────────────────────────────────────────

function ChangeBadge({ change, pct }: { change: ProcessedHolding["change"]; pct: number | null }) {
  if (change === "new") {
    return <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-400/10 text-emerald-400 border border-emerald-400/20">NEW</span>;
  }
  if (change === "increased") {
    return <span className="text-xs text-emerald-400">↑{pct != null ? ` ${Math.abs(pct).toFixed(0)}%` : ""}</span>;
  }
  if (change === "decreased") {
    return <span className="text-xs text-rose-400">↓{pct != null ? ` ${Math.abs(pct).toFixed(0)}%` : ""}</span>;
  }
  return null;
}

// ── Per-tile state ────────────────────────────────────────────────────────────

interface TileState {
  loading: boolean;
  error: boolean;
  data: HoldingsPayload | null;
}

// In-memory cache so navigating back doesn't re-hit SEC EDGAR
const _cache = new Map<string, HoldingsPayload>();

function useTileData(id: string, delayMs = 0): TileState {
  const [state, setState] = useState<TileState>({
    loading: !_cache.has(id),
    error: false,
    data: _cache.get(id) ?? null,
  });

  useEffect(() => {
    if (_cache.has(id)) return; // already cached — nothing to fetch
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const r = await fetch(`/api/institutions/${id}`, { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json() as HoldingsPayload;
        _cache.set(id, data);
        if (!cancelled) setState({ loading: false, error: false, data });
      } catch {
        if (!cancelled) setState({ loading: false, error: true, data: null });
      }
    }, delayMs);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [id, delayMs]);

  return state;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function TileSkeleton() {
  return (
    <div className="animate-pulse space-y-2">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="flex items-center justify-between">
          <div className="h-3 bg-slate-700 rounded w-32" />
          <div className="h-3 bg-slate-700 rounded w-10" />
        </div>
      ))}
    </div>
  );
}

// ── Institution tile ──────────────────────────────────────────────────────────

function InstitutionTile({ institution, index }: { institution: Institution; index: number }) {
  const { loading, error, data } = useTileData(institution.id, index * 300);
  const meta = CATEGORY_META[institution.category];
  const top5 = data?.holdings.slice(0, 5) ?? [];

  return (
    <Link href={`/portfolio/institutions/${institution.id}`}>
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 hover:border-slate-600 hover:bg-slate-800/50 transition-all cursor-pointer group h-full flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between gap-2 mb-1">
          <div>
            <h3 className="text-sm font-semibold text-slate-100 group-hover:text-sky-400 transition-colors leading-tight">
              {institution.name}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">{institution.manager}</p>
          </div>
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium whitespace-nowrap shrink-0 ${meta.badgeCls}`}>
            {meta.label}
          </span>
        </div>

        {/* Stats row */}
        {data && (
          <div className="flex items-center gap-3 mb-3 mt-1">
            <span className="text-xs font-semibold text-slate-200">{fmtMM(data.totalValueMM)}</span>
            <span className="text-xs text-slate-500">{data.positionCount} positions</span>
            <span className="text-xs text-slate-600 ml-auto">{data.quarter}</span>
          </div>
        )}
        {!data && !loading && (
          <div className="text-xs text-slate-600 mb-3 mt-1">—</div>
        )}
        {loading && (
          <div className="h-3 w-24 bg-slate-700 rounded animate-pulse mb-3 mt-1" />
        )}

        {/* Top 5 holdings */}
        <div className="flex-1 space-y-1.5">
          {loading && <TileSkeleton />}
          {error && (
            <p className="text-xs text-slate-600 italic">SEC data unavailable</p>
          )}
          {!loading && !error && top5.map((h) => (
            <div key={h.cusip} className="flex items-center gap-2">
              {/* % bar */}
              <div className="w-[60px] shrink-0">
                <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-sky-500/60"
                    style={{ width: `${Math.min(h.pctPortfolio * 2, 100)}%` }}
                  />
                </div>
              </div>
              {/* Name */}
              <span className="text-xs text-slate-300 flex-1 truncate">{h.name}</span>
              {/* Pct */}
              <span className="text-xs text-slate-400 shrink-0">{fmtPct(h.pctPortfolio)}</span>
              {/* Change */}
              <div className="shrink-0 w-14 text-right">
                <ChangeBadge change={h.change} pct={h.changePctShares} />
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="mt-3 pt-2 border-t border-slate-800 text-xs text-slate-600 group-hover:text-sky-500 transition-colors">
          View full portfolio →
        </div>
      </div>
    </Link>
  );
}

// ── Category filter tabs ──────────────────────────────────────────────────────

const TABS: { id: "all" | InstitutionCategory; label: string }[] = [
  { id: "all",           label: "All" },
  { id: "star",          label: "Star Investors" },
  { id: "hedge_fund",    label: "Hedge Funds" },
  { id: "tech_growth",   label: "Tech / Growth" },
  { id: "asset_manager", label: "Asset Managers" },
];

// ── Page ──────────────────────────────────────────────────────────────────────

export default function InstitutionsPage() {
  const [activeTab, setActiveTab] = useState<"all" | InstitutionCategory>("all");

  const visible =
    activeTab === "all"
      ? INSTITUTIONS
      : INSTITUTIONS.filter((i) => i.category === activeTab);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Institutional Portfolios</h1>
        <p className="text-sm text-slate-500 mt-1">
          Live 13F-HR holdings from SEC EDGAR · updated quarterly
        </p>
      </div>

      {/* Category tabs */}
      <div className="flex gap-1 mb-6 bg-slate-900 border border-slate-800 rounded-lg p-1 w-fit">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${
              activeTab === tab.id
                ? "bg-slate-700 text-slate-100"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Summary count */}
      <p className="text-xs text-slate-600 mb-4">
        {visible.length} institution{visible.length !== 1 ? "s" : ""}
      </p>

      {/* Tile grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {visible.map((inst, i) => (
          <InstitutionTile key={inst.id} institution={inst} index={i} />
        ))}
      </div>

      {/* Footer note */}
      <p className="mt-8 text-xs text-slate-700 text-center">
        13F filings are required for institutions managing &gt;$100M in qualifying securities.
        Holdings reported 45 days after each quarter-end.
      </p>
    </div>
  );
}
