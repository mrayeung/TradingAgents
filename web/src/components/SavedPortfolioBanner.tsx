"use client";

/**
 * Reusable banner that appears at the top of Benchmark, Sizing, Correlation,
 * and Rebalance pages when a portfolio has been saved from the Construct page.
 *
 * Props:
 *   onLoad — called when the user clicks "Load"; the parent should apply the
 *            returned strings to its own tickerInput / weightInput state.
 */

import { usePortfolioStore, weightsToInputs, savedLabel } from "@/lib/portfolio-store";

interface Props {
  onLoad: (tickerInput: string, weightInput: string) => void;
  /** Set to true once the parent has applied the saved values. */
  loaded?: boolean;
}

export default function SavedPortfolioBanner({ onLoad, loaded = false }: Props) {
  const { savedPortfolio } = usePortfolioStore();
  if (!savedPortfolio) return null;

  const pairs = Object.entries(savedPortfolio.weights).sort(([, a], [, b]) => b - a);
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

  const handleLoad = () => {
    const { tickerInput, weightInput } = weightsToInputs(savedPortfolio);
    onLoad(tickerInput, weightInput);
  };

  return (
    <div className="mb-5 flex items-center gap-3 px-4 py-3 bg-sky-900/20 border border-sky-800/50 rounded-xl text-sm">
      <span className="text-sky-400 shrink-0 text-base">📋</span>
      <div className="flex-1 min-w-0">
        <span className="text-slate-300 font-medium">Saved portfolio</span>
        <span className="text-slate-500 ml-2 text-xs">{savedLabel(savedPortfolio.savedAt)}</span>
        <div className="flex gap-2 mt-1 flex-wrap">
          {pairs.map(([ticker, w]) => (
            <span key={ticker} className="text-xs text-slate-400">
              <span className="text-slate-200 font-mono">{ticker}</span>
              <span className="text-slate-600 ml-0.5">{pct(w)}</span>
            </span>
          ))}
        </div>
      </div>
      <button
        onClick={handleLoad}
        className={`px-4 py-1.5 rounded-lg text-xs font-medium transition-colors shrink-0 ${
          loaded
            ? "bg-emerald-800/60 text-emerald-300 cursor-default"
            : "bg-sky-600 hover:bg-sky-500 text-white"
        }`}
      >
        {loaded ? "✓ Loaded" : "↙ Use this portfolio"}
      </button>
    </div>
  );
}
