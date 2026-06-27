/**
 * Shared types for 13F holdings data, used by both the API route
 * and the institution detail/tile pages.
 */

export interface ProcessedHolding {
  rank: number;
  name: string;
  cusip: string;
  value: number;             // in $1 000s (raw, as reported)
  valueMM: number;           // in $M (rounded)
  shares: number;
  pctPortfolio: number;      // 0–100
  change: "new" | "increased" | "decreased" | "unchanged";
  changePctShares: number | null; // signed %, null if no prior period data
}

export interface HoldingsPayload {
  filingDate: string;        // ISO date of latest 13F-HR, e.g. "2025-02-14"
  quarter: string;           // e.g. "Q4 2024"
  totalValueMM: number;      // total equity value in $M
  positionCount: number;
  prevFilingDate: string | null;
  prevQuarter: string | null;
  holdings: ProcessedHolding[];
}
