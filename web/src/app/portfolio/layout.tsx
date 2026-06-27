import { PortfolioStoreProvider } from "@/lib/portfolio-store";

/**
 * Portfolio sub-layout.
 *
 * Wraps every /portfolio/* page with the shared portfolio store.
 * Because this layout never unmounts during inter-page navigation,
 * the store (form inputs, saved portfolio) persists across Signals →
 * Construct → Benchmark → Sizing → Correlation → Rebalance.
 */
export default function PortfolioLayout({ children }: { children: React.ReactNode }) {
  return <PortfolioStoreProvider>{children}</PortfolioStoreProvider>;
}
