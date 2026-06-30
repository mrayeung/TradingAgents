/**
 * Typed API client for the TradingDesk engine (localhost:8765).
 *
 * All calls target /api/* which next.config.mjs rewrites to
 * http://localhost:8765/* — so there's zero CORS overhead in production.
 * During `next dev` the Next.js dev proxy handles the rewrite automatically.
 */

const BASE = "/api";

// ─── Type definitions ────────────────────────────────────────────────────────

export interface AnalystVerdicts {
  market: string;
  sentiment: string;
  news: string;
  fundamentals: string;
  valuation: string;
  market_technician: string;
  quantitative: string;
}

export interface SignalRow {
  ticker: string;
  date: string;
  age_days: number;
  stale: boolean;
  rating: "BUY" | "HOLD" | "SELL" | string;
  conviction: number;       // 0..1
  expected_return: number;  // e.g. 0.25
  win_prob: number;         // e.g. 0.70
  analyst_verdicts: AnalystVerdicts;
  report_path: string;
}

export interface PortfolioConstructResult {
  weights: Record<string, number>;
  expected_return: number | null;
  volatility: number | null;
  sharpe: number | null;
  bl_returns: Record<string, number>;
  /** Server may populate this when one or more tickers had no price data */
  invalid_tickers?: string[];
}

export interface CorrelationResult {
  tickers: string[];
  matrix: number[][];
  high_pairs: { a: string; b: string; r: number }[];
}

export interface SizingPosition {
  ticker: string;
  weight: number;
  kelly_f: number | null;
  half_kelly: number | null;
  correlation_penalty: number;
  final_size: number;
}

export interface BenchmarkSummary {
  portfolio_return: number;
  spy_return: number;
  qqq_return: number;
  dia_return: number;
  portfolio_volatility: number;
  sharpe_vs_spy: number;
}

export interface BenchmarkResult {
  dates: string[];
  portfolio_values: number[];
  spy_values: number[];
  qqq_values: number[];
  dia_values: number[];
  summary: BenchmarkSummary;
}

export interface RebalanceTrade {
  ticker: string;
  action: "BUY" | "SELL";
  delta_weight: number;
  dollar_amount: number;
  current_weight: number;
  target_weight: number;
}

// ─── API helpers ─────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`GET ${path} → ${res.status}: ${err}`);
  }
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`POST ${path} → ${res.status}: ${err}`);
  }
  return res.json();
}

// ─── Portfolio API ────────────────────────────────────────────────────────────

export const api = {
  /** Aggregate analyst conviction signals across all saved reports. */
  signals(): Promise<{ signals: SignalRow[] }> {
    return get("/portfolio/signals");
  },

  /** Run Black-Litterman + mean-variance optimisation. */
  construct(params: {
    tickers: string[];
    risk_aversion?: number;
    max_position?: number;
    min_position?: number;
    lookback_days?: number;
  }): Promise<PortfolioConstructResult> {
    return post("/portfolio/construct", params);
  },

  /** Pairwise return-correlation matrix. */
  correlation(tickers: string[], days = 90): Promise<CorrelationResult> {
    const q = new URLSearchParams({ tickers: tickers.join(","), days: String(days) });
    return get(`/portfolio/correlation?${q}`);
  },

  /** Kelly-criterion position sizes. */
  sizing(tickers: string[], weights: number[], days = 90): Promise<{ positions: SizingPosition[] }> {
    const q = new URLSearchParams({
      tickers: tickers.join(","),
      weights: weights.join(","),
      days: String(days),
    });
    return get(`/portfolio/sizing?${q}`);
  },

  /** Portfolio performance vs benchmarks. */
  benchmark(tickers: string[], weights: number[], days = 90): Promise<BenchmarkResult> {
    const q = new URLSearchParams({
      tickers: tickers.join(","),
      weights: weights.join(","),
      days: String(days),
    });
    return get(`/portfolio/benchmark?${q}`);
  },

  /** Compute rebalance trades. */
  rebalance(params: {
    current_holdings: Record<string, number>;
    target_weights: Record<string, number>;
    portfolio_value?: number;
  }): Promise<{ trades: RebalanceTrade[]; portfolio_value: number }> {
    return post("/portfolio/rebalance", params);
  },

  /** Start a TradingAgents analysis run. */
  startRun(cfg: Record<string, unknown>): Promise<{ run_id: string }> {
    return post("/runs", cfg);
  },

  /** List all saved reports, optionally filtered by ticker. */
  listReports(ticker?: string): Promise<{ reports: ReportSummary[] }> {
    const q = ticker ? `?ticker=${encodeURIComponent(ticker)}` : "";
    return get(`/reports${q}`);
  },

  /** Fetch a full report document for ticker + date. */
  getReport(ticker: string, date: string): Promise<FullReport> {
    return get(`/reports?ticker=${encodeURIComponent(ticker)}&date=${encodeURIComponent(date)}`);
  },
};

// ─── Report types ─────────────────────────────────────────────────────────────

export interface ReportSummary {
  ticker: string;
  date: string;
  rating: string;
}

export interface FullReport {
  market_report?: string;
  sentiment_report?: string;
  news_report?: string;
  fundamentals_report?: string;
  valuation_report?: string;
  market_technician_report?: string;
  quantitative_report?: string;
  investment_debate_state?: { history?: string; bull_history?: string; bear_history?: string };
  risk_debate_state?: { history?: string };
  final_trade_decision?: string;
  [key: string]: unknown;
}
