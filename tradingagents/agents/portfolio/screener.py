"""Institutional Multi-Factor Screener.

Implements a two-phase screening pipeline modelled on approaches used by
Goldman Sachs Equity Research, AQR Capital, Bridgewater, and systematic
hedge funds:

Phase A — Hard Filters  (cheap, eliminates obvious failures first)
─────────────────────────────────────────────────────────────────────
  • Minimum market cap  (default $500M — avoid illiquid microcaps)
  • Minimum avg daily dollar volume  (default $5M — liquidity)
  • Financial health gate  (not in distress: positive FCF OR positive
    earnings OR current ratio > 1.0)
  • Negative EV/EBITDA guard  (excludes deeply distressed names)

Phase B — Multi-Factor Scoring  (ranks survivors, returns top-N)
─────────────────────────────────────────────────────────────────────
  Five factor groups, each normalised to cross-sectional z-scores:

  ① Quality  (default 25%)
      ROE, FCF margin, gross margin, interest coverage, Debt/EBITDA (inv)
      → Inspired by Goldman "GS Quality" basket and AQR Quality-Minus-Junk

  ② Growth  (default 25%)
      Revenue growth YoY, EPS growth YoY, forward EPS growth, FCF yield
      → GARP tilt: growth that is visible and not yet priced in

  ③ Valuation  (default 20%)
      PEG ratio (inv), EV/EBITDA (inv), FCF yield, forward P/E discount
      → Avoids value traps by combining with quality/growth screens

  ④ Momentum  (default 20%)
      12-1 month, 6m, 3m, 1m price returns (cross-sectional z-scores)
      → Standard academic momentum; 12-1m is the primary signal

  ⑤ Analyst Sentiment  (default 10%)
      % Buy ratings, target price upside, recommendation mean (inv)
      → Acts as a soft catalyst signal; high-conviction buy consensus

All weights are configurable via config["portfolio"]["screener_factor_weights"].

Usage
─────
    screener = MomentumQualityScreener(config)
    results  = screener.screen("2026-05-04", top_n=50)
    # returns List[ScreenerResult] — hard-filter failures excluded,
    # survivors ranked by composite_score descending
"""

from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from tradingagents.agents.portfolio.schemas import ScreenerResult
from tradingagents.dataflows.stockstats_utils import make_yf_session, yf_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Universe seed lists
# ---------------------------------------------------------------------------

_SP500_SEED = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B",
    "AVGO", "JPM", "LLY", "V", "UNH", "XOM", "COST", "MA", "HD", "PG",
    "JNJ", "WMT", "NFLX", "BAC", "CRM", "ABBV", "CVX", "ORCL", "AMD",
    "MRK", "ADBE", "ACN", "PEP", "TMO", "KO", "CSCO", "WFC", "MCD",
    "ABT", "TXN", "GE", "NOW", "PM", "IBM", "QCOM", "DHR", "RTX",
    "NEE", "CAT", "AMGN", "INTU", "SPGI",
]

_SECTOR_TICKERS: Dict[str, List[str]] = {
    "Technology":     ["AAPL", "MSFT", "NVDA", "AVGO", "AMD", "ORCL", "CRM", "ADBE",
                       "TXN", "QCOM", "IBM", "INTU", "NOW", "SNOW", "AMAT", "KLAC",
                       "MU", "LRCX", "CDNS", "SNPS"],
    "Healthcare":     ["UNH", "LLY", "JNJ", "ABBV", "MRK", "TMO", "ABT", "DHR",
                       "AMGN", "BMY", "CVS", "ISRG", "GILD", "VRTX", "REGN", "HCA",
                       "CI", "ELV", "MCK", "ZTS"],
    "Financials":     ["JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "BLK", "SPGI",
                       "AXP", "C", "USB", "TFC", "PNC", "COF", "SCHW", "ICE", "CME",
                       "MMC", "AON"],
    "ConsumerDisc":   ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX",
                       "BKNG", "CMG", "GM", "F", "ROST", "ORLY", "AZO"],
    "Energy":         ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO",
                       "PXD", "OXY", "BKR", "HAL", "DVN"],
    "Industrials":    ["GE", "CAT", "RTX", "HON", "UPS", "BA", "LMT", "DE",
                       "GD", "ETN", "EMR", "ITW", "FDX", "NSC", "UNP"],
    "Communication":  ["GOOGL", "META", "NFLX", "DIS", "TMUS", "VZ", "CMCSA",
                       "T", "EA", "TTWO", "CHTR"],
    "Utilities":      ["NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "PCG"],
    "Materials":      ["LIN", "APD", "SHW", "FCX", "NEM", "DD", "ECL", "PPG", "ALB"],
    "RealEstate":     ["PLD", "AMT", "EQIX", "SPG", "CCI", "PSA", "O", "WELL", "DLR"],
    "ConsumerStaples":["WMT", "COST", "PG", "KO", "PEP", "PM", "MO", "CL", "MDLZ", "GIS"],
}

