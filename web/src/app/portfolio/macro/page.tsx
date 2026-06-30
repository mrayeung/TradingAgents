"use client";

import { useState, useMemo, useEffect } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
  ComposedChart,
  Area,
} from "recharts";

// ── Seeded PRNG (deterministic, Mulberry32 variant) ───────────────────────────
function mkRng(seed: number) {
  let s = (seed + 0x9e3779b9) >>> 0;
  return (): number => {
    s ^= s << 13; s ^= s >>> 17; s ^= s << 5;
    return (s >>> 0) / 0x100000000;
  };
}

// ── Random walk ───────────────────────────────────────────────────────────────
function walk(rng: () => number, n: number, start: number, vol: number, drift = 0): number[] {
  const out = [start];
  for (let i = 1; i < n; i++) {
    out.push(out[i - 1] + (rng() - 0.5) * 2 * vol + drift);
  }
  return out;
}

// ── Moving average ────────────────────────────────────────────────────────────
function movAvg(arr: number[], p: number): (number | null)[] {
  return arr.map((_, i) =>
    i < p - 1 ? null : +(arr.slice(i - p + 1, i + 1).reduce((a, b) => a + b, 0) / p).toFixed(4)
  );
}

// ── Label arrays ──────────────────────────────────────────────────────────────
function bizDays(n: number): string[] {
  const out: string[] = [];
  let d = new Date();
  while (out.length < n) {
    if (d.getDay() !== 0 && d.getDay() !== 6)
      out.unshift(d.toLocaleDateString("en-US", { month: "short", day: "numeric" }));
    d = new Date(d); d.setDate(d.getDate() - 1);
  }
  return out;
}

function monthlyLabels(n: number): string[] {
  const out: string[] = []; const d = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const m = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push(m.toLocaleDateString("en-US", { month: "short", year: "2-digit" }));
  }
  return out;
}

function weeklyLabels(n: number): string[] {
  const out: string[] = []; const d = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const w = new Date(d); w.setDate(d.getDate() - i * 7);
    out.push(w.toLocaleDateString("en-US", { month: "short", day: "numeric" }));
  }
  return out;
}

function intradayLabels(): string[] {
  const out: string[] = [];
  for (let h = 9; h <= 16; h++) {
    const s = h === 9 ? 30 : 0; const e = h === 16 ? 0 : 55;
    for (let m = s; m <= e; m += 5) out.push(`${h}:${String(m).padStart(2, "0")}`);
  }
  return out;
}

// ── Chart style constants ─────────────────────────────────────────────────────
const CM = { top: 4, right: 10, left: 0, bottom: 0 };
const GP = { stroke: "#1e293b", strokeDasharray: "3 3" };
const AX = { fill: "#64748b", fontSize: 10 };
const C = {
  cyan:    "#22d3ee",
  amber:   "#f59e0b",
  violet:  "#8b5cf6",
  emerald: "#10b981",
  rose:    "#f43f5e",
  sky:     "#38bdf8",
  orange:  "#fb923c",
  slate3:  "#cbd5e1",
  slate4:  "#94a3b8",
} as const;

// ── Custom crosshair tooltip ──────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const CT = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-900/95 border border-slate-700 rounded-lg px-3 py-2 shadow-xl text-[11px]">
      <p className="text-slate-400 mb-1.5 border-b border-slate-800 pb-1 font-medium">{label}</p>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full shrink-0" style={{ background: p.color }} />
          <span className="text-slate-400">{p.name}:</span>
          <span className="text-slate-100 font-mono font-semibold">
            {typeof p.value === "number" ? p.value.toFixed(3) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
};

