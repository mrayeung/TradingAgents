"use client";

import { useState, useEffect, useRef, useCallback } from "react";

/* ════════════════════════════════════════════════════════════════════════════
   TYPES
════════════════════════════════════════════════════════════════════════════ */
type FactorTier = "green" | "amber" | "sky";

interface Factor {
  name: string;
  val: number; // 0–100
  tier: FactorTier;
}

interface Pair {
  id: string;
  ticker: string;
  sector: string;
  score: number; // 0–100 composite
  corr: number;
  cointP: number;
  halflife: number;
  zScore: number;
  beta: number;
  rSquared: number;
  leg1: string;
  leg2: string;
  action1: "LONG" | "SHORT";
  action2: "LONG" | "SHORT";
  entryZ: number;
  exitZ: number;
  stopZ: number;
  factors: Factor[];
  spread: number[]; // 252 OU-simulated z-values
  thesis: string;
}

/* ════════════════════════════════════════════════════════════════════════════
   ORNSTEIN-UHLENBECK SPREAD SIMULATOR
   Generates a realistic mean-reverting spread series terminating at zScore.
════════════════════════════════════════════════════════════════════════════ */
function genSpread(targetZ: number, n = 252, seed = 42): number[] {
  // xorshift pseudo-rng for deterministic output per pair
  let s = seed;
  const rand = () => {
    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    return (s >>> 0) / 4294967296;
  };
  const randn = () => {
    const u = rand() || 1e-10;
    const v = rand();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };

  const arr: number[] = [];
  let z = 0;
  for (let i = 0; i < n; i++) {
    const meanRev = -0.08 * z;
    z += meanRev + randn() * 0.35;
    arr.push(z);
  }
  // Smoothly guide the last 15% of the series toward targetZ
  const bp = Math.floor(n * 0.85);
  for (let i = bp; i < n; i++) {
    const t = (i - bp) / (n - bp);
    arr[i] = arr[i] * (1 - t) + targetZ * t;
  }
  arr[n - 1] = targetZ;
  return arr;
}

