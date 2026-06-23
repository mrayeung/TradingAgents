"""Pairwise return correlation matrix for a list of tickers.

Uses yfinance to fetch adjusted close prices, computes daily log returns,
and returns a plain-dict payload that the dashboard can embed as JSON.

Usage:
    from tradingagents.portfolio.correlation import compute_correlation_matrix
    data = compute_correlation_matrix(["AAPL", "MSFT", "NVDA"], "2026-05-05")
    # data = {"tickers": [...], "matrix": [[...], ...], "lookback_days": 252}
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def compute_correlation_matrix(
    tickers:      List[str],
    trade_date:   str,
    lookback_days: int = 252,      # ~1 trading year
) -> Optional[dict]:
    """Fetch daily close prices and return a correlation-matrix payload.

    Parameters
    ----------
    tickers : list[str]
        Portfolio tickers (order is preserved in the output matrix).
    trade_date : str
        YYYY-MM-DD — end date for the price window (no look-ahead).
    lookback_days : int
        Calendar days to look back.  252 ≈ 1 trading year.

    Returns
    -------
    dict with keys:
        tickers      : list[str]  — tickers that had sufficient data
        matrix       : list[list[float | None]]  — NxN Pearson correlations
        lookback_days: int
        start_date   : str        — actual start of price window
        end_date     : str
    or None if fewer than 2 tickers had usable price data.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — correlation matrix unavailable")
        return None

    if not tickers or len(tickers) < 2:
        return None

    end_dt   = datetime.strptime(trade_date, "%Y-%m-%d")
    # Add extra calendar days to ensure we get ~lookback_days of trading days
    start_dt = end_dt - timedelta(days=int(lookback_days * 1.45))

    start_str = start_dt.strftime("%Y-%m-%d")
    end_str   = end_dt.strftime("%Y-%m-%d")

    logger.info("Fetching %d-day price history for %d tickers …", lookback_days, len(tickers))

    try:
        # Batch download — much faster than one-by-one
        raw = yf.download(
            tickers,
            start=start_str,
            end=end_str,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.warning("yfinance batch download failed: %s", e)
        return None

    # Extract Close prices — shape depends on whether multi-ticker or single
    if isinstance(raw.columns, type(raw.columns)) and hasattr(raw.columns, "levels"):
        # MultiIndex: (field, ticker)
        try:
            closes = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw["Adj Close"]
        except Exception:
            closes = raw.xs("Close", axis=1, level=0) if "Close" in raw.columns.get_level_values(0) else None
    else:
        # Single ticker — columns are plain field names
        col = "Close" if "Close" in raw.columns else "Adj Close"
        closes = raw[[col]].rename(columns={col: tickers[0]}) if col in raw.columns else None

    if closes is None or closes.empty:
        logger.warning("No price data returned from yfinance")
        return None

    # Keep only tickers that have enough non-null data (at least 60 trading days)
    min_obs = 60
    good_cols = [c for c in tickers if c in closes.columns
                 and closes[c].dropna().shape[0] >= min_obs]
    if len(good_cols) < 2:
        logger.warning("Fewer than 2 tickers have sufficient price history")
        return None

    closes = closes[good_cols].dropna(how="all")

    # Daily log returns; drop rows where ALL are NaN
    returns = np.log(closes / closes.shift(1)).dropna(how="all")

    # Pearson correlation matrix — use pairwise complete obs (min_periods)
    corr_df = returns.corr(method="pearson", min_periods=30)

    # Build output — round to 4dp, replace NaN with None
    n = len(good_cols)
    matrix: list[list] = []
    for i in range(n):
        row = []
        for j in range(n):
            val = corr_df.iloc[i, j]
            row.append(None if val != val else round(float(val), 4))   # NaN → None
        matrix.append(row)

    return {
        "tickers":       good_cols,
        "matrix":        matrix,
        "lookback_days": lookback_days,
        "start_date":    str(returns.index[0].date()),
        "end_date":      str(returns.index[-1].date()),
        "n_obs":         len(returns),
    }