// ── Card wrapper ──────────────────────────────────────────────────────────────
function Card({
  title, badge, badgeColor = "text-slate-400", children, className = "",
}: {
  title: string; badge?: string; badgeColor?: string;
  children: React.ReactNode; className?: string;
}) {
  return (
    <div className={`bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-2 ${className}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] font-semibold text-slate-500 uppercase tracking-widest">{title}</h3>
        {badge && <span className={`text-xs font-mono font-bold ${badgeColor}`}>{badge}</span>}
      </div>
      {children}
    </div>
  );
}

// ── Metric chip ───────────────────────────────────────────────────────────────
function Metric({ label, value, chg }: { label: string; value: string; chg: string }) {
  const pos = !chg.startsWith("-") && !chg.startsWith("−");
  return (
    <div className="flex flex-col gap-0.5 bg-slate-800/70 rounded-lg px-3 py-2 min-w-[100px]">
      <span className="text-[9px] text-slate-500 uppercase tracking-wider">{label}</span>
      <span className="text-sm font-bold text-slate-100 font-mono leading-tight">{value}</span>
      <span className={`text-[10px] font-mono ${pos ? "text-emerald-400" : "text-rose-400"}`}>{chg}</span>
    </div>
  );
}

// ── All mock data (computed once) ─────────────────────────────────────────────
function buildMockData() {
  const r = mkRng(1337);

  const INTRA = intradayLabels();  // 79 pts
  const D252  = bizDays(252);
  const D48M  = monthlyLabels(48);
  const W52   = weeklyLabels(52);
  const M60   = monthlyLabels(60);

  // ── Tab 1: RATES ──────────────────────────────────────────────────────────
  const y2i  = walk(r, INTRA.length, 4.835, 0.006);
  const y10i = walk(r, INTRA.length, 4.318, 0.004);
  const intradayRates = INTRA.map((t, i) => ({ t, y2: +y2i[i].toFixed(3), y10: +y10i[i].toFixed(3) }));

  const fedFunds = [
    { mtg: "Jul '25", rate: 5.33 },
    { mtg: "Sep",     rate: 5.08 },
    { mtg: "Nov",     rate: 4.83 },
    { mtg: "Dec",     rate: 4.58 },
    { mtg: "Jan '26", rate: 4.33 },
    { mtg: "Mar",     rate: 4.08 },
    { mtg: "May",     rate: 3.83 },
    { mtg: "Jun",     rate: 3.75 },
  ];

  const spr5y = walk(r, 60, 0.42, 0.14, -0.022);
  const spreadHistory = M60.map((d, i) => ({ d, spread: +Math.max(-1.8, Math.min(0.8, spr5y[i])).toFixed(3) }));

  const tp5y = walk(r, 60, -0.48, 0.07, 0.013);
  const termPremium = M60.map((d, i) => ({ d, tp: +Math.max(-0.9, Math.min(0.6, tp5y[i])).toFixed(3) }));

  // ── Tab 2: EQUITIES ──────────────────────────────────────────────────────
  const srv = walk(r, 252, 1.278, 0.005, 0.0007);
  const srma = movAvg(srv, 40);
  const spyRsp = D252.map((d, i) => ({ d, ratio: +srv[i].toFixed(4), ma200: srma[i] }));

  const smhv = walk(r, 252, 1.022, 0.003, 0.0001);
  const spyv = walk(r, 252, 2.81, 0.04, 0.004);
  const soxx = D252.map((d, i) => ({ d, smhRatio: +smhv[i].toFixed(4), spyRatio: +spyv[i].toFixed(3) }));

  const INTL = ["ewj","fez","fxi","ewy","ewz","ewc","afk"] as const;
  type IntlKey = typeof INTL[number];
  const iStarts: Record<IntlKey, number> = { ewj:0.084, fez:0.102, fxi:0.046, ewy:0.067, ewz:0.118, ewc:0.151, afk:0.021 };
  const intlData: Record<IntlKey, { d: string; ratio: number; fx: number }[]> = {} as never;
  for (const k of INTL) {
    const rv = walk(r, 52, iStarts[k], iStarts[k]*0.025, -iStarts[k]*0.0015);
    const fv = walk(r, 52, 100, 1.8, -0.05);
    const norm = (a: number[]) => { const mn=Math.min(...a),mx=Math.max(...a),rng=mx-mn+1e-6; return a.map(v=>+((v-mn)/rng).toFixed(3)); };
    const nr = norm(rv), nf = norm(fv);
    intlData[k] = W52.map((d,i) => ({ d, ratio: nr[i], fx: nf[i] }));
  }

  // ── Tab 3: OPTIONS ───────────────────────────────────────────────────────
  const vxv = walk(r, INTRA.length, 17.4, 0.2, -0.02);
  const vxd = walk(r, INTRA.length, 15.7, 0.25, -0.02);
  const vixData = INTRA.map((t,i) => ({
    t,
    vix: +Math.max(10, vxd[i]).toFixed(2),
    ratio: +(Math.max(10, vxd[i]) / Math.max(12, vxv[i])).toFixed(4),
  }));

  const strikes = [4800,4850,4900,4950,5000,5050,5100,5150,5200,5250,5300,5350,5400,5450,5500,5550,5600];
  const ATM = 9; // index of 5200
  const gexData = strikes.map((strike, i) => {
    const d = i - ATM;
    const gex = d === 0 ? 5e7
      : d > 0 ? Math.abs(d) * (0.5e9 + r()*0.25e9)
      : -(Math.abs(d) * (0.8e9 + r()*0.4e9));
    return { strike: strike.toLocaleString(), gex: Math.round(gex) };
  });

  const HT = ["SPY","QQQ","IWM","DIA","XLF","XLK","XLE","XLU","XLP","XLY","XLC","XLI","XLB","XLV","XLRE"];
  const zScores: Record<string, [number,number,number]> = {};
  for (const t of HT) zScores[t] = [+(r()*5.2-2.6).toFixed(1), +(r()*5.2-2.6).toFixed(1), +(r()*5.2-2.6).toFixed(1)];

  // ── Tab 4: FX ────────────────────────────────────────────────────────────
  const ujv = walk(r, 52, 148.2, 1.9, 0.04);
  const y10w = walk(r, 52, 4.18, 0.05, 0.003);
  const usdjpy = W52.map((d,i) => ({ d, usdjpy: +ujv[i].toFixed(2), y10: +y10w[i].toFixed(3) }));

  const ajv = walk(r, 52, 96.4, 1.2, -0.06);
  const spxw = walk(r, 52, 4820, 50, 8);
  const audjpy = W52.map((d,i) => ({ d, audjpy: +ajv[i].toFixed(2), spx: +spxw[i].toFixed(0) }));

  // ── Tab 5: ENERGY ────────────────────────────────────────────────────────
  const brent = walk(r, 252, 85.4, 1.9, -0.04);
  const wti   = walk(r, 252, 81.6, 1.7, -0.03);
  const crude = D252.map((d,i) => ({
    d, brent: +brent[i].toFixed(2), wti: +wti[i].toFixed(2),
    spread: +(brent[i]-wti[i]).toFixed(2),
  }));

  const cl1cl6 = walk(r, 252, 4.1, 0.32, -0.01);
  const termStructure = D252.map((d,i) => ({ d, cl1cl6: +cl1cl6[i].toFixed(2) }));

  const cuGoldV   = walk(r, 252, 0.312, 0.004, -0.0002);
  const realYield = walk(r, 252, 2.14, 0.04, -0.002);
  const cuGold = D252.map((d,i) => ({ d, cuGold: +cuGoldV[i].toFixed(4), realYield: +realYield[i].toFixed(3) }));

  const gsv = walk(r, 252, 82.6, 1.3, 0.015);
  const goldSilver = D252.map((d,i) => ({ d, ratio: +gsv[i].toFixed(2) }));

  // ── Tab 6: MACRO ─────────────────────────────────────────────────────────
  const mfgv = walk(r, 48, 52.4, 2.0, -0.09);
  const svcv = walk(r, 48, 55.1, 1.5, -0.05);
  const ism = D48M.map((d,i) => ({
    d, mfg: +Math.max(42, Math.min(60, mfgv[i])).toFixed(1),
    svc: +Math.max(47, Math.min(62, svcv[i])).toFixed(1),
  }));

  const cpiv = walk(r, 48, 8.2, 0.32, -0.16);
  const pcev = walk(r, 48, 5.9, 0.22, -0.10);
  const beiv = walk(r, 48, 2.82, 0.08, -0.008);
  const inflation = D48M.map((d,i) => ({
    d, cpi: +Math.max(1.8, cpiv[i]).toFixed(2),
    pce: +Math.max(1.8, pcev[i]).toFixed(2),
    bei: +Math.max(1.7, Math.min(3.4, beiv[i])).toFixed(2),
  }));

  const debtv = walk(r, 48, 29_600, 130, 85);
  const ratev = walk(r, 48, 1.82, 0.13, 0.075);
  const fiscal = D48M.map((d,i) => ({
    d, debt: +Math.max(28000, debtv[i]).toFixed(0),
    rate: +Math.max(1.5, ratev[i]).toFixed(2),
  }));

  // ── Tab 7: SYSTEMIC RISK ──────────────────────────────────────────────────
  const mcvv = walk(r, 252, 340, 65, -0.8);
  const mcclellan = D252.map((d,i) => ({ d, nysi: +mcvv[i].toFixed(0) }));

  const naaimv = walk(r, 52, 63, 9, -0.15);
  const aaiiV  = walk(r, 52, 19, 7, -0.08);
  const sentiment = W52.map((d,i) => ({
    d, naaim: +Math.max(5, Math.min(100, naaimv[i])).toFixed(1),
    aaii: +Math.max(-40, Math.min(55, aaiiV[i])).toFixed(1),
  }));

  const nfciv = walk(r, 252, -0.09, 0.04, 0.0002);
  const bofav = walk(r, 252, -0.24, 0.09, 0.0004);
  const stress = D252.map((d,i) => ({
    d, nfci: +nfciv[i].toFixed(4), bofaFsi: +bofav[i].toFixed(4),
  }));

  // ── Put/Call Ratio ────────────────────────────────────────────────────────
  // Equity-only PCR: mean ~0.62, spikes toward 1.0 on fear days
  const eqPcrVals = walk(r, 252, 0.64, 0.07, -0.0003).map(v => +Math.max(0.35, Math.min(1.35, v)).toFixed(3));
  // Total CBOE PCR (includes index options which are structurally put-heavy): mean ~0.95
  const totPcrVals = walk(r, 252, 0.96, 0.10, -0.0002).map(v => +Math.max(0.55, Math.min(1.70, v)).toFixed(3));
  const eqPcrMa20 = movAvg(eqPcrVals, 20);
  const pcrDaily = D252.map((d,i) => ({
    d,
    eqPcr:   eqPcrVals[i],
    totPcr:  totPcrVals[i],
    ma20:    eqPcrMa20[i],
  }));

  // Intraday PCR — starts elevated (morning hedging), normalizes into close
  const pcrIntra = INTRA.map((t, i) => {
    const decay = Math.exp(-i / 40);                          // morning put-buying fades
    const base  = 0.62 + decay * 0.28;                       // 0.90 at open → 0.62 at close
    const noise = (r() - 0.5) * 0.08;
    return { t, pcr: +Math.max(0.35, base + noise).toFixed(3) };
  });

  const eqPcrLast  = eqPcrVals[eqPcrVals.length - 1];
  const totPcrLast = totPcrVals[totPcrVals.length - 1];
  const eqMa20Last = eqPcrMa20[eqPcrMa20.length - 1] ?? eqPcrLast;

  const hindenburg    = r() > 0.72;
  const titanic       = r() > 0.88;
  const vixAboveMA    = r() > 0.58;
  const yieldInverted = spreadHistory[spreadHistory.length-1].spread < 0;
  const naaimHigh     = naaimv[naaimv.length-1] > 75;
  const mclellanNeg   = mcvv[mcvv.length-1] < 0;

  const activeFlags = [hindenburg, titanic, vixAboveMA, yieldInverted, naaimHigh, mclellanNeg].filter(Boolean).length;
  const riskScore   = Math.min(10, Math.max(1, Math.round(activeFlags * 1.6 + r() * 1.5)));

  return {
    rates:    { intradayRates, fedFunds, spreadHistory, termPremium },
    equities: { spyRsp, soxx, intlData },
    options:  { vixData, gexData, zScores, pcrDaily, pcrIntra, eqPcrLast, totPcrLast, eqMa20Last },
    fx:       { usdjpy, audjpy },
    energy:   { crude, termStructure, cuGold, goldSilver },
    macro:    { ism, inflation, fiscal },
    systemic: { mcclellan, sentiment, stress, hindenburg, titanic, vixAboveMA, yieldInverted, naaimHigh, mclellanNeg },
    riskScore,
  };
}

type MD = ReturnType<typeof buildMockData>;

// ─────────────────────────────────────────────────────────────────────────────
// TAB 1 — RATES & FIXED INCOME
// ─────────────────────────────────────────────────────────────────────────────
function RatesTab({ d }: { d: MD["rates"] }) {
  const last = d.intradayRates[d.intradayRates.length - 1];
  const first = d.intradayRates[0];
  const sLast = d.spreadHistory[d.spreadHistory.length - 1].spread;
  const tpLast = d.termPremium[d.termPremium.length - 1].tp;
  const ffLast = d.fedFunds[d.fedFunds.length - 1].rate;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Metric label="US 2Y" value={`${last.y2.toFixed(3)}%`} chg={`${(last.y2 - first.y2 >= 0 ? "+" : "")}${(last.y2 - first.y2).toFixed(3)}%`} />
        <Metric label="US 10Y" value={`${last.y10.toFixed(3)}%`} chg={`${(last.y10 - first.y10 >= 0 ? "+" : "")}${(last.y10 - first.y10).toFixed(3)}%`} />
        <Metric label="2Y/10Y Spread" value={`${sLast.toFixed(2)}%`} chg={sLast < 0 ? "Inverted" : "Normal"} />
        <Metric label="Term Premium" value={`${tpLast.toFixed(2)}%`} chg={tpLast >= 0 ? "+Positive" : "-Negative"} />
        <Metric label="Year-End FF" value={`${ffLast.toFixed(2)}%`} chg={`-${(d.fedFunds[0].rate - ffLast).toFixed(2)}% implied`} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Intraday 2Y / 10Y */}
        <Card title="US 2Y & 10Y Yields — Intraday" badge="Live Rates" badgeColor="text-cyan-400">
          <ResponsiveContainer width="100%" height={190}>
            <LineChart data={d.intradayRates} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="t" tick={AX} interval={15} />
              <YAxis tick={AX} domain={["auto","auto"]} tickFormatter={v => `${v.toFixed(2)}%`} width={48} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10, color: C.slate4 }} />
              <Line dataKey="y2"  name="US 2Y"  stroke={C.cyan}  dot={false} strokeWidth={1.5} />
              <Line dataKey="y10" name="US 10Y" stroke={C.amber} dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Fed Funds Futures */}
        <Card title="Fed Funds Futures — Implied Rate Path" badge="OIS Curve" badgeColor="text-violet-400">
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={d.fedFunds} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="mtg" tick={AX} />
              <YAxis tick={AX} domain={[3.4, 5.6]} tickFormatter={v => `${v.toFixed(2)}%`} width={48} />
              <Tooltip content={<CT />} />
              <Bar dataKey="rate" name="Implied Rate" radius={[4,4,0,0]}>
                {d.fedFunds.map((_,i) => <Cell key={i} fill={`rgba(139,92,246,${1 - i * 0.09})`} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        {/* 2Y/10Y Spread 5Y */}
        <Card title="2Y/10Y Yield Spread — 5-Year History" badge="T10Y2Y" badgeColor="text-orange-400">
          <ResponsiveContainer width="100%" height={190}>
            <ComposedChart data={d.spreadHistory} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={11} />
              <YAxis tick={AX} tickFormatter={v => `${v.toFixed(1)}%`} width={48} />
              <Tooltip content={<CT />} />
              <ReferenceLine y={0} stroke="#ef4444" strokeWidth={1.5} label={{ value: "0%", fill: "#ef4444", fontSize: 9, position: "right" }} />
              <Area dataKey="spread" name="Spread" stroke={C.orange} fill="rgba(251,146,60,0.12)" strokeWidth={1.5} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        {/* Term Premium */}
        <Card title="10Y Term Premium Model (ACM)" badge="Structural" badgeColor="text-amber-400">
          <ResponsiveContainer width="100%" height={190}>
            <ComposedChart data={d.termPremium} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={11} />
              <YAxis tick={AX} tickFormatter={v => `${v.toFixed(2)}%`} width={48} />
              <Tooltip content={<CT />} />
              <ReferenceLine y={0} stroke="#475569" strokeWidth={1} strokeDasharray="4 4" />
              <Area dataKey="tp" name="Term Premium" stroke={C.amber} fill="rgba(245,158,11,0.1)" strokeWidth={1.5} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 2 — EQUITIES & GLOBAL BREADTH
// ─────────────────────────────────────────────────────────────────────────────
const INTL_META = [
  { key:"ewj", name:"EWJ/SPY", region:"Japan",       fx:"USD/JPY"   },
  { key:"fez", name:"FEZ/SPY", region:"Eurozone",    fx:"EUR/USD"   },
  { key:"fxi", name:"FXI/SPY", region:"China",       fx:"USD/CNY"   },
  { key:"ewy", name:"EWY/SPY", region:"Korea",       fx:"USD/KRW"   },
  { key:"ewz", name:"EWZ/SPY", region:"Brazil",      fx:"USD/BRL"   },
  { key:"ewc", name:"EWC/SPY", region:"Canada",      fx:"USD/CAD"   },
  { key:"afk", name:"AFK/SPY", region:"Africa",      fx:"DXY"       },
] as const;

function EquitiesTab({ d }: { d: MD["equities"] }) {
  const srLast  = d.spyRsp[d.spyRsp.length-1];
  const srFirst = d.spyRsp[0];
  const sxLast  = d.soxx[d.soxx.length-1];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Metric label="SPY/RSP Ratio" value={srLast.ratio.toFixed(4)} chg={`${srLast.ratio > srFirst.ratio ? "+" : ""}${(srLast.ratio - srFirst.ratio).toFixed(4)} YTD`} />
        <Metric label="SOXX/SMH"  value={sxLast.smhRatio.toFixed(4)} chg={`${d.soxx[0].smhRatio > sxLast.smhRatio ? "-" : "+"}${Math.abs(sxLast.smhRatio - d.soxx[0].smhRatio).toFixed(4)}`} />
        <Metric label="SOXX/SPY" value={sxLast.spyRatio.toFixed(3)} chg={`${sxLast.spyRatio > d.soxx[0].spyRatio ? "+" : ""}${(sxLast.spyRatio - d.soxx[0].spyRatio).toFixed(3)}`} />
        <Metric label="Breadth Signal" value={srLast.ratio > (srLast.ma200 ?? 0) ? "OW Large Cap" : "UW Large Cap"}
          chg={srLast.ratio > (srLast.ma200 ?? 0) ? "+Mega-cap led" : "-Rotation risk"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* SPY/RSP */}
        <Card title="SPY / RSP — Market-Cap vs Equal-Weight Breadth" badge="200D MA" badgeColor="text-amber-400">
          <ResponsiveContainer width="100%" height={190}>
            <LineChart data={d.spyRsp} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={50} />
              <YAxis tick={AX} domain={["auto","auto"]} tickFormatter={v => v.toFixed(3)} width={50} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line dataKey="ratio" name="SPY/RSP" stroke={C.cyan} dot={false} strokeWidth={1.5} />
              <Line dataKey="ma200" name="40D MA" stroke={C.amber} dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* SOXX Ratios */}
        <Card title="Semiconductors — SOXX/SMH & SOXX/SPY" badge="CapEx Proxy" badgeColor="text-sky-400">
          <ResponsiveContainer width="100%" height={190}>
            <LineChart data={d.soxx} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={50} />
              <YAxis yAxisId="l" tick={AX} domain={["auto","auto"]} tickFormatter={v => v.toFixed(4)} width={52} />
              <YAxis yAxisId="r" orientation="right" tick={AX} domain={["auto","auto"]} tickFormatter={v => v.toFixed(2)} width={44} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line yAxisId="l" dataKey="smhRatio" name="SOXX/SMH" stroke={C.cyan}   dot={false} strokeWidth={1.5} />
              <Line yAxisId="r" dataKey="spyRatio" name="SOXX/SPY" stroke={C.violet} dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>

      {/* International ETF Grid */}
      <Card title="International ETFs vs SPY — Relative Strength & FX Overlay" badge="Global Breadth" badgeColor="text-emerald-400">
        <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7 gap-3">
          {INTL_META.map(({ key, name, region, fx }) => {
            const data = d.intlData[key as keyof typeof d.intlData];
            const last  = data[data.length - 1];
            const first = data[0];
            const trend = last.ratio > first.ratio;
            return (
              <div key={key} className="bg-slate-800/60 rounded-lg p-2 flex flex-col gap-1">
                <div className="text-[10px] font-bold text-slate-300">{name}</div>
                <div className="text-[9px] text-slate-500">{region}</div>
                <ResponsiveContainer width="100%" height={56}>
                  <LineChart data={data} margin={{ top:2, right:2, left:2, bottom:2 }}>
                    <Line dataKey="ratio" stroke={trend ? C.emerald : C.rose} dot={false} strokeWidth={1.5} />
                    <Line dataKey="fx"    stroke={C.amber} dot={false} strokeWidth={1} strokeDasharray="3 2" />
                  </LineChart>
                </ResponsiveContainer>
                <div className="flex justify-between items-center">
                  <span className={`text-[9px] font-bold ${trend ? "text-emerald-400" : "text-rose-400"}`}>
                    {trend ? "▲" : "▼"} {Math.abs(last.ratio - first.ratio).toFixed(2)}
                  </span>
                  <span className="text-[8px] text-amber-400/70">{fx}</span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="text-[9px] text-slate-600 mt-1">
          ■ Solid = ETF/SPY ratio · — Dashed = Local currency pair (normalized 0–1)
        </div>
      </Card>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 3 — OPTIONS & VOLATILITY
// ─────────────────────────────────────────────────────────────────────────────
const HMAP_TICKERS = ["SPY","QQQ","IWM","DIA","XLF","XLK","XLE","XLU","XLP","XLY","XLC","XLI","XLB","XLV","XLRE"];

function zCell(z: number) {
  if (z >  2.5) return "bg-red-900     text-red-100";
  if (z >  1.5) return "bg-red-900/60  text-red-300";
  if (z >  0.5) return "bg-red-900/30  text-red-400";
  if (z < -2.5) return "bg-emerald-900 text-emerald-100";
  if (z < -1.5) return "bg-emerald-900/60 text-emerald-300";
  if (z < -0.5) return "bg-emerald-900/30 text-emerald-400";
  return "bg-slate-800 text-slate-400";
}

function OptionsTab({ d }: { d: MD["options"] }) {
  const vLast  = d.vixData[d.vixData.length-1];
  const vFirst = d.vixData[0];
  const { eqPcrLast, totPcrLast, eqMa20Last } = d;

  // PCR interpretation
  const pcrSignal = eqPcrLast > 0.90 ? { label: "Bearish / Fear", color: "text-emerald-400", chg: "+Contrarian buy" }
    : eqPcrLast < 0.55               ? { label: "Bullish / Complacency", color: "text-rose-400", chg: "-Contrarian sell" }
    :                                   { label: "Neutral", color: "text-slate-400", chg: "±No extreme" };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Metric label="VIX" value={vLast.vix.toFixed(2)}
          chg={`${vLast.vix > vFirst.vix ? "+" : ""}${(vLast.vix - vFirst.vix).toFixed(2)} today`} />
        <Metric label="VIX/VXV" value={vLast.ratio.toFixed(4)}
          chg={vLast.ratio > 1 ? "Backwardated — stress" : "Term struct normal"} />
        <Metric label="Equity PCR" value={eqPcrLast.toFixed(3)}
          chg={eqPcrLast > (eqMa20Last as number) ? `+${(eqPcrLast - (eqMa20Last as number)).toFixed(3)} above MA` : `${(eqPcrLast - (eqMa20Last as number)).toFixed(3)} below MA`} />
        <Metric label="Total PCR" value={totPcrLast.toFixed(3)}
          chg={totPcrLast > 1.0 ? "-Elevated put demand" : "+Below parity"} />
        <Metric label="PCR Signal" value={pcrSignal.label} chg={pcrSignal.chg} />
        <Metric label="GEX Flip Zone" value="≈5,200" chg="+Positive above" />
        <Metric label="Vol Regime" value={vLast.vix < 15 ? "Low Vol" : vLast.vix < 20 ? "Mid Vol" : "High Vol"}
          chg={vLast.vix < 15 ? "+Complacency zone" : vLast.vix < 20 ? "±Transitional" : "-Stress elevated"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* VIX Intraday */}
        <Card title="VIX & VIX/VXV Ratio — Intraday" badge={`VIX ${vLast.vix.toFixed(2)}`} badgeColor="text-rose-400">
          <ResponsiveContainer width="100%" height={190}>
            <LineChart data={d.vixData} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="t" tick={AX} interval={15} />
              <YAxis yAxisId="l" tick={AX} domain={[10,24]} tickFormatter={v=>`${v.toFixed(0)}`} width={36} />
              <YAxis yAxisId="r" orientation="right" tick={AX} domain={[0.82,1.08]} tickFormatter={v=>v.toFixed(3)} width={44} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <ReferenceLine yAxisId="r" y={1.0} stroke={C.amber} strokeDasharray="4 4" strokeWidth={1} />
              <Line yAxisId="l" dataKey="vix"   name="VIX"     stroke={C.rose}  dot={false} strokeWidth={1.5} />
              <Line yAxisId="r" dataKey="ratio"  name="VIX/VXV" stroke={C.amber} dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Dealer GEX */}
        <Card title="Dealer Gamma Exposure (GEX) — Strike Profile" badge="Flip Zone ~5200" badgeColor="text-orange-400">
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={d.gexData} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="strike" tick={{ ...AX, fontSize: 8 }} interval={3} />
              <YAxis tick={AX} tickFormatter={v=>`${(v/1e9).toFixed(1)}B`} width={40} />
              <Tooltip content={<CT />} formatter={(v:number) => [`$${(v/1e9).toFixed(2)}B`, "GEX"]} />
              <ReferenceLine y={0} stroke={C.orange} strokeWidth={1.5} label={{ value:"Flip", fill:C.orange, fontSize:9, position:"insideTopLeft" }} />
              <Bar dataKey="gex" name="GEX" radius={[2,2,0,0]}>
                {d.gexData.map((row,i) => <Cell key={i} fill={row.gex >= 0 ? C.emerald : C.rose} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      {/* ── Put / Call Ratio ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Daily PCR history */}
        <Card title="CBOE Put/Call Ratio — Daily History (1 Year)" badge="Equity vs Total" badgeColor="text-orange-400">
          <p className="text-[9px] text-slate-600 -mt-1">
            Equity PCR &gt; 0.90 = fear / contrarian bullish · &lt; 0.55 = complacency / contrarian bearish.
            Total PCR structurally higher (index options are put-heavy by design).
          </p>
          <ResponsiveContainer width="100%" height={195}>
            <ComposedChart data={d.pcrDaily} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={50} />
              <YAxis tick={AX} domain={[0.3, 1.8]} tickFormatter={v => v.toFixed(2)} width={40} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              {/* Danger zone: complacency below 0.55 */}
              <ReferenceLine y={0.55} stroke={C.rose}   strokeDasharray="4 4" strokeWidth={1}
                label={{ value:"0.55 complacency", fill: C.rose,   fontSize: 8, position:"insideTopLeft" }} />
              {/* Fear zone: above 0.90 */}
              <ReferenceLine y={0.90} stroke={C.emerald} strokeDasharray="4 4" strokeWidth={1}
                label={{ value:"0.90 fear", fill: C.emerald, fontSize: 8, position:"insideBottomLeft" }} />
              <Line dataKey="totPcr" name="Total PCR"   stroke={C.violet} dot={false} strokeWidth={1}   strokeDasharray="4 3" />
              <Line dataKey="eqPcr"  name="Equity PCR"  stroke={C.orange} dot={false} strokeWidth={1.5} />
              <Line dataKey="ma20"   name="20D MA (Eq)" stroke={C.amber}  dot={false} strokeWidth={2}   strokeDasharray="6 2" />
            </ComposedChart>
          </ResponsiveContainer>
          {/* PCR regime legend */}
          <div className="grid grid-cols-3 gap-2 mt-1">
            {[
              { range: "< 0.55", label: "Complacency",    color: "bg-rose-900/40 text-rose-400",    hint: "Contrarian SELL signal" },
              { range: "0.55–0.90", label: "Neutral",     color: "bg-slate-800 text-slate-400",     hint: "No directional edge" },
              { range: "> 0.90", label: "Fear / Hedging", color: "bg-emerald-900/40 text-emerald-400", hint: "Contrarian BUY signal" },
            ].map(b => (
              <div key={b.range} className={`rounded-lg px-2 py-1.5 ${b.color}`}>
                <div className="text-[10px] font-bold">{b.range}</div>
                <div className="text-[9px] font-semibold">{b.label}</div>
                <div className="text-[8px] opacity-70">{b.hint}</div>
              </div>
            ))}
          </div>
        </Card>

        {/* Intraday PCR */}
        <Card title="Put/Call Ratio — Intraday Evolution" badge="Today" badgeColor="text-cyan-400">
          <p className="text-[9px] text-slate-600 -mt-1">
            PCR is typically elevated at the open (institutional hedging, overnight put unwind) and
            normalizes by midday. A rising PCR into the close signals late-day defensive positioning.
          </p>
          <ResponsiveContainer width="100%" height={195}>
            <ComposedChart data={d.pcrIntra} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="t" tick={AX} interval={15} />
              <YAxis tick={AX} domain={[0.3, 1.2]} tickFormatter={v => v.toFixed(2)} width={40} />
              <Tooltip content={<CT />} />
              <ReferenceLine y={0.90} stroke={C.emerald} strokeDasharray="3 3" strokeWidth={1}
                label={{ value:"0.90", fill: C.emerald, fontSize:8, position:"right" }} />
              <ReferenceLine y={0.55} stroke={C.rose}   strokeDasharray="3 3" strokeWidth={1}
                label={{ value:"0.55", fill: C.rose,   fontSize:8, position:"right" }} />
              <Area dataKey="pcr" name="Intraday PCR" stroke={C.cyan} fill="rgba(34,211,238,0.08)" dot={false} strokeWidth={1.5} />
            </ComposedChart>
          </ResponsiveContainer>
          {/* Key levels explanation */}
          <div className="mt-2 space-y-1">
            {[
              { label: "Morning spike (9:30–10:30)", note: "Overnight hedges rolling + gap protection. Often fades — fade the fear." },
              { label: "Midday normalization",        note: "True flow emerges. PCR near 0.60–0.75 = balanced market." },
              { label: "Close divergence",            note: "PCR rising into close = defensive. Falling = momentum chasers piling in." },
            ].map(r => (
              <div key={r.label} className="flex gap-2 text-[9px]">
                <span className="text-cyan-400 font-semibold shrink-0">{r.label}:</span>
                <span className="text-slate-500">{r.note}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Z-Score Heatmap */}
      <Card title="Options Z-Score Sentiment Matrix — SPY · QQQ · IWM · DIA · 11 Sector ETFs" badge="Conditional Formatting" badgeColor="text-violet-400">
        <div className="overflow-x-auto">
          <table className="w-full text-[10px] border-separate border-spacing-0.5">
            <thead>
              <tr>
                <th className="text-left text-[9px] text-slate-600 w-16 pr-2">Horizon</th>
                {HMAP_TICKERS.map(t => (
                  <th key={t} className="text-center text-[9px] text-slate-500 font-semibold pb-1">{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(["1W Z", "1M Z", "3M Z"] as const).map((row, ri) => (
                <tr key={row}>
                  <td className="text-[9px] text-slate-600 pr-2 py-0.5 font-medium whitespace-nowrap">{row}</td>
                  {HMAP_TICKERS.map(t => {
                    const z = d.zScores[t]?.[ri] ?? 0;
                    return (
                      <td key={t} className={`text-center py-1 rounded font-mono text-[10px] ${zCell(z)}`}>
                        {z.toFixed(1)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex gap-4 text-[9px] mt-1 text-slate-600">
          <span><span className="text-red-400">■</span> Z &gt; +2 extreme put skew / oversold pressure</span>
          <span><span className="text-emerald-400">■</span> Z &lt; −2 elevated call demand / overbought</span>
        </div>
      </Card>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 4 — CURRENCIES (FX)
// ─────────────────────────────────────────────────────────────────────────────
function FXTab({ d }: { d: MD["fx"] }) {
  const ujLast  = d.usdjpy[d.usdjpy.length-1];
  const ujFirst = d.usdjpy[0];
  const ajLast  = d.audjpy[d.audjpy.length-1];
  const ajFirst = d.audjpy[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Metric label="USD/JPY" value={ujLast.usdjpy.toFixed(2)}
          chg={`${(ujLast.usdjpy - ujFirst.usdjpy >= 0 ? "+" : "")}${(ujLast.usdjpy - ujFirst.usdjpy).toFixed(2)} YTD`} />
        <Metric label="US 10Y Yield" value={`${ujLast.y10.toFixed(3)}%`}
          chg={`${(ujLast.y10 - ujFirst.y10 >= 0 ? "+" : "")}${(ujLast.y10 - ujFirst.y10).toFixed(3)}% YTD`} />
        <Metric label="AUD/JPY" value={ajLast.audjpy.toFixed(2)}
          chg={`${(ajLast.audjpy - ajFirst.audjpy >= 0 ? "+" : "")}${(ajLast.audjpy - ajFirst.audjpy).toFixed(2)} YTD`} />
        <Metric label="Risk Regime" value={ajLast.audjpy > ajFirst.audjpy ? "Risk-On" : "Risk-Off"}
          chg={ajLast.audjpy > ajFirst.audjpy ? "+AUD/JPY rising" : "-AUD/JPY falling"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* USD/JPY vs 10Y */}
        <Card title="USD/JPY vs US 10Y Treasury — Policy Divergence Proxy" badge="BoJ · Fed" badgeColor="text-cyan-400">
          <p className="text-[9px] text-slate-600 -mt-1">
            High correlation: diverging yields drive JPY weakness. Watch for BoJ rate normalization.
          </p>
          <ResponsiveContainer width="100%" height={210}>
            <LineChart data={d.usdjpy} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={12} />
              <YAxis yAxisId="l" tick={AX} domain={["auto","auto"]} tickFormatter={v=>v.toFixed(1)} width={46}
                label={{ value:"¥/USD", angle:-90, position:"insideLeft", fill:"#64748b", fontSize:9 }} />
              <YAxis yAxisId="r" orientation="right" tick={AX} domain={["auto","auto"]} tickFormatter={v=>`${v.toFixed(2)}%`} width={46} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line yAxisId="l" dataKey="usdjpy" name="USD/JPY"  stroke={C.cyan}  dot={false} strokeWidth={1.5} />
              <Line yAxisId="r" dataKey="y10"    name="US 10Y %"  stroke={C.amber} dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* AUD/JPY vs SPX */}
        <Card title="AUD/JPY vs S&P 500 — Risk-On / Risk-Off Barometer" badge="Risk Regime" badgeColor="text-emerald-400">
          <p className="text-[9px] text-slate-600 -mt-1">
            AUD/JPY leads equity drawdowns by ~2–5 days. Divergence = warning signal.
          </p>
          <ResponsiveContainer width="100%" height={210}>
            <LineChart data={d.audjpy} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={12} />
              <YAxis yAxisId="l" tick={AX} domain={["auto","auto"]} tickFormatter={v=>v.toFixed(1)} width={44} />
              <YAxis yAxisId="r" orientation="right" tick={AX} domain={["auto","auto"]} tickFormatter={v=>v.toFixed(0)} width={52} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line yAxisId="l" dataKey="audjpy" name="AUD/JPY" stroke={C.emerald} dot={false} strokeWidth={1.5} />
              <Line yAxisId="r" dataKey="spx"    name="S&P 500" stroke={C.sky}    dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 5 — ENERGY & COMMODITIES
// ─────────────────────────────────────────────────────────────────────────────
function EnergyTab({ d }: { d: MD["energy"] }) {
  const cLast = d.crude[d.crude.length-1];
  const tLast = d.termStructure[d.termStructure.length-1];
  const cgLast = d.cuGold[d.cuGold.length-1];
  const gsLast = d.goldSilver[d.goldSilver.length-1];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Metric label="Brent Crude" value={`$${cLast.brent.toFixed(2)}`}
          chg={`${cLast.brent > d.crude[0].brent ? "+" : ""}${(cLast.brent - d.crude[0].brent).toFixed(2)}`} />
        <Metric label="WTI Crude" value={`$${cLast.wti.toFixed(2)}`}
          chg={`${cLast.wti > d.crude[0].wti ? "+" : ""}${(cLast.wti - d.crude[0].wti).toFixed(2)}`} />
        <Metric label="B–W Spread" value={`$${cLast.spread.toFixed(2)}`} chg={`Quality premium`} />
        <Metric label="CL1−CL6 Curve" value={`$${tLast.cl1cl6.toFixed(2)}`}
          chg={tLast.cl1cl6 > 0 ? "+Backwardation" : "-Contango"} />
        <Metric label="Cu/Gold Ratio" value={cgLast.cuGold.toFixed(4)}
          chg={cgLast.cuGold > d.cuGold[0].cuGold ? "+Industrial growth" : "-Risk-off metals"} />
        <Metric label="Gold/Silver" value={gsLast.ratio.toFixed(1)}
          chg={gsLast.ratio > 80 ? "+Defensive (Au leads)" : "-Risk-on (Ag leads)"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Brent vs WTI */}
        <Card title="Brent vs WTI Crude — Spot Prices & Spread" badge="Physical" badgeColor="text-orange-400">
          <ResponsiveContainer width="100%" height={145}>
            <LineChart data={d.crude} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={50} />
              <YAxis tick={AX} domain={["auto","auto"]} tickFormatter={v=>`$${v.toFixed(0)}`} width={44} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line dataKey="brent" name="Brent" stroke={C.orange} dot={false} strokeWidth={1.5} />
              <Line dataKey="wti"   name="WTI"   stroke={C.amber}  dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
            </LineChart>
          </ResponsiveContainer>
          <div className="text-[9px] text-slate-600">Brent – WTI Spread ($/bbl)</div>
          <ResponsiveContainer width="100%" height={60}>
            <ComposedChart data={d.crude} margin={{ top:2, right:10, left:0, bottom:2 }}>
              <XAxis dataKey="d" hide />
              <YAxis tick={{ fill:"#64748b", fontSize:9 }} tickFormatter={v=>`$${v.toFixed(1)}`} width={36} />
              <Tooltip content={<CT />} />
              <ReferenceLine y={0} stroke="#334155" />
              <Area dataKey="spread" name="B−W Spread" stroke={C.cyan} fill="rgba(34,211,238,0.12)" dot={false} strokeWidth={1} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        {/* Oil Term Structure */}
        <Card title="Oil Futures Term Structure — CL1 vs CL6 Spread" badge="Curve Shape" badgeColor="text-amber-400">
          <p className="text-[9px] text-slate-600 -mt-1">Positive = backwardation (tight supply) · Negative = contango (surplus/storage build)</p>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={d.termStructure} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={50} />
              <YAxis tick={AX} tickFormatter={v=>`$${v.toFixed(1)}`} width={44} />
              <Tooltip content={<CT />} />
              <ReferenceLine y={0} stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 4" />
              <Area dataKey="cl1cl6" name="CL1−CL6" stroke={C.amber} fill="rgba(245,158,11,0.1)" dot={false} strokeWidth={1.5} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        {/* Copper/Gold vs Real Yield */}
        <Card title="Copper / Gold Ratio vs 10Y Real Yield (TIPS)" badge="Hard Macro" badgeColor="text-emerald-400">
          <p className="text-[9px] text-slate-600 -mt-1">Cu/Au falls before recessions; tracks real rates &amp; global industrial demand</p>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={d.cuGold} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={50} />
              <YAxis yAxisId="l" tick={AX} domain={["auto","auto"]} tickFormatter={v=>v.toFixed(4)} width={52} />
              <YAxis yAxisId="r" orientation="right" tick={AX} domain={["auto","auto"]} tickFormatter={v=>`${v.toFixed(1)}%`} width={42} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line yAxisId="l" dataKey="cuGold"     name="Cu/Gold"      stroke={C.emerald} dot={false} strokeWidth={1.5} />
              <Line yAxisId="r" dataKey="realYield"   name="10Y Real Yld" stroke={C.violet}  dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Gold/Silver */}
        <Card title="Gold / Silver Ratio (XAU / XAG)" badge="Precious Metals" badgeColor="text-slate-300">
          <p className="text-[9px] text-slate-600 -mt-1">Ratio &gt;80 = defensive gold bid; &lt;70 = industrial risk-on, silver outperforms</p>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={d.goldSilver} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={50} />
              <YAxis tick={AX} domain={["auto","auto"]} tickFormatter={v=>v.toFixed(1)} width={40} />
              <Tooltip content={<CT />} />
              <ReferenceLine y={80} stroke="#64748b" strokeDasharray="3 3" strokeWidth={1} label={{ value:"80", fill:"#64748b", fontSize:9 }} />
              <Area dataKey="ratio" name="Gold/Silver" stroke={C.slate3} fill="rgba(203,213,225,0.07)" dot={false} strokeWidth={1.5} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 6 — MACRO ECONOMIC
// ─────────────────────────────────────────────────────────────────────────────
function MacroTab({ d }: { d: MD["macro"] }) {
  const ismL  = d.ism[d.ism.length-1];
  const infL  = d.inflation[d.inflation.length-1];
  const fisL  = d.fiscal[d.fiscal.length-1];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Metric label="ISM Mfg" value={ismL.mfg.toFixed(1)}
          chg={ismL.mfg > 50 ? "+Expansion" : "-Contraction"} />
        <Metric label="ISM Services" value={ismL.svc.toFixed(1)}
          chg={ismL.svc > 50 ? "+Expansion" : "-Contraction"} />
        <Metric label="CPI YoY" value={`${infL.cpi.toFixed(1)}%`}
          chg={infL.cpi < 3 ? "+Near target" : "-Above 2% target"} />
        <Metric label="Core PCE" value={`${infL.pce.toFixed(1)}%`}
          chg={infL.pce < 2.5 ? "+Near target" : "-Elevated"} />
        <Metric label="10Y Breakeven" value={`${infL.bei.toFixed(2)}%`}
          chg={infL.bei > 2.5 ? "-Inflation priced high" : "+Anchored"} />
        <Metric label="Gross Debt" value={`$${(fisL.debt/1000).toFixed(1)}T`}
          chg={`+${((fisL.debt - d.fiscal[0].debt)/1000).toFixed(1)}T yr`} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* ISM */}
        <Card title="ISM Manufacturing vs Services PMI" badge="Growth Cycle" badgeColor="text-cyan-400">
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={d.ism} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={11} />
              <YAxis tick={AX} domain={[42,62]} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <ReferenceLine y={50} stroke="#ef4444" strokeWidth={1} strokeDasharray="4 4"
                label={{ value:"50", fill:"#ef4444", fontSize:9, position:"insideTopRight" }} />
              <Line dataKey="mfg" name="ISM Mfg"      stroke={C.cyan}  dot={false} strokeWidth={1.5} />
              <Line dataKey="svc" name="ISM Services" stroke={C.amber} dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Inflation */}
        <Card title="Headline CPI vs Core PCE vs 10Y Breakeven" badge="Inflation Complex" badgeColor="text-rose-400">
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={d.inflation} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={11} />
              <YAxis tick={AX} tickFormatter={v=>`${v.toFixed(1)}%`} width={44} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <ReferenceLine y={2} stroke="#64748b" strokeDasharray="3 3" label={{ value:"2% target", fill:"#64748b", fontSize:8 }} />
              <Line dataKey="cpi" name="CPI YoY"      stroke={C.rose}   dot={false} strokeWidth={1.5} />
              <Line dataKey="pce" name="Core PCE"     stroke={C.orange} dot={false} strokeWidth={1.5} />
              <Line dataKey="bei" name="10Y Breakeven" stroke={C.violet} dot={false} strokeWidth={1.5} strokeDasharray="4 3" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Fiscal */}
        <Card title="US Gross National Debt vs Blended Average Interest Rate" badge="Fiscal Risk" badgeColor="text-red-400" className="xl:col-span-2">
          <p className="text-[9px] text-slate-600 -mt-1">
            Interest expense = Debt × Blended Rate. Rising rate on growing stock = compounding fiscal pressure.
          </p>
          <ResponsiveContainer width="100%" height={210}>
            <ComposedChart data={d.fiscal} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={11} />
              <YAxis yAxisId="l" tick={AX} tickFormatter={v=>`$${(v/1000).toFixed(0)}T`} width={46} />
              <YAxis yAxisId="r" orientation="right" tick={AX} tickFormatter={v=>`${v.toFixed(1)}%`} width={40} />
              <Tooltip content={<CT />} formatter={(v:number, n:string) =>
                [n.includes("Debt") ? `$${(v/1000).toFixed(2)}T` : `${v.toFixed(2)}%`, n]} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Area yAxisId="l" dataKey="debt" name="Gross National Debt"  stroke={C.rose}  fill="rgba(244,63,94,0.1)" dot={false} strokeWidth={1.5} />
              <Line yAxisId="r" dataKey="rate" name="Blended Interest Rate" stroke={C.amber} dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 7 — SYSTEMIC RISK & REGIME COCKPIT
// ─────────────────────────────────────────────────────────────────────────────
function SystemicTab({ d, score }: { d: MD["systemic"]; score: number }) {
  const signals = [
    { name: "Hindenburg Omen",       active: d.hindenburg,    desc: "≥2 NH/NL signals in 30 days — distribution in breadth" },
    { name: "Titanic Syndrome",      active: d.titanic,       desc: "Nasdaq new highs diverge from NYSE — internal weakness" },
    { name: "VIX > 200-Day MA",      active: d.vixAboveMA,   desc: "Volatility regime transition — elevated tail risk" },
    { name: "Yield Curve Inverted",  active: d.yieldInverted, desc: "2Y > 10Y — historical recession predictor (T+12–18mo)" },
    { name: "NAAIM Exposure > 80%",  active: d.naaimHigh,    desc: "Active manager overexposure — contrarian crowding risk" },
    { name: "McClellan NYSI < 0",    active: d.mclellanNeg,  desc: "Breadth thrust in negative territory — down momentum" },
  ];

  const scColor = score >= 7 ? "text-red-400" : score >= 5 ? "text-orange-400" : score >= 3 ? "text-amber-400" : "text-emerald-400";
  const scBg    = score >= 7 ? "bg-red-950/40 border-red-900/60"
                : score >= 5 ? "bg-orange-950/40 border-orange-900/60"
                : score >= 3 ? "bg-amber-950/40 border-amber-900/60"
                : "bg-emerald-950/40 border-emerald-900/60";
  const scLabel = score >= 7 ? "🔴 EXTREME STRESS — Defensive posture recommended"
                : score >= 5 ? "🟠 ELEVATED RISK — Reduce beta, raise quality"
                : score >= 3 ? "🟡 MODERATE CAUTION — Selective exposure, hedge tails"
                : "🟢 LOW SYSTEMIC RISK — Risk-on, but remain vigilant";

  const mcNYSI   = d.mcclellan[d.mcclellan.length-1].nysi;
  const naaimNow = d.sentiment[d.sentiment.length-1].naaim;
  const aaiiNow  = d.sentiment[d.sentiment.length-1].aaii;
  const nfciNow  = d.stress[d.stress.length-1].nfci;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Metric label="Risk Score" value={`${score}/10`}
          chg={score >= 7 ? "-Extreme" : score >= 5 ? "-Elevated" : score >= 3 ? "±Moderate" : "+Benign"} />
        <Metric label="NYSI Breadth" value={mcNYSI.toFixed(0)}
          chg={+mcNYSI > 0 ? "+Positive momentum" : "-Negative momentum"} />
        <Metric label="NAAIM Exposure" value={`${naaimNow.toFixed(0)}%`}
          chg={+naaimNow > 75 ? "-Crowded long" : +naaimNow < 35 ? "+Washed out" : "±Neutral"} />
        <Metric label="AAII Bull−Bear" value={`${aaiiNow.toFixed(0)}`}
          chg={+aaiiNow > 20 ? "-Bullish extreme" : +aaiiNow < -10 ? "+Bearish extreme" : "±Neutral"} />
        <Metric label="NFCI" value={nfciNow.toFixed(3)}
          chg={+nfciNow > 0.1 ? "-Tightening conditions" : "+Accommodative"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Risk Score + Signal Grid */}
        <Card title="Aggregate Systemic Risk Cockpit">
          <div className={`flex items-center gap-4 p-3 rounded-xl border ${scBg} mb-1`}>
            <div className="text-center shrink-0">
              <div className="text-[9px] text-slate-500 uppercase tracking-widest mb-1">Systemic Risk</div>
              <div className={`text-5xl font-black font-mono leading-none ${scColor}`}>
                {score}<span className="text-xl font-semibold">/10</span>
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="h-2.5 bg-slate-800 rounded-full overflow-hidden mb-2">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${score>=7?"bg-red-500":score>=5?"bg-orange-500":score>=3?"bg-amber-500":"bg-emerald-500"}`}
                  style={{ width: `${score * 10}%` }}
                />
              </div>
              <p className="text-[10px] text-slate-300 font-medium">{scLabel}</p>
            </div>
          </div>

          <div className="space-y-1.5 mt-2">
            {signals.map(sig => (
              <div key={sig.name}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg ${sig.active ? "bg-red-950/50 border border-red-900/40" : "bg-slate-800/50 border border-transparent"}`}
              >
                <div className={`w-2 h-2 rounded-full shrink-0 ${sig.active ? "bg-red-400 shadow-[0_0_8px_#f87171]" : "bg-slate-600"}`} />
                <div className="flex-1 min-w-0">
                  <div className={`text-[11px] font-semibold ${sig.active ? "text-red-300" : "text-slate-400"}`}>{sig.name}</div>
                  <div className="text-[9px] text-slate-600 truncate">{sig.desc}</div>
                </div>
                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded shrink-0 ${sig.active ? "bg-red-900/60 text-red-300" : "bg-slate-700 text-slate-500"}`}>
                  {sig.active ? "ACTIVE" : "CLEAR"}
                </span>
              </div>
            ))}
          </div>
        </Card>

        {/* McClellan Summation */}
        <Card title="McClellan Summation Index (NYSI) — Breadth Velocity" badge="NYSE Breadth" badgeColor="text-sky-400">
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={d.mcclellan} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={50} />
              <YAxis tick={AX} width={44} />
              <Tooltip content={<CT />} />
              <ReferenceLine y={0}    stroke="#94a3b8" strokeWidth={1.5} label={{ value:"0", fill:"#94a3b8", fontSize:9 }} />
              <ReferenceLine y={500}  stroke={C.emerald} strokeDasharray="3 3" strokeWidth={1} />
              <ReferenceLine y={-500} stroke={C.rose}   strokeDasharray="3 3" strokeWidth={1} />
              <Area dataKey="nysi" name="NYSI" stroke={C.sky} fill="rgba(56,189,248,0.08)" dot={false} strokeWidth={1.5} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        {/* NAAIM vs AAII */}
        <Card title="NAAIM Exposure Index vs AAII Bull/Bear Spread (4W Smooth)" badge="Contrarian Sentiment" badgeColor="text-violet-400">
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={d.sentiment} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={12} />
              <YAxis yAxisId="l" tick={AX} domain={[0,100]} tickFormatter={v=>`${v.toFixed(0)}%`} width={38} />
              <YAxis yAxisId="r" orientation="right" tick={AX} domain={[-45,60]} width={38} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <ReferenceLine yAxisId="l" y={80} stroke={C.rose}   strokeDasharray="3 3" strokeWidth={1} />
              <ReferenceLine yAxisId="l" y={30} stroke={C.emerald} strokeDasharray="3 3" strokeWidth={1} />
              <Line yAxisId="l" dataKey="naaim" name="NAAIM Exposure" stroke={C.violet} dot={false} strokeWidth={1.5} />
              <Line yAxisId="r" dataKey="aaii"  name="AAII B−Bear"   stroke={C.amber}  dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* NFCI + BofA FSI */}
        <Card title="Chicago Fed NFCI vs BofA Financial Stress Index" badge="Liquidity Stress" badgeColor="text-rose-400">
          <p className="text-[9px] text-slate-600 -mt-1">Positive = tighter/riskier conditions than average. Negative = easy/accommodative.</p>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={d.stress} margin={CM}>
              <CartesianGrid {...GP} />
              <XAxis dataKey="d" tick={AX} interval={50} />
              <YAxis yAxisId="l" tick={AX} domain={["auto","auto"]} tickFormatter={v=>v.toFixed(2)} width={42} />
              <YAxis yAxisId="r" orientation="right" tick={AX} domain={["auto","auto"]} tickFormatter={v=>v.toFixed(2)} width={42} />
              <Tooltip content={<CT />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <ReferenceLine yAxisId="l" y={0} stroke="#475569" strokeDasharray="3 3" />
              <Line yAxisId="l" dataKey="nfci"    name="Chicago NFCI" stroke={C.rose}   dot={false} strokeWidth={1.5} />
              <Line yAxisId="r" dataKey="bofaFsi" name="BofA FSI"     stroke={C.orange} dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB DEFINITIONS
// ─────────────────────────────────────────────────────────────────────────────
const TABS = [
  { id: "rates",    icon: "📈", label: "Rates",    sub: "Fixed Income"  },
  { id: "equities", icon: "📊", label: "Equities", sub: "Global Breadth" },
  { id: "options",  icon: "⚡", label: "Options",  sub: "Volatility"    },
  { id: "fx",       icon: "💱", label: "FX",       sub: "Currencies"    },
  { id: "energy",   icon: "🛢️", label: "Energy",   sub: "Commodities"   },
  { id: "macro",    icon: "📉", label: "Macro",    sub: "Economic"      },
  { id: "systemic", icon: "🛡️", label: "Systemic", sub: "Risk Cockpit"  },
] as const;

type TabId = typeof TABS[number]["id"];

// ─────────────────────────────────────────────────────────────────────────────
// MAIN DASHBOARD
// ─────────────────────────────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type LivePayload = Record<string, any>;

function nonEmpty<T>(arr: T[] | null | undefined): arr is T[] {
  return Array.isArray(arr) && arr.length > 0;
}

function mergeLive(mock: ReturnType<typeof buildMockData>, L: LivePayload): ReturnType<typeof buildMockData> {
  const r = L.rates ?? {};
  const eq = L.equities ?? {};
  const opt = L.options ?? {};
  const fx = L.fx ?? {};
  const en = L.energy ?? {};
  const sys = L.systemic ?? {};

  // Live intraday rates arrive as {t, y5, y10} — remap y5 → y2 for RatesTab
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const intraMapped = (r.intradayRates ?? []).map((p: any) => ({
    t: p.t, y2: p.y5 ?? p.y2 ?? 0, y10: p.y10 ?? 0,
  }));

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return {
    ...mock,
    rates: {
      ...mock.rates,
      ...(nonEmpty(intraMapped)        && { intradayRates: intraMapped }),
      ...(nonEmpty(r.spreadHistory)    && { spreadHistory: r.spreadHistory }),
    },
    equities: {
      ...mock.equities,
      ...(nonEmpty(eq.spyRsp)          && { spyRsp: eq.spyRsp }),
      ...(nonEmpty(eq.soxx)            && { soxx: eq.soxx }),
      ...(eq.intlData                  && { intlData: eq.intlData }),
    },
    options: {
      ...mock.options,
      ...(nonEmpty(opt.vixData)        && { vixData: opt.vixData }),
      ...(nonEmpty(opt.pcrDaily)       && {
        pcrDaily:   opt.pcrDaily,
        eqPcrLast:  opt.eqPcrLast  ?? mock.options.eqPcrLast,
        totPcrLast: opt.totPcrLast ?? mock.options.totPcrLast,
        eqMa20Last: opt.eqMa20Last ?? mock.options.eqMa20Last,
      }),
    },
    fx: {
      ...mock.fx,
      ...(nonEmpty(fx.usdjpy)          && { usdjpy: fx.usdjpy }),
      ...(nonEmpty(fx.audjpy)          && { audjpy: fx.audjpy }),
    },
    energy: {
      ...mock.energy,
      ...(nonEmpty(en.crude)           && { crude: en.crude }),
      ...(nonEmpty(en.cuGold)          && { cuGold: en.cuGold }),
      ...(nonEmpty(en.goldSilver)      && { goldSilver: en.goldSilver }),
    },
    systemic: {
      ...mock.systemic,
      ...(sys.vixAboveMA   !== undefined && { vixAboveMA:   sys.vixAboveMA }),
      ...(sys.yieldInverted !== undefined && { yieldInverted: sys.yieldInverted }),
    },
  } as ReturnType<typeof buildMockData>;
}

export default function MacroDashboard() {
  const [tab, setTab] = useState<TabId>("rates");
  const mock = useMemo(() => buildMockData(), []);
  const [livePayload, setLivePayload] = useState<LivePayload | null>(null);
  const [srcStatus, setSrcStatus] = useState<"loading" | "live" | "mock">("loading");
  const [pcrSource, setPcrSource] = useState<"cboe" | "mock">("mock");

  useEffect(() => {
    fetch("/api/macro/data")
      .then(res => { if (!res.ok) throw new Error(String(res.status)); return res.json(); })
      .then((payload: LivePayload) => {
        setLivePayload(payload);
        setSrcStatus("live");
        setPcrSource(payload.pcrSource === "cboe" ? "cboe" : "mock");
      })
      .catch(() => setSrcStatus("mock"));
  }, []);

  const data = useMemo(() => {
    if (!livePayload) return mock;
    return mergeLive(mock, livePayload);
  }, [mock, livePayload]);

  const scoreColor =
    data.riskScore >= 7 ? "bg-red-900/30 text-red-400 border-red-800/50"
    : data.riskScore >= 5 ? "bg-orange-900/30 text-orange-400 border-orange-800/50"
    : data.riskScore >= 3 ? "bg-amber-900/30 text-amber-400 border-amber-800/50"
    : "bg-emerald-900/30 text-emerald-400 border-emerald-800/50";

  const srcBadge =
    srcStatus === "loading" ? { label: "⟳ Fetching…",    cls: "text-slate-500"  }
    : srcStatus === "live"  ? { label: "● Live",          cls: "text-emerald-400" }
    :                         { label: "○ Mock",          cls: "text-amber-500"   };

  // pcrSource only matters once livePayload arrives
  const pcrBadge = srcStatus === "live"
    ? (pcrSource === "cboe" ? "CBOE live" : "PCR mock")
    : "";

  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100 min-h-0">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-slate-800 shrink-0 gap-4">
        <div>
          <h1 className="text-base font-bold text-slate-100 tracking-tight">Cross-Asset Macro Dashboard</h1>
          <p className="text-[10px] text-slate-500">
            7 asset classes · 25+ charts ·{" "}
            <span className={`font-semibold ${srcBadge.cls}`}>{srcBadge.label}</span>
            {pcrBadge && <span className="ml-2 text-slate-600">· PCR: {pcrBadge}</span>}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold ${scoreColor}`}>
            <div className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
            Systemic Risk: {data.riskScore}/10
          </div>
          <div className="text-[10px] text-slate-700 font-mono">
            {new Date().toLocaleDateString("en-US", { weekday:"short", month:"short", day:"numeric", year:"numeric" })}
          </div>
        </div>
      </div>

      {/* ── Tab Bar ──────────────────────────────────────────────────────────── */}
      <div className="flex gap-0.5 px-4 pt-3 shrink-0 border-b border-slate-800 overflow-x-auto">
        {TABS.map(({ id, icon, label, sub }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex flex-col items-center px-4 py-2 rounded-t-lg text-[11px] font-medium transition-all whitespace-nowrap border-b-2 -mb-px ${
              tab === id
                ? "border-sky-500 text-sky-400 bg-slate-800/60"
                : "border-transparent text-slate-500 hover:text-slate-300 hover:bg-slate-800/30"
            }`}
          >
            <span>{icon} {label}</span>
            <span className="text-[9px] text-slate-600 mt-0.5">{sub}</span>
          </button>
        ))}
      </div>

      {/* ── Content ──────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-4 min-h-0">
        {tab === "rates"    && <RatesTab    d={data.rates} />}
        {tab === "equities" && <EquitiesTab d={data.equities} />}
        {tab === "options"  && <OptionsTab  d={data.options} />}
        {tab === "fx"       && <FXTab       d={data.fx} />}
        {tab === "energy"   && <EnergyTab   d={data.energy} />}
        {tab === "macro"    && <MacroTab    d={data.macro} />}
        {tab === "systemic" && <SystemicTab d={data.systemic} score={data.riskScore} />}
      </div>
    </div>
  );
}
