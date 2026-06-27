"""
Correlation matrix from recent price history (yfinance).
Identifies high-correlation pairs that may warrant position sizing penalties.
"""
from __future__ import annotations

import pandas as pd


def _fetch_prices(tickers: list[str], days: int) -> pd.DataFrame:
    """Download adjusted close prices for all tickers in one yfinance call."""
    import yfinance as yf

    period = f"{days}d"
    raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)

    if raw.empty:
        return pd.DataFrame(columns=tickers)

    # yfinance returns MultiIndex columns when multiple tickers are requested
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            prices = raw["Close"]
        else:
            # Flatten — take the first available metric level
            prices = raw.iloc[:, : len(tickers)]
            prices.columns = tickers[: prices.shape[1]]
    else:
        # Single ticker
        prices = raw[["Close"]] if "Close" in raw.columns else raw
        if len(tickers) == 1:
            prices.columns = [tickers[0]]

    return prices.dropna(how="all")


def compute_correlation_matrix(
    tickers: list[str],
    days: int = 90,
    high_corr_threshold: float = 0.70,
) -> dict:
    """Compute the pairwise return-correlation matrix.

    Parameters
    ----------
    tickers:              Ticker symbols.
    days:                 Look-back window in trading days.
    high_corr_threshold:  |r| above which a pair is flagged as high-correlation.

    Returns
    -------
    dict with:
      tickers:    list[str]          — available subset (some may be excluded if no data)
      matrix:     list[list[float]]  — correlation matrix rows
      high_pairs: list[{a, b, r}]   — pairs exceeding the threshold, sorted desc by |r|
    """
    if not tickers:
        return {"tickers": [], "matrix": [], "high_pairs": []}

    prices = _fetch_prices(tickers, days)

    available = [t for t in tickers if t in prices.columns]
    if len(available) < 2:
        # Return identity-like result
        n = len(available)
        return {
            "tickers": available,
            "matrix": [[1.0] * n for _ in range(n)] if n else [],
            "high_pairs": [],
        }

    returns = prices[available].pct_change().dropna()
    corr = returns.corr()

    matrix = [[round(float(corr.iloc[i, j]), 4) for j in range(len(available))]
              for i in range(len(available))]

    high_pairs = []
    for i in range(len(available)):
        for j in range(i + 1, len(available)):
            r = float(corr.iloc[i, j])
            if abs(r) >= high_corr_threshold:
                high_pairs.append({
                    "a": available[i],
                    "b": available[j],
                    "r": round(r, 3),
                })
    high_pairs.sort(key=lambda x: -abs(x["r"]))

    return {
        "tickers": available,
        "matrix": matrix,
        "high_pairs": high_pairs,
    }
