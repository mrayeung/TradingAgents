"use client";

/**
 * Shared portfolio store — persists state across all /portfolio/* pages.
 *
 * Placed in the portfolio layout so the provider never unmounts during
 * inter-page navigation, preserving form inputs, saved portfolio data,
 * and active analysis runs (so navigating away from Signals doesn't lose
 * run tracking).
 */

import { createContext, useContext, useState, ReactNode, useCallback } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ConstructInputs {
  tickerInput: string;
  riskAversion: number;
  maxPosition: number;
  minPosition: number;
  lookbackDays: number;
}

export interface SavedPortfolio {
  tickers: string[];
  weights: Record<string, number>;
  savedAt: string;
  expectedReturn: number;
  volatility: number;
  sharpe: number;
}

export interface ActiveRun {
  runId: string;
  ticker: string;
  status: "warming" | "started" | "done" | "error" | "cancelled" | "pending";
  startedAt: number;
}

interface PortfolioStore {
  // Form state — survives navigation back to Construct
  constructInputs: ConstructInputs;
  patchConstructInputs: (patch: Partial<ConstructInputs>) => void;

  // The last explicitly saved portfolio — flows into Benchmark, Sizing, etc.
  savedPortfolio: SavedPortfolio | null;
  savePortfolio: (p: SavedPortfolio) => void;

  // Active analysis runs — survives navigation away from Signals
  activeRuns: ActiveRun[];
  addRun: (run: ActiveRun) => void;
  updateRun: (runId: string, patch: Partial<ActiveRun>) => void;
  dismissRun: (runId: string) => void;
  setAllRuns: (runs: ActiveRun[]) => void;
}

// ─── Defaults ─────────────────────────────────────────────────────────────────

const DEFAULT_INPUTS: ConstructInputs = {
  tickerInput: "AAPL,MSFT,GOOGL,AMZN,NVDA",
  riskAversion: 2.5,
  maxPosition: 0.40,
  minPosition: 0.02,
  lookbackDays: 90,
};

// ─── Context ──────────────────────────────────────────────────────────────────

const PortfolioContext = createContext<PortfolioStore | null>(null);

export function PortfolioStoreProvider({ children }: { children: ReactNode }) {
  const [constructInputs, setConstructInputs] = useState<ConstructInputs>(DEFAULT_INPUTS);
  const [savedPortfolio, setSavedPortfolio] = useState<SavedPortfolio | null>(null);
  const [activeRuns, setActiveRuns] = useState<ActiveRun[]>([]);

  const patchConstructInputs = useCallback((patch: Partial<ConstructInputs>) => {
    setConstructInputs(prev => ({ ...prev, ...patch }));
  }, []);

  const savePortfolio = useCallback((p: SavedPortfolio) => {
    setSavedPortfolio(p);
  }, []);

  const addRun = useCallback((run: ActiveRun) => {
    setActiveRuns(prev => [run, ...prev]);
  }, []);

  const updateRun = useCallback((runId: string, patch: Partial<ActiveRun>) => {
    setActiveRuns(prev => prev.map(r => r.runId === runId ? { ...r, ...patch } : r));
  }, []);

  const dismissRun = useCallback((runId: string) => {
    setActiveRuns(prev => prev.filter(r => r.runId !== runId));
  }, []);

  const setAllRuns = useCallback((runs: ActiveRun[]) => {
    setActiveRuns(runs);
  }, []);

  return (
    <PortfolioContext.Provider value={{
      constructInputs, patchConstructInputs,
      savedPortfolio, savePortfolio,
      activeRuns, addRun, updateRun, dismissRun, setAllRuns,
    }}>
      {children}
    </PortfolioContext.Provider>
  );
}

export function usePortfolioStore(): PortfolioStore {
  const ctx = useContext(PortfolioContext);
  if (!ctx) throw new Error("usePortfolioStore must be used inside PortfolioStoreProvider");
  return ctx;
}

// ─── Helpers shared across pages ──────────────────────────────────────────────

export function weightsToInputs(saved: SavedPortfolio): { tickerInput: string; weightInput: string } {
  const pairs = Object.entries(saved.weights).sort(([, a], [, b]) => b - a);
  return {
    tickerInput: pairs.map(([t]) => t).join(","),
    weightInput: pairs.map(([, w]) => w.toFixed(4)).join(","),
  };
}

export function savedLabel(isoString: string): string {
  const d = new Date(isoString);
  return `saved at ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}