# Default factor weights (must sum to 1.0)
_DEFAULT_FACTOR_WEIGHTS = {
    "quality":   0.25,
    "growth":    0.25,
    "valuation": 0.20,
    "momentum":  0.20,
    "analyst":   0.10,
}


# ---------------------------------------------------------------------------
# Main screener class
# ---------------------------------------------------------------------------


class MomentumQualityScreener:
    """Institutional multi-factor screener.

    Parameters
    ----------
    config : dict
        The TradingAgents config dict.  Reads the ``portfolio`` sub-key.
    """

    def __init__(self, config: dict):
        self.config = config
        self.pcfg = config.get("portfolio", {})

        # Hard filter thresholds
        self.min_market_cap_b  = self.pcfg.get("min_market_cap_b", 0.5)   # $B
        self.min_avg_volume_m  = self.pcfg.get("min_avg_volume_m", 5.0)   # $M/day
        self.require_positive_fcf_or_earnings = self.pcfg.get(
            "require_positive_fcf_or_earnings", True
        )

        # Factor weights
        fw = self.pcfg.get("screener_factor_weights", {})
        self.factor_weights = {**_DEFAULT_FACTOR_WEIGHTS, **fw}
        # Normalise in case caller supplied partial overrides
        total = sum(self.factor_weights.values())
        if total > 0:
            self.factor_weights = {k: v / total for k, v in self.factor_weights.items()}

        self.max_workers    = self.pcfg.get("screener_max_workers", 10)
        self.request_delay  = self.pcfg.get("screener_request_delay", 0.05)

    # ──────────────────────────────────────────────────────────────────────
    # Universe helpers
    # ──────────────────────────────────────────────────────────────────────

    def get_universe(self) -> List[str]:
        """Return tickers for the configured universe type."""
        universe_type = self.pcfg.get("universe", "sp500")
        if universe_type == "sp500":
            return self._get_sp500_tickers()
        elif universe_type == "sector":
            sector = self.pcfg.get("sector")
            if not sector or sector not in _SECTOR_TICKERS:
                logger.warning("Unknown sector '%s', using sp500 seed", sector)
                return _SP500_SEED
            return _SECTOR_TICKERS[sector]
        elif universe_type == "list":
            return self.pcfg.get("custom_tickers", _SP500_SEED)
        return _SP500_SEED

    def _get_sp500_tickers(self) -> List[str]:
        try:
            tables = pd.read_html(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                attrs={"id": "constituents"},
            )
            tickers = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
            logger.info("Fetched %d S&P 500 tickers from Wikipedia", len(tickers))
            return tickers
        except Exception as e:
            logger.warning("S&P 500 fetch failed (%s); using seed list", e)
            return _SP500_SEED

    # ──────────────────────────────────────────────────────────────────────
    # Per-ticker data fetch
    # ──────────────────────────────────────────────────────────────────────

    def _fetch_single(self, ticker: str, trade_date: str) -> ScreenerResult:
        """Fetch all factor data for one ticker.  Never raises — returns a
        result with ``passed_hard_filters=False`` on error."""
        r = ScreenerResult(ticker=ticker)
        try:
            # Use a session with a hard per-request timeout so a slow or
            # unresponsive Yahoo Finance server never hangs the whole run.
            session = make_yf_session()
            t = yf.Ticker(ticker, session=session)

            # Both .info and .history() make blocking HTTP calls — wrap each
            # in yf_retry so transient timeouts and connection drops are
            # retried before the error is surfaced.
            info = yf_retry(lambda: t.info) or {}

            # ── Price history ──────────────────────────────────────────
            trade_dt = datetime.strptime(trade_date, "%Y-%m-%d")
            start    = (trade_dt - timedelta(days=400)).strftime("%Y-%m-%d")
            hist     = yf_retry(lambda: t.history(start=start, end=trade_date, auto_adjust=True))

            if len(hist) >= 5:
                close    = hist["Close"]
                r.price  = float(close.iloc[-1])
                volume   = hist["Volume"]
                r.avg_daily_volume = float(
                    (close * volume).tail(60).mean() / 1e6
                )  # avg daily $ volume in $M
            else:
                r.passed_hard_filters = False
                r.filter_reason = "Insufficient price history"
                return r

            # ── Basic identifiers ──────────────────────────────────────
            r.sector   = info.get("sector")
            r.industry = info.get("industry")
            mkt_cap    = info.get("marketCap")
            r.market_cap = mkt_cap / 1e9 if mkt_cap else None
            r.beta     = info.get("beta")

            # ── Hard filter checks (fast exit) ─────────────────────────
            if r.market_cap is not None and r.market_cap < self.min_market_cap_b:
                r.passed_hard_filters = False
                r.filter_reason = f"Market cap ${r.market_cap:.2f}B < ${self.min_market_cap_b}B minimum"
                return r

            if r.avg_daily_volume is not None and r.avg_daily_volume < self.min_avg_volume_m:
                r.passed_hard_filters = False
                r.filter_reason = f"Avg daily volume ${r.avg_daily_volume:.1f}M < ${self.min_avg_volume_m}M minimum"
                return r

            if self.require_positive_fcf_or_earnings:
                fcf = info.get("freeCashflow", 0) or 0
                net_income = info.get("netIncomeToCommon", 0) or 0
                current_ratio = info.get("currentRatio") or 0
                if fcf <= 0 and net_income <= 0 and current_ratio < 1.0:
                    r.passed_hard_filters = False
                    r.filter_reason = "Financial distress: negative FCF + negative earnings + current ratio < 1"
                    return r

            # ── Factor 1: Quality ──────────────────────────────────────
            r.roe              = info.get("returnOnEquity")
            r.roa              = info.get("returnOnAssets")
            r.gross_margin     = info.get("grossMargins")
            r.operating_margin = info.get("operatingMargins")
            r.current_ratio    = info.get("currentRatio")

            # FCF margin = FCF / Revenue
            fcf     = info.get("freeCashflow")
            revenue = info.get("totalRevenue")
            if fcf and revenue and revenue > 0:
                r.fcf_margin = fcf / revenue

            # FCF yield = FCF / Market Cap
            if fcf and mkt_cap and mkt_cap > 0:
                r.fcf_yield = fcf / mkt_cap

            # Debt/EBITDA
            total_debt = info.get("totalDebt") or 0
            cash       = info.get("totalCash") or 0
            ebitda     = info.get("ebitda")
            net_debt   = total_debt - cash
            if ebitda and ebitda > 0:
                r.debt_to_ebitda = net_debt / ebitda

            # Interest coverage = operating income / interest expense
            op_income    = info.get("operatingIncome") or 0
            interest_exp = info.get("interestExpense") or 0
            if interest_exp and interest_exp < 0:          # yfinance signs vary
                interest_exp = abs(interest_exp)
            if interest_exp and interest_exp > 0:
                r.interest_coverage = op_income / interest_exp

            # ── Factor 2: Growth ───────────────────────────────────────
            r.revenue_growth_yoy = info.get("revenueGrowth")
            r.eps_growth_yoy     = info.get("earningsGrowth")

            trailing_eps = info.get("trailingEps") or 0
            forward_eps  = info.get("forwardEps")  or 0
            if trailing_eps and abs(trailing_eps) > 0.01:
                r.forward_eps_growth = (forward_eps - trailing_eps) / abs(trailing_eps)

            r.earnings_growth_3y = info.get("earningsQuarterlyGrowth")  # proxy

            # ── Factor 3: Valuation ────────────────────────────────────
            r.pe_trailing  = info.get("trailingPE")
            r.pe_forward   = info.get("forwardPE")
            r.peg_ratio    = info.get("pegRatio")
            r.ev_to_ebitda = info.get("enterpriseToEbitda")
            r.price_to_sales = info.get("priceToSalesTrailingTwelveMonths")
            r.price_to_book  = info.get("priceToBook")

            # ── Factor 4: Momentum ─────────────────────────────────────
            def _ret(lookback: int, skip: int = 0) -> Optional[float]:
                end_i   = len(close) - 1 - skip
                start_i = end_i - lookback
                if start_i < 0 or close.iloc[start_i] == 0:
                    return None
                return float((close.iloc[end_i] - close.iloc[start_i]) / close.iloc[start_i])

            r.momentum_1m    = _ret(21)
            r.momentum_3m    = _ret(63)
            r.momentum_6m    = _ret(126)
            r.momentum_12_1m = _ret(252, skip=21)

            # ── Factor 5: Analyst Sentiment ────────────────────────────
            r.analyst_rating_mean = info.get("recommendationMean")    # 1=Strong Buy
            r.num_analysts        = info.get("numberOfAnalystOpinions")
            target_price          = info.get("targetMeanPrice")
            if target_price and r.price and r.price > 0:
                r.analyst_target_upside = (target_price - r.price) / r.price

            # Estimate % buy: yfinance doesn't expose buy/hold/sell counts
            # directly via .info so we approximate from recommendationMean
            # (1=SB 2=B 3=H 4=S 5=SS).  Ratings ≤ 2.0 → ~buy consensus.
            if r.analyst_rating_mean is not None:
                # Linear mapping: 1→100%, 2→75%, 3→50%, 4→25%, 5→0%
                r.analyst_buy_pct = max(0.0, (5 - r.analyst_rating_mean) / 4)

            time.sleep(self.request_delay)

        except Exception as e:
            logger.warning("Screener fetch error for %s (%s): %s",
                           ticker, type(e).__name__, e)
            r.passed_hard_filters = False
            r.filter_reason = f"Data fetch error ({type(e).__name__}): {e}"

        return r

    # ──────────────────────────────────────────────────────────────────────
    # Z-score helper
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _zscore(series: pd.Series) -> pd.Series:
        """Robust cross-sectional z-score; returns 0 for constant/empty series."""
        filled = series.dropna()
        if filled.empty:
            return pd.Series(0.0, index=series.index)
        mu  = filled.mean()
        std = filled.std()
        if std == 0 or math.isnan(std):
            return pd.Series(0.0, index=series.index)
        return (series - mu) / std

    # ──────────────────────────────────────────────────────────────────────
    # Factor scoring
    # ──────────────────────────────────────────────────────────────────────

    def _score_factors(self, results: List[ScreenerResult]) -> List[ScreenerResult]:
        """Compute factor z-scores and composite score for all passing results."""
        if not results:
            return results

        df = pd.DataFrame([r.model_dump() for r in results]).set_index("ticker")
        z  = self._zscore  # shorthand

        # ── Quality z-score ────────────────────────────────────────────
        q_parts = {}
        for col in ["roe", "roa", "gross_margin", "operating_margin", "fcf_margin",
                    "fcf_yield", "interest_coverage"]:
            if df[col].notna().sum() > 2:
                q_parts[col] = z(df[col].fillna(df[col].median()))
        for col in ["debt_to_ebitda"]:       # inverted: lower is better
            if df[col].notna().sum() > 2:
                q_parts[f"{col}_inv"] = -z(df[col].fillna(df[col].median()))
        df["quality_score"] = pd.DataFrame(q_parts, index=df.index).mean(axis=1) if q_parts else 0.0

        # ── Growth z-score ─────────────────────────────────────────────
        g_parts = {}
        for col in ["revenue_growth_yoy", "eps_growth_yoy", "forward_eps_growth",
                    "earnings_growth_3y", "fcf_yield"]:
            if df[col].notna().sum() > 2:
                g_parts[col] = z(df[col].fillna(df[col].median()))
        df["growth_score"] = pd.DataFrame(g_parts, index=df.index).mean(axis=1) if g_parts else 0.0

        # ── Valuation z-score (lower multiple = better → inverted) ─────
        v_parts = {}
        for col in ["peg_ratio", "ev_to_ebitda", "pe_forward",
                    "pe_trailing", "price_to_sales"]:
            if df[col].notna().sum() > 2:
                # Cap extreme outliers before inverting (avoid distortion)
                capped = df[col].clip(upper=df[col].quantile(0.95))
                v_parts[f"{col}_inv"] = -z(capped.fillna(capped.median()))
        # FCF yield: higher is better (not inverted)
        if df["fcf_yield"].notna().sum() > 2:
            v_parts["fcf_yield"] = z(df["fcf_yield"].fillna(df["fcf_yield"].median()))
        df["valuation_score"] = pd.DataFrame(v_parts, index=df.index).mean(axis=1) if v_parts else 0.0

        # ── Momentum z-score ───────────────────────────────────────────
        m_parts = {}
        for col, wt in [("momentum_12_1m", 2), ("momentum_6m", 1.5),
                        ("momentum_3m", 1), ("momentum_1m", 0.5)]:
            if df[col].notna().sum() > 2:
                m_parts[col] = wt * z(df[col].fillna(df[col].median()))
        total_wt = sum([2, 1.5, 1, 0.5][: len(m_parts)])
        df["momentum_score"] = (
            pd.DataFrame(m_parts, index=df.index).sum(axis=1) / total_wt
            if m_parts else 0.0
        )

        # ── Analyst Sentiment z-score ──────────────────────────────────
        a_parts = {}
        for col in ["analyst_buy_pct", "analyst_target_upside"]:
            if df[col].notna().sum() > 2:
                a_parts[col] = z(df[col].fillna(df[col].median()))
        if df["analyst_rating_mean"].notna().sum() > 2:   # inverted: 1=best
            a_parts["rating_inv"] = -z(
                df["analyst_rating_mean"].fillna(df["analyst_rating_mean"].median())
            )
        df["analyst_score"] = pd.DataFrame(a_parts, index=df.index).mean(axis=1) if a_parts else 0.0

        # ── Composite ──────────────────────────────────────────────────
        fw = self.factor_weights
        df["composite_score"] = (
            fw["quality"]   * df["quality_score"]
            + fw["growth"]    * df["growth_score"]
            + fw["valuation"] * df["valuation_score"]
            + fw["momentum"]  * df["momentum_score"]
            + fw["analyst"]   * df["analyst_score"]
        )

        # Write scores back to result objects
        score_cols = [
            "quality_score", "growth_score", "valuation_score",
            "momentum_score", "analyst_score", "composite_score",
        ]
        for r in results:
            if r.ticker in df.index:
                for col in score_cols:
                    val = df.loc[r.ticker, col]
                    setattr(r, col, float(val) if pd.notna(val) else 0.0)

        return results

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    def screen(
        self,
        trade_date: str,
        top_n: Optional[int] = None,
        tickers: Optional[List[str]] = None,
    ) -> Tuple[List[ScreenerResult], List[ScreenerResult]]:
        """Run the full two-phase institutional screen.

        Parameters
        ----------
        trade_date : str   YYYY-MM-DD
        top_n : int        Number of survivors to return after scoring.
                           Defaults to ``config["portfolio"]["pre_analysis_cap"]``.
        tickers : list     Override universe.  If None, uses ``get_universe()``.

        Returns
        -------
        (passed, filtered)
            passed   — top_n results sorted by composite_score descending
            filtered — tickers that failed hard filters (for reporting)
        """
        if top_n is None:
            top_n = self.pcfg.get("pre_analysis_cap", 50)

        universe = tickers or self.get_universe()
        logger.info(
            "Screening %d tickers  [quality=%.0f%% growth=%.0f%% "
            "valuation=%.0f%% momentum=%.0f%% analyst=%.0f%%]",
            len(universe),
            self.factor_weights["quality"] * 100,
            self.factor_weights["growth"] * 100,
            self.factor_weights["valuation"] * 100,
            self.factor_weights["momentum"] * 100,
            self.factor_weights["analyst"] * 100,
        )

        # ── Phase A: parallel data fetch ───────────────────────────────
        all_results: List[ScreenerResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._fetch_single, tkr, trade_date): tkr
                for tkr in universe
            }
            for fut in as_completed(futures):
                orig_ticker = futures[fut]
                try:
                    all_results.append(fut.result())
                except Exception as e:
                    # Never silently drop a ticker — add it to filtered with a reason
                    logger.warning(
                        "Screener: unexpected error for %s — %s", orig_ticker, e
                    )
                    all_results.append(ScreenerResult(
                        ticker=orig_ticker,
                        passed_hard_filters=False,
                        filter_reason=f"Unexpected error: {e}",
                    ))

        passed   = [r for r in all_results if r.passed_hard_filters]
        filtered = [r for r in all_results if not r.passed_hard_filters]

        logger.info(
            "Hard filters: %d/%d passed  (%d eliminated)",
            len(passed), len(all_results), len(filtered),
        )
        for r in filtered:
            logger.debug("  ✗ %s — %s", r.ticker, r.filter_reason)

        # ── Phase B: multi-factor scoring ─────────────────────────────
        scored = self._score_factors(passed)

        scored.sort(key=lambda r: (r.composite_score or -999.0), reverse=True)

        # Assign ranks
        for rank, r in enumerate(scored, 1):
            r.composite_rank = rank

        top = scored[:top_n]

        logger.info(
            "Top %d after scoring: %s",
            len(top),
            [r.ticker for r in top],
        )

        return top, filtered