/* ════════════════════════════════════════════════════════════════════════════
   SYNTHETIC PAIR DATABASE
════════════════════════════════════════════════════════════════════════════ */
const RAW: Omit<Pair, "spread">[] = [
  {
    id: "xom-cvx",
    ticker: "XOM / CVX",
    sector: "Energy",
    score: 92,
    corr: 0.94,
    cointP: 0.012,
    halflife: 8,
    zScore: 2.31,
    beta: 0.87,
    rSquared: 0.88,
    leg1: "XOM",
    leg2: "CVX",
    action1: "LONG",
    action2: "SHORT",
    entryZ: 2.0,
    exitZ: 0.5,
    stopZ: 3.5,
    factors: [
      { name: "Cointegration",      val: 97, tier: "green" },
      { name: "OU Half-Life",       val: 88, tier: "green" },
      { name: "Correlation",        val: 94, tier: "green" },
      { name: "Kalman β Stability", val: 82, tier: "sky"   },
      { name: "Liquidity Match",    val: 91, tier: "green" },
      { name: "Regime Score",       val: 75, tier: "amber" },
    ],
    thesis:
      "XOM/CVX — Classic integrated major pair sharing near-identical upstream cost structures and refinery economics. " +
      "Current spread at +2.31σ driven by XOM downstream margin pressure vs CVX Permian outperformance. " +
      "Cointegration confirmed at p=0.012 over 252-day window — statistically robust. " +
      "Half-life of 8 days implies rapid mean-reversion consistent with Medallion's short-duration targets. " +
      "Kalman hedge ratio β=0.87, stable over trailing 90 sessions.\n\n" +
      "▸ ENTRY: Long XOM / Short CVX in 87:100 ratio at current spread ≥ +2.0σ\n" +
      "▸ TARGET: Exit at spread ≤ +0.5σ · Hard stop at +3.5σ\n" +
      "▸ EXPECTED HOLD: 4–10 trading days\n" +
      "▸ RISK-ADJUSTED RETURN: Est. 0.9–1.4% net per leg",
  },
  {
    id: "wmt-tgt",
    ticker: "WMT / TGT",
    sector: "Consumer",
    score: 86,
    corr: 0.88,
    cointP: 0.027,
    halflife: 14,
    zScore: -2.18,
    beta: 0.93,
    rSquared: 0.77,
    leg1: "TGT",
    leg2: "WMT",
    action1: "LONG",
    action2: "SHORT",
    entryZ: -2.0,
    exitZ: -0.5,
    stopZ: -3.2,
    factors: [
      { name: "Cointegration",      val: 89, tier: "green" },
      { name: "OU Half-Life",       val: 83, tier: "green" },
      { name: "Correlation",        val: 88, tier: "green" },
      { name: "Kalman β Stability", val: 79, tier: "amber" },
      { name: "Liquidity Match",    val: 86, tier: "green" },
      { name: "Regime Score",       val: 74, tier: "amber" },
    ],
    thesis:
      "WMT/TGT — Classic big-box retail pair. Spread at -2.18σ — ENTRY TRIGGERED.\n\n" +
      "WMT's grocery market-share gains and international business have driven a structural premium " +
      "vs TGT's discretionary mix headwinds and margin pressure. Both face identical macro forces — " +
      "structural reversion expected. Cointegration p=0.027, half-life 14 days. β=0.93 — near dollar-neutral.\n\n" +
      "▸ EXECUTE: Long TGT / Short WMT · Size 93:100 ratio\n" +
      "▸ TARGET: Exit at -0.5σ (~8–12 days)\n" +
      "▸ STOP: -3.2σ\n" +
      "▸ ANALOG: 7 comparable setups (5yr) · 6 profitable · Avg P&L: +1.1% net",
  },
  {
    id: "jpm-bac",
    ticker: "JPM / BAC",
    sector: "Financials",
    score: 88,
    corr: 0.91,
    cointP: 0.021,
    halflife: 12,
    zScore: -1.87,
    beta: 1.04,
    rSquared: 0.83,
    leg1: "JPM",
    leg2: "BAC",
    action1: "SHORT",
    action2: "LONG",
    entryZ: -2.0,
    exitZ: -0.5,
    stopZ: -3.5,
    factors: [
      { name: "Cointegration",      val: 91, tier: "green" },
      { name: "OU Half-Life",       val: 79, tier: "amber" },
      { name: "Correlation",        val: 91, tier: "green" },
      { name: "Kalman β Stability", val: 88, tier: "green" },
      { name: "Liquidity Match",    val: 95, tier: "green" },
      { name: "Regime Score",       val: 71, tier: "amber" },
    ],
    thesis:
      "JPM/BAC — Core money-center bank pair driven by identical rate sensitivity and credit cycle exposure. " +
      "Current spread at -1.87σ, approaching entry threshold.\n\n" +
      "JPM elevated NIM vs BAC commercial real estate drag has widened the spread; structural reversion " +
      "likely as CRE overhang prices in. Engle-Granger cointegration p=0.021. Half-life 12 days. " +
      "β=1.04 (near unity) simplifies sizing — approximately dollar-neutral.\n\n" +
      "▸ WATCH: Set alert at z ≤ -2.0σ for entry trigger\n" +
      "▸ SETUP: Short JPM / Long BAC\n" +
      "▸ TARGET: -0.5σ · STOP: -3.5σ\n" +
      "▸ ESTIMATED HOLD: 8–15 trading days · Sharpe on historicals: ~1.8",
  },
  {
    id: "nvda-amd",
    ticker: "NVDA / AMD",
    sector: "Technology",
    score: 82,
    corr: 0.87,
    cointP: 0.031,
    halflife: 11,
    zScore: 2.44,
    beta: 1.21,
    rSquared: 0.76,
    leg1: "NVDA",
    leg2: "AMD",
    action1: "SHORT",
    action2: "LONG",
    entryZ: 2.0,
    exitZ: 0.5,
    stopZ: 3.5,
    factors: [
      { name: "Cointegration",      val: 87, tier: "green" },
      { name: "OU Half-Life",       val: 85, tier: "green" },
      { name: "Correlation",        val: 87, tier: "green" },
      { name: "Kalman β Stability", val: 69, tier: "amber" },
      { name: "Liquidity Match",    val: 88, tier: "green" },
      { name: "Regime Score",       val: 72, tier: "amber" },
    ],
    thesis:
      "NVDA/AMD — Semiconductor pair driven by identical AI accelerator demand tailwinds but diverging " +
      "execution and pricing power. Spread at +2.44σ — ENTRY TRIGGERED.\n\n" +
      "NVDA HBM supply constraints and premium pricing vs AMD MI300X ramp at discount is the " +
      "fundamental driver. Cointegration p=0.031, half-life 11 days — rapid reversion expected. " +
      "β=1.21 — size NVDA short at ~83% of AMD long notional.\n\n" +
      "▸ ENTRY: Short NVDA / Long AMD · Size 83:100\n" +
      "▸ TARGET: +0.5σ (~5–9 days) · STOP: +3.5σ\n" +
      "▸ NOTE: High-beta pair — reduce to 0.7x normal unit in elevated vol regimes",
  },
  {
    id: "gld-slv",
    ticker: "GLD / SLV",
    sector: "Commodities ETF",
    score: 84,
    corr: 0.89,
    cointP: 0.034,
    halflife: 19,
    zScore: 2.67,
    beta: 0.52,
    rSquared: 0.79,
    leg1: "SLV",
    leg2: "GLD",
    action1: "LONG",
    action2: "SHORT",
    entryZ: 2.0,
    exitZ: 0.5,
    stopZ: 3.8,
    factors: [
      { name: "Cointegration",      val: 85, tier: "green" },
      { name: "OU Half-Life",       val: 68, tier: "amber" },
      { name: "Correlation",        val: 89, tier: "green" },
      { name: "Kalman β Stability", val: 74, tier: "amber" },
      { name: "Liquidity Match",    val: 88, tier: "green" },
      { name: "Regime Score",       val: 80, tier: "sky"   },
    ],
    thesis:
      "GLD/SLV (Gold-Silver Ratio) — The gold/silver ratio is a canonical mean-reverting spread. " +
      "Currently at extreme +2.67σ on 252-day lookback.\n\n" +
      "Industrial demand for silver (solar panel manufacturing surge) vs gold defensive bid has " +
      "compressed the ratio to a historically stretched level. Half-life of 19 days is longer than " +
      "ideal but within criteria. β=0.52 — size SLV leg ~2:1 relative to GLD notional.\n\n" +
      "▸ ENTRY: Long SLV / Short GLD at ≥ +2.0σ\n" +
      "▸ TARGET: Spread convergence toward historical ~80:1 ratio · STOP: +3.8σ\n" +
      "▸ SIZING: Higher vol warrants 0.5x normal unit — reduce for safety",
  },
  {
    id: "msft-googl",
    ticker: "MSFT / GOOGL",
    sector: "Technology",
    score: 79,
    corr: 0.86,
    cointP: 0.048,
    halflife: 22,
    zScore: 1.54,
    beta: 0.79,
    rSquared: 0.74,
    leg1: "MSFT",
    leg2: "GOOGL",
    action1: "LONG",
    action2: "SHORT",
    entryZ: 2.0,
    exitZ: 0.5,
    stopZ: 3.0,
    factors: [
      { name: "Cointegration",      val: 78, tier: "amber" },
      { name: "OU Half-Life",       val: 62, tier: "amber" },
      { name: "Correlation",        val: 86, tier: "green" },
      { name: "Kalman β Stability", val: 71, tier: "amber" },
      { name: "Liquidity Match",    val: 90, tier: "green" },
      { name: "Regime Score",       val: 68, tier: "amber" },
    ],
    thesis:
      "MSFT/GOOGL — Mega-cap tech pair with strong structural linkage through cloud (Azure vs GCP) " +
      "and AI infrastructure spend. Current z-score at +1.54σ — not yet at entry threshold.\n\n" +
      "GOOGL ad revenue softness vs MSFT enterprise cloud momentum created the divergence. " +
      "Cointegration marginally passes at p=0.048 — borderline. Half-life 22 days at upper bound.\n\n" +
      "▸ WATCH: Set alert at z ≥ +2.0σ for entry trigger\n" +
      "▸ SETUP: Long MSFT / Short GOOGL · β=0.79 · Size 79:100\n" +
      "▸ STOP: +3.0σ · Check regime score before entering (moderate conviction only)",
  },
];

const PAIRS: Pair[] = RAW.map((p, i) => ({
  ...p,
  spread: genSpread(p.zScore, 252, 100 + i * 37),
}));

const SECTORS = [
  "All Sectors",
  "Energy",
  "Technology",
  "Financials",
  "Consumer",
  "Commodities ETF",
];

/* ════════════════════════════════════════════════════════════════════════════
   HELPERS
════════════════════════════════════════════════════════════════════════════ */
const FACTOR_COLORS: Record<FactorTier, string> = {
  green: "#10b981",
  amber: "#f59e0b",
  sky: "#38bdf8",
};

function isEntry(z: number, threshold = 2.0) {
  return Math.abs(z) >= threshold;
}

function zTextColor(z: number) {
  if (Math.abs(z) >= 2) return z > 0 ? "text-emerald-400" : "text-rose-400";
  return "text-amber-400";
}

function scoreColor(s: number) {
  if (s >= 85) return "#10b981";
  if (s >= 75) return "#f59e0b";
  return "#ef4444";
}

/* ════════════════════════════════════════════════════════════════════════════
   SCORE RING
════════════════════════════════════════════════════════════════════════════ */
function ScoreRing({ score }: { score: number }) {
  const R = 20;
  const circ = 2 * Math.PI * R;
  const fill = (score / 100) * circ;
  const color = scoreColor(score);

  return (
    <div className="relative w-12 h-12 shrink-0">
      <svg
        className="w-12 h-12 -rotate-90"
        viewBox="0 0 48 48"
        xmlns="http://www.w3.org/2000/svg"
      >
        <circle
          cx="24"
          cy="24"
          r={R}
          fill="none"
          stroke="rgba(51,65,85,0.8)"
          strokeWidth="3.5"
        />
        <circle
          cx="24"
          cy="24"
          r={R}
          fill="none"
          stroke={color}
          strokeWidth="3.5"
          strokeDasharray={`${fill} ${circ}`}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-[12px] font-bold text-white leading-none">
          {score}
        </span>
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   PAIR LIST ITEM
════════════════════════════════════════════════════════════════════════════ */
function PairItem({
  pair,
  active,
  onClick,
}: {
  pair: Pair;
  active: boolean;
  onClick: () => void;
}) {
  const sign = pair.zScore >= 0 ? "+" : "";
  const entry = isEntry(pair.zScore);

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3.5 border-b border-slate-800/70 transition-all hover:bg-slate-800/25 ${
        active
          ? "bg-slate-800/50 border-l-[2px] border-l-sky-500 pl-[14px]"
          : "border-l-[2px] border-l-transparent"
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className="text-white font-semibold text-sm leading-tight">
          {pair.ticker}
        </span>
        <ScoreRing score={pair.score} />
      </div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-slate-500 text-[10px]">{pair.sector}</span>
        {entry && (
          <span className="text-[8px] font-bold px-1.5 py-px rounded-full bg-emerald-900/50 text-emerald-400 border border-emerald-800 leading-none">
            ENTRY
          </span>
        )}
        {!entry && Math.abs(pair.zScore) >= 1.5 && (
          <span className="text-[8px] font-bold px-1.5 py-px rounded-full bg-amber-900/40 text-amber-400 border border-amber-800/60 leading-none">
            WATCH
          </span>
        )}
      </div>
      <div className="flex gap-3 text-[10px] font-mono text-slate-500">
        <span>
          Z:{" "}
          <span className={`font-bold ${zTextColor(pair.zScore)}`}>
            {sign}
            {pair.zScore.toFixed(2)}σ
          </span>
        </span>
        <span>ρ: {pair.corr.toFixed(2)}</span>
        <span>HL: {pair.halflife}d</span>
        <span>p: {pair.cointP.toFixed(3)}</span>
      </div>
    </button>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   SPREAD CANVAS CHART
════════════════════════════════════════════════════════════════════════════ */
function SpreadChart({ pair }: { pair: Pair }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const dpr = window.devicePixelRatio || 1;
    const W = container.clientWidth;
    const H = 140;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    const data = pair.spread;
    const rawMin = Math.min(...data);
    const rawMax = Math.max(...data);
    const margin = (rawMax - rawMin) * 0.1;
    const mn = rawMin - margin;
    const mx = rawMax + margin;

    const pad = { t: 10, b: 22, l: 36, r: 10 };
    const cw = W - pad.l - pad.r;
    const ch = H - pad.t - pad.b;
    const toX = (i: number) => pad.l + (i / (data.length - 1)) * cw;
    const toY = (v: number) => pad.t + (1 - (v - mn) / (mx - mn)) * ch;

    // Background bands
    const p2Y = toY(Math.max(mn, Math.min(mx, 2)));
    const n2Y = toY(Math.max(mn, Math.min(mx, -2)));
    ctx.fillStyle = "rgba(16,185,129,0.04)";
    ctx.fillRect(pad.l, pad.t, cw, Math.max(0, p2Y - pad.t));
    ctx.fillStyle = "rgba(239,68,68,0.04)";
    ctx.fillRect(pad.l, n2Y, cw, Math.max(0, pad.t + ch - n2Y));

    // Axis grid
    ctx.strokeStyle = "rgba(51,65,85,0.4)";
    ctx.lineWidth = 0.5;
    ctx.setLineDash([3, 6]);
    const gridYs = [-3, -2, -1, 0, 1, 2, 3];
    gridYs.forEach((z) => {
      if (z < mn || z > mx) return;
      const y = toY(z);
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + cw, y);
      ctx.stroke();
    });
    ctx.setLineDash([]);

    // Reference line labels
    const refLines = [
      { z: -2, color: "rgba(239,68,68,0.6)", label: "-2σ" },
      { z: 0, color: "rgba(100,116,139,0.6)", label: "0" },
      { z: 2, color: "rgba(16,185,129,0.6)", label: "+2σ" },
    ];
    refLines.forEach(({ z, color, label }) => {
      if (z < mn || z > mx) return;
      const y = toY(z);
      ctx.strokeStyle = color;
      ctx.lineWidth = z === 0 ? 1 : 0.8;
      ctx.setLineDash(z === 0 ? [] : [4, 4]);
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + cw, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(148,163,184,0.65)";
      ctx.font = `9px ui-monospace, SFMono-Regular, monospace`;
      ctx.textAlign = "right";
      ctx.fillText(label, pad.l - 4, y + 3);
    });

    // Area fill under the spread line
    const areaGrad = ctx.createLinearGradient(0, pad.t, 0, pad.t + ch);
    areaGrad.addColorStop(0, "rgba(56,189,248,0.12)");
    areaGrad.addColorStop(1, "rgba(56,189,248,0.01)");
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = toX(i);
      const y = toY(v);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.lineTo(toX(data.length - 1), toY(0));
    ctx.lineTo(pad.l, toY(0));
    ctx.closePath();
    ctx.fillStyle = areaGrad;
    ctx.fill();

    // Spread line — gradient by zone
    const lineGrad = ctx.createLinearGradient(pad.l, pad.t, pad.l, pad.t + ch);
    lineGrad.addColorStop(0, "#10b981");
    lineGrad.addColorStop(0.4, "#38bdf8");
    lineGrad.addColorStop(0.6, "#38bdf8");
    lineGrad.addColorStop(1, "#ef4444");
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = toX(i);
      const y = toY(v);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = lineGrad;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Current value dot + glow
    const lx = toX(data.length - 1);
    const ly = toY(data[data.length - 1]);
    ctx.beginPath();
    ctx.arc(lx, ly, 5, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(56,189,248,0.2)";
    ctx.fill();
    ctx.beginPath();
    ctx.arc(lx, ly, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = "#38bdf8";
    ctx.fill();
    ctx.strokeStyle = "rgba(2,6,23,0.8)";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Z label next to current dot
    const sign = pair.zScore >= 0 ? "+" : "";
    const zLabel = `${sign}${pair.zScore.toFixed(2)}σ`;
    ctx.font = `bold 10px ui-monospace, SFMono-Regular, monospace`;
    ctx.fillStyle = "#38bdf8";
    ctx.textAlign = lx > W - 60 ? "right" : "left";
    ctx.fillText(zLabel, lx + (lx > W - 60 ? -10 : 10), ly - 8);

    // X-axis labels
    const xLabels = ["252d ago", "180d", "90d", "Today"];
    ctx.fillStyle = "rgba(100,116,139,0.5)";
    ctx.font = `9px ui-monospace, SFMono-Regular, monospace`;
    ctx.textAlign = "center";
    xLabels.forEach((l, i) => {
      ctx.fillText(l, pad.l + (i / 3) * cw, H - 5);
    });
  }, [pair]);

  return (
    <div ref={containerRef} className="w-full">
      <canvas ref={canvasRef} className="block w-full" />
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   FACTOR BARS
════════════════════════════════════════════════════════════════════════════ */
function FactorBars({ factors }: { factors: Factor[] }) {
  const [go, setGo] = useState(false);

  useEffect(() => {
    setGo(false);
    const t = setTimeout(() => setGo(true), 60);
    return () => clearTimeout(t);
  }, [factors]);

  return (
    <div className="space-y-2.5">
      {factors.map((f) => (
        <div key={f.name} className="flex items-center gap-3">
          <div className="text-slate-400 text-[10px] w-36 shrink-0 leading-tight">
            {f.name}
          </div>
          <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700 ease-out"
              style={{
                width: go ? `${f.val}%` : "0%",
                backgroundColor: FACTOR_COLORS[f.tier],
                boxShadow: go
                  ? `0 0 6px ${FACTOR_COLORS[f.tier]}60`
                  : "none",
              }}
            />
          </div>
          <div className="text-[10px] font-mono text-slate-300 w-7 text-right">
            {f.val}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   Z-SCORE METER
════════════════════════════════════════════════════════════════════════════ */
function ZMeter({ pair }: { pair: Pair }) {
  const [go, setGo] = useState(false);
  useEffect(() => {
    setGo(false);
    const t = setTimeout(() => setGo(true), 120);
    return () => clearTimeout(t);
  }, [pair.id]);

  const z = pair.zScore;
  const pct = Math.max(2, Math.min(98, ((z + 4) / 8) * 100));
  const sign = z >= 0 ? "+" : "";
  const entry = isEntry(z);

  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-3.5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[9px] text-slate-500 uppercase tracking-widest">
          Z-Score Position
        </span>
        <div className="flex items-center gap-2">
          <span className={`font-mono font-bold text-sm ${zTextColor(z)}`}>
            {sign}
            {z.toFixed(2)}σ
          </span>
          <span
            className={`text-[8px] font-bold px-2 py-0.5 rounded-full border leading-none ${
              entry
                ? "text-emerald-400 border-emerald-700 bg-emerald-900/30"
                : "text-amber-400 border-amber-700 bg-amber-900/25"
            }`}
          >
            {entry ? "✓ ENTRY" : "◎ WATCH"}
          </span>
        </div>
      </div>

      {/* Track */}
      <div
        className="relative h-6 rounded overflow-hidden"
        style={{
          background:
            "linear-gradient(90deg, rgba(239,68,68,0.4) 0%, rgba(239,68,68,0.15) 20%, rgba(30,41,59,0.6) 30%, rgba(30,41,59,0.6) 70%, rgba(16,185,129,0.15) 80%, rgba(16,185,129,0.4) 100%)",
          border: "1px solid rgba(51,65,85,0.7)",
        }}
      >
        {/* Entry threshold markers */}
        <div
          className="absolute top-0 bottom-0 w-px"
          style={{ left: "25%", background: "rgba(239,68,68,0.45)" }}
        />
        <div
          className="absolute top-0 bottom-0 w-px"
          style={{ left: "75%", background: "rgba(16,185,129,0.45)" }}
        />
        {/* Centre */}
        <div
          className="absolute top-0 bottom-0 w-px"
          style={{ left: "50%", background: "rgba(100,116,139,0.35)" }}
        />
        {/* Needle */}
        <div
          className="absolute top-1 bottom-1 w-0.5 rounded-full transition-all duration-700 ease-out"
          style={{
            left: go ? `${pct}%` : "50%",
            transform: "translateX(-50%)",
            background: "#38bdf8",
            boxShadow: "0 0 8px #38bdf8, 0 0 2px #fff",
          }}
        />
      </div>

      <div className="flex justify-between text-[8px] text-slate-600 mt-1.5 px-px">
        {["-4σ", "-2σ", "0", "+2σ", "+4σ"].map((l) => (
          <span key={l}>{l}</span>
        ))}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   TRADE SETUP GRID
════════════════════════════════════════════════════════════════════════════ */
function TradeSetup({ pair }: { pair: Pair }) {
  const items = [
    {
      label: `${pair.leg1} Leg`,
      value: pair.action1,
      cls: pair.action1 === "LONG" ? "text-emerald-400" : "text-rose-400",
    },
    {
      label: `${pair.leg2} Leg`,
      value: pair.action2,
      cls: pair.action2 === "LONG" ? "text-emerald-400" : "text-rose-400",
    },
    {
      label: "Entry Threshold",
      value:
        (pair.entryZ >= 0 ? "+" : "") + pair.entryZ.toFixed(1) + "σ",
      cls: "text-sky-400",
    },
    {
      label: "Exit Target",
      value:
        (pair.exitZ >= 0 ? "+" : "") + pair.exitZ.toFixed(1) + "σ",
      cls: "text-sky-400",
    },
    {
      label: "Stop Loss",
      value:
        (pair.stopZ >= 0 ? "+" : "") + pair.stopZ.toFixed(1) + "σ",
      cls: "text-rose-400",
    },
    {
      label: "OU Half-Life",
      value: `${pair.halflife}d`,
      cls: "text-slate-200",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-2">
      {items.map((item) => (
        <div
          key={item.label}
          className="bg-slate-800/50 border border-slate-700/40 rounded-lg p-2.5"
        >
          <div className="text-[8px] text-slate-500 uppercase tracking-wider mb-1.5">
            {item.label}
          </div>
          <div className={`font-mono font-bold text-sm ${item.cls}`}>
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   STATISTICAL SUMMARY TABLE
════════════════════════════════════════════════════════════════════════════ */
function StatTable({ pair }: { pair: Pair }) {
  const entry = isEntry(pair.zScore);

  const rows = [
    {
      metric: "Engle-Granger p-value",
      value: pair.cointP.toFixed(3),
      threshold: "< 0.05",
      badge: "PASS",
      badgeCls: "text-emerald-400 bg-emerald-900/30 border-emerald-800",
      method: "Cointegration Test",
    },
    {
      metric: "Pearson Correlation ρ",
      value: pair.corr.toFixed(2),
      threshold: "> 0.80",
      badge: pair.corr >= 0.80 ? "PASS" : "WARN",
      badgeCls:
        pair.corr >= 0.80
          ? "text-emerald-400 bg-emerald-900/30 border-emerald-800"
          : "text-amber-400 bg-amber-900/30 border-amber-800",
      method: "252-Day Rolling",
    },
    {
      metric: "OU Half-Life",
      value: `${pair.halflife}d`,
      threshold: "< 30d",
      badge: pair.halflife <= 30 ? "PASS" : "LONG",
      badgeCls:
        pair.halflife <= 30
          ? "text-emerald-400 bg-emerald-900/30 border-emerald-800"
          : "text-amber-400 bg-amber-900/30 border-amber-800",
      method: "Ornstein-Uhlenbeck",
    },
    {
      metric: "Current Z-Score",
      value: (pair.zScore >= 0 ? "+" : "") + pair.zScore.toFixed(2) + "σ",
      threshold: "≥ |2.0|",
      badge: entry ? "ENTRY" : "WATCH",
      badgeCls: entry
        ? "text-emerald-400 bg-emerald-900/30 border-emerald-800"
        : "text-amber-400 bg-amber-900/30 border-amber-800",
      method: "Kalman Spread",
    },
    {
      metric: "Kalman Hedge Ratio β",
      value: pair.beta.toFixed(2),
      threshold: "Stable ±0.15",
      badge: "STABLE",
      badgeCls: "text-sky-400 bg-sky-900/30 border-sky-800",
      method: "Kalman Filter",
    },
    {
      metric: "R-Squared",
      value: pair.rSquared.toFixed(2),
      threshold: "> 0.70",
      badge: pair.rSquared >= 0.70 ? "PASS" : "WARN",
      badgeCls:
        pair.rSquared >= 0.70
          ? "text-emerald-400 bg-emerald-900/30 border-emerald-800"
          : "text-amber-400 bg-amber-900/30 border-amber-800",
      method: "OLS Regression",
    },
    {
      metric: "Composite Score",
      value: `${pair.score}/100`,
      threshold: "> 75",
      badge:
        pair.score >= 85 ? "HIGH" : pair.score >= 75 ? "MED" : "LOW",
      badgeCls:
        pair.score >= 85
          ? "text-emerald-400 bg-emerald-900/30 border-emerald-800"
          : pair.score >= 75
          ? "text-amber-400 bg-amber-900/30 border-amber-800"
          : "text-rose-400 bg-rose-900/30 border-rose-800",
      method: "6-Factor Model",
    },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse min-w-[500px]">
        <thead>
          <tr className="border-b border-slate-800">
            {["Metric", "Value", "Threshold", "Status", "Method"].map((h) => (
              <th
                key={h}
                className="text-left px-3 py-2 text-[9px] text-slate-500 uppercase tracking-wider font-medium"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              className="border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors"
            >
              <td className="px-3 py-2.5 text-slate-300">{row.metric}</td>
              <td className="px-3 py-2.5 font-mono text-white font-semibold">
                {row.value}
              </td>
              <td className="px-3 py-2.5 text-slate-500">{row.threshold}</td>
              <td className="px-3 py-2.5">
                <span
                  className={`text-[8px] font-bold px-2 py-0.5 rounded border ${row.badgeCls}`}
                >
                  {row.badge}
                </span>
              </td>
              <td className="px-3 py-2.5 text-slate-600 text-[10px]">
                {row.method}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   STREAMING THESIS
════════════════════════════════════════════════════════════════════════════ */
function ThesisStream({
  text,
  streamKey,
}: {
  text: string;
  streamKey: number;
}) {
  const [displayed, setDisplayed] = useState("");
  const [done, setDone] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setDisplayed("");
    setDone(false);
    let idx = 0;

    if (timerRef.current) clearInterval(timerRef.current);

    timerRef.current = setInterval(() => {
      if (idx >= text.length) {
        setDone(true);
        clearInterval(timerRef.current!);
        return;
      }
      const chunk = text.slice(idx, idx + 3);
      setDisplayed((d) => d + chunk);
      idx += 3;
    }, 10);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [text, streamKey]);

  return (
    <div className="text-slate-300 text-[11px] leading-relaxed font-mono whitespace-pre-wrap">
      {displayed}
      {!done && (
        <span
          className="inline-block w-[7px] h-[13px] bg-sky-400 ml-0.5 align-text-bottom"
          style={{ animation: "thesis-blink 0.9s step-end infinite" }}
        />
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   PERFORMANCE STAT
════════════════════════════════════════════════════════════════════════════ */
function PerfStat({
  label,
  value,
  sub,
  cls,
}: {
  label: string;
  value: string;
  sub: string;
  cls: string;
}) {
  return (
    <div className="px-5 py-4 border-r border-slate-800 last:border-r-0">
      <div className="text-[9px] text-slate-500 uppercase tracking-widest mb-1.5">
        {label}
      </div>
      <div className={`text-xl font-bold font-mono ${cls}`}>{value}</div>
      <div className="text-[9px] text-slate-600 mt-1">{sub}</div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   MAIN PAGE
════════════════════════════════════════════════════════════════════════════ */
export default function PairsPage() {
  // ── Screener state ──────────────────────────────────────────────────────
  const [sector, setSector] = useState("All Sectors");
  const [lookback, setLookback] = useState(252);
  const [zThresh, setZThresh] = useState(2.0);
  const [pLimitIdx, setPLimitIdx] = useState(2); // maps to pValues[2]=0.05
  const [minCorr, setMinCorr] = useState(0.80);
  const [maxHL, setMaxHL] = useState(30);

  const pValues = [0.01, 0.02, 0.05, 0.10, 0.15];
  const pLimit = pValues[pLimitIdx];

  // ── UI state ────────────────────────────────────────────────────────────
  const [running, setRunning] = useState(false);
  const [screened, setScreened] = useState<Pair[]>([]);
  const [selected, setSelected] = useState<Pair | null>(null);
  const [thesisKey, setThesisKey] = useState(0);

  // ── Screener logic ──────────────────────────────────────────────────────
  const runScreener = useCallback(() => {
    if (running) return;
    setRunning(true);
    setSelected(null);
    setScreened([]);

    setTimeout(() => {
      const results = PAIRS.filter((p) => {
        if (sector !== "All Sectors") {
          if (!p.sector.toLowerCase().includes(sector.toLowerCase()))
            return false;
        }
        if (p.corr < minCorr) return false;
        if (p.halflife > maxHL) return false;
        if (p.cointP > pLimit) return false;
        return true;
      }).sort((a, b) => b.score - a.score);

      setScreened(results.length > 0 ? results : [...PAIRS].sort((a, b) => b.score - a.score));
      setRunning(false);
    }, 1500);
  }, [running, sector, minCorr, maxHL, pLimit]);

  function selectPair(p: Pair) {
    setSelected(p);
    setThesisKey((k) => k + 1);
  }

  const entryCount = screened.filter((p) => isEntry(p.zScore, zThresh)).length;
  const avgScore = screened.length
    ? Math.round(screened.reduce((s, p) => s + p.score, 0) / screened.length)
    : 0;

  /* ── Render ─────────────────────────────────────────────────────────────── */
  return (
    <>
      {/* Blink keyframe injected once */}
      <style>{`@keyframes thesis-blink { 50% { opacity: 0; } }`}</style>

      <div className="flex bg-slate-950 overflow-hidden" style={{ height: "100vh" }}>
        {/* ═══ LEFT PANEL — Screener ═══════════════════════════════════════ */}
        <aside className="w-72 shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3.5 border-b border-slate-800">
            <div className="text-slate-200 text-sm font-bold tracking-tight">
              Pair Screener
            </div>
            <div className="text-slate-500 text-[10px] mt-0.5">
              Medallion-inspired stat arb pipeline
            </div>
          </div>

          {/* Controls */}
          <div className="px-4 py-3 space-y-4 border-b border-slate-800 overflow-y-auto">
            {/* Sector */}
            <div>
              <label className="block text-[9px] text-slate-500 uppercase tracking-widest mb-1.5">
                Sector Filter
              </label>
              <select
                value={sector}
                onChange={(e) => setSector(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 text-slate-200 text-xs rounded-md px-2.5 py-1.5 outline-none focus:border-sky-600 transition-colors"
              >
                {SECTORS.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>

            {/* Lookback */}
            <SliderRow
              label="Lookback Window"
              valueLabel={`${lookback}d`}
              min={63}
              max={504}
              step={21}
              value={lookback}
              onChange={setLookback}
            />

            {/* Z-Score Threshold */}
            <SliderRow
              label="Entry Z-Threshold"
              valueLabel={`${zThresh.toFixed(2)}σ`}
              min={100}
              max={350}
              step={25}
              value={Math.round(zThresh * 100)}
              onChange={(v) => setZThresh(v / 100)}
            />

            {/* Cointegration p */}
            <SliderRow
              label="Cointegration p-value"
              valueLabel={`< ${pValues[pLimitIdx].toFixed(2)}`}
              min={0}
              max={4}
              step={1}
              value={pLimitIdx}
              onChange={setPLimitIdx}
            />

            {/* Min Correlation */}
            <SliderRow
              label="Min Correlation"
              valueLabel={`ρ ≥ ${minCorr.toFixed(2)}`}
              min={50}
              max={95}
              step={5}
              value={Math.round(minCorr * 100)}
              onChange={(v) => setMinCorr(v / 100)}
            />

            {/* Max Half-Life */}
            <SliderRow
              label="Max OU Half-Life"
              valueLabel={`${maxHL}d`}
              min={5}
              max={60}
              step={5}
              value={maxHL}
              onChange={setMaxHL}
            />
          </div>

          {/* Run button */}
          <div className="px-4 py-3 border-b border-slate-800">
            <button
              onClick={runScreener}
              disabled={running}
              className={`w-full py-2.5 rounded-lg text-xs font-bold uppercase tracking-widest transition-all duration-200 ${
                running
                  ? "bg-slate-700 text-slate-500 cursor-not-allowed"
                  : "bg-sky-600 hover:bg-sky-500 text-white shadow-lg shadow-sky-950/60 active:scale-[0.98]"
              }`}
            >
              {running ? "⟳  Scanning Universe…" : "⟳  Run Screener"}
            </button>
          </div>

          {/* Results summary bar */}
          {screened.length > 0 && (
            <div className="px-4 py-2 border-b border-slate-800 flex gap-4 text-[10px]">
              <span className="text-slate-500">
                <span className="text-white font-bold">{screened.length}</span>{" "}
                pairs
              </span>
              <span className="text-slate-500">
                <span className="text-emerald-400 font-bold">{entryCount}</span>{" "}
                entry
              </span>
              <span className="text-slate-500">
                avg{" "}
                <span className="text-sky-400 font-bold">{avgScore}</span>
              </span>
            </div>
          )}

          {/* Pair list */}
          <div className="flex-1 overflow-y-auto">
            {!screened.length && !running && (
              <div className="px-4 py-10 text-center text-slate-600 text-xs leading-relaxed">
                Configure parameters above
                <br />
                and run the screener.
              </div>
            )}
            {running && (
              <div className="px-4 py-10 text-center space-y-1.5">
                <div className="text-slate-500 text-[11px]">
                  Running Engle-Granger tests…
                </div>
                <div className="text-slate-700 text-[10px]">
                  OU process · Kalman filter · Z-scores
                </div>
                <div className="flex justify-center mt-3 gap-1">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-sky-600"
                      style={{
                        animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
                      }}
                    />
                  ))}
                </div>
              </div>
            )}
            {screened.map((p) => (
              <PairItem
                key={p.id}
                pair={p}
                active={selected?.id === p.id}
                onClick={() => selectPair(p)}
              />
            ))}
          </div>
        </aside>

        {/* ═══ RIGHT PANEL — Detail ════════════════════════════════════════ */}
        <div className="flex-1 overflow-y-auto">
          {/* Engine banner */}
          <div className="px-6 py-4 border-b border-slate-800 bg-gradient-to-r from-violet-950/20 via-slate-950 to-slate-950">
            <div className="flex items-baseline gap-2">
              <span className="text-sky-400 font-bold text-base tracking-tight">
                Renaissance
              </span>
              <span className="text-white font-bold text-base tracking-tight">
                Statistical Arbitrage Engine
              </span>
              <span className="ml-2 text-[9px] font-bold px-2 py-0.5 rounded border text-violet-400 border-violet-800 bg-violet-900/20">
                MEDALLION v3.1
              </span>
            </div>
            <div className="text-slate-500 text-[10px] mt-1 max-w-2xl leading-relaxed">
              Ornstein-Uhlenbeck mean-reversion · Engle-Granger cointegration ·
              Kalman filter dynamic hedge ratio · 6-factor composite score (0–100)
            </div>
          </div>

          {/* Performance reference stats */}
          <div className="grid grid-cols-5 border-b border-slate-800">
            <PerfStat
              label="Medallion CAGR"
              value="66.1%"
              sub="1988–2018 gross"
              cls="text-emerald-400"
            />
            <PerfStat
              label="Sharpe Ratio"
              value="~2.1"
              sub="Pairs sub-strategy"
              cls="text-sky-400"
            />
            <PerfStat
              label="Avg Hold Period"
              value="1–5d"
              sub="Mean-reversion target"
              cls="text-slate-200"
            />
            <PerfStat
              label="Historical Win Rate"
              value="58–64%"
              sub="252d rolling windows"
              cls="text-emerald-400"
            />
            <PerfStat
              label="Strategy Drawdown Cap"
              value="-4.2%"
              sub="Portfolio-level limit"
              cls="text-rose-400"
            />
          </div>

          {/* ── No pair selected ── */}
          {!selected && (
            <div className="flex flex-col items-center justify-center py-28 text-center">
              <div className="w-16 h-16 rounded-2xl bg-slate-800/50 border border-slate-700/40 flex items-center justify-center text-3xl mb-5 shadow-inner">
                ⌬
              </div>
              <div className="text-slate-400 text-sm font-semibold mb-2">
                No pair selected
              </div>
              <div className="text-slate-600 text-xs max-w-xs leading-relaxed">
                {screened.length === 0
                  ? "Run the screener to discover cointegrated pairs, then select one for full statistical analysis."
                  : "Select a pair from the results panel to view its spread chart, factor scores, and trade setup."}
              </div>
            </div>
          )}

          {/* ── Pair detail ── */}
          {selected && (
            <div className="p-5 space-y-4">
              {/* Pair header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <ScoreRing score={selected.score} />
                  <div>
                    <div className="text-white font-bold text-lg leading-tight">
                      {selected.ticker}
                    </div>
                    <div className="text-slate-500 text-[10px] mt-0.5">
                      {selected.sector} ·{" "}
                      <span className="text-slate-400">
                        ρ={selected.corr.toFixed(2)}
                      </span>{" "}
                      · β={selected.beta.toFixed(2)} · R²=
                      {selected.rSquared.toFixed(2)}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2">
                  <div
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-bold ${
                      selected.action1 === "LONG"
                        ? "text-emerald-400 border-emerald-800 bg-emerald-900/20"
                        : "text-rose-400 border-rose-800 bg-rose-900/20"
                    }`}
                  >
                    {selected.action1 === "LONG" ? "▲" : "▼"}{" "}
                    {selected.leg1}
                  </div>
                  <div
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-bold ${
                      selected.action2 === "LONG"
                        ? "text-emerald-400 border-emerald-800 bg-emerald-900/20"
                        : "text-rose-400 border-rose-800 bg-rose-900/20"
                    }`}
                  >
                    {selected.action2 === "LONG" ? "▲" : "▼"}{" "}
                    {selected.leg2}
                  </div>
                </div>
              </div>

              {/* Spread Chart */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
                  <span className="text-slate-200 text-sm font-semibold">
                    Normalized Spread — Z-Score History (252 sessions)
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] text-slate-500 bg-slate-800/80 border border-slate-700 px-2 py-0.5 rounded font-mono">
                      OU half-life {selected.halflife}d
                    </span>
                    <span className="text-[9px] text-slate-500 bg-slate-800/80 border border-slate-700 px-2 py-0.5 rounded font-mono">
                      β={selected.beta.toFixed(2)}
                    </span>
                  </div>
                </div>
                <div className="px-4 py-4">
                  <SpreadChart pair={selected} />
                </div>
              </div>

              {/* Two-column: factors + trade setup/Z-meter */}
              <div className="grid grid-cols-2 gap-4">
                {/* Factor Bars */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                  <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
                    <span className="text-slate-200 text-sm font-semibold">
                      6-Factor Signal Score
                    </span>
                    <span className="text-[9px] text-slate-500 bg-slate-800/70 border border-slate-700 px-2 py-0.5 rounded">
                      Medallion composite
                    </span>
                  </div>
                  <div className="p-4">
                    <FactorBars factors={selected.factors} />
                    <div className="mt-4 pt-3 border-t border-slate-800/60 flex items-center justify-between">
                      <span className="text-slate-500 text-[9px] uppercase tracking-wider">
                        Composite
                      </span>
                      <div className="flex items-center gap-2">
                        <span
                          className="text-xs font-bold font-mono"
                          style={{ color: scoreColor(selected.score) }}
                        >
                          {selected.score}/100
                        </span>
                        <span
                          className="text-[8px] font-bold px-2 py-0.5 rounded border"
                          style={{
                            color: scoreColor(selected.score),
                            borderColor: scoreColor(selected.score) + "55",
                            background: scoreColor(selected.score) + "15",
                          }}
                        >
                          {selected.score >= 85
                            ? "HIGH CONVICTION"
                            : selected.score >= 75
                            ? "MEDIUM"
                            : "LOW"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Trade Setup + Z-Meter */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                  <div className="px-4 py-3 border-b border-slate-800">
                    <span className="text-slate-200 text-sm font-semibold">
                      Trade Setup &amp; Risk Levels
                    </span>
                  </div>
                  <div className="p-4 space-y-3">
                    <TradeSetup pair={selected} />
                    <ZMeter pair={selected} />
                  </div>
                </div>
              </div>

              {/* AI Thesis */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
                  <span className="text-slate-200 text-sm font-semibold">
                    Medallion Trade Thesis
                  </span>
                  <div className="flex items-center gap-2">
                    <div className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
                    <span className="text-[9px] text-sky-500 font-mono">
                      streaming
                    </span>
                  </div>
                </div>
                <div className="p-4 min-h-[80px]">
                  <ThesisStream
                    key={thesisKey}
                    text={selected.thesis}
                    streamKey={thesisKey}
                  />
                </div>
              </div>

              {/* Statistical Summary */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-800">
                  <span className="text-slate-200 text-sm font-semibold">
                    Statistical Summary
                  </span>
                </div>
                <StatTable pair={selected} />
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   SLIDER ROW HELPER
════════════════════════════════════════════════════════════════════════════ */
function SliderRow({
  label,
  valueLabel,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string;
  valueLabel: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex justify-between mb-1.5">
        <label className="text-[9px] text-slate-500 uppercase tracking-widest">
          {label}
        </label>
        <span className="text-[10px] text-sky-400 font-mono">{valueLabel}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1 accent-sky-500 bg-slate-700 rounded-full cursor-pointer"
      />
    </div>
  );
}
