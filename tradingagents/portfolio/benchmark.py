"""
Benchmark comparison: weighted portfolio performance vs SPY, QQQ, DIA.

Pulls historical prices via yfinance. All series rebased to 1.0 at start date.
"""
from __future__ import annotations

import pandas as pd

BENCHMARKS = ["SPY", "QQQ", "DIA"]


def _rebase(series: pd.Series) -> list[float]:
    """Rebase a price series to 1.0 at the first non-null value."""
    s = series.dropna()
    if s.empty:
        return []
    return [round(float(v / s.iloc[0]), 6) for v in s]


def _total_return(series: pd.Series) -> float:
    s = series.dropna()
    if len(s) < 2:
        return 0.0
    return float((s.iloc[-1] / s.iloc[0]) - 1.0)


def compute_benchmark_comparison(
    tickers: list[str],
    weights: dict[str, float],
    days: int = 90,
) -> dict:
    """Time-series comparison of a weighted portfolio vs SPY / QQQ / DIA.

    Parameters
    ----------
    tickers:  Constituent symbols.
    weights:  Portfolio weights (must sum to ~1.0).
    days:     Look-back window in trading days (default 90).

    Returns
    -------
    dict with:
      dates:             list[str] YYYY-MM-DD
      portfolio_values:  rebased cumulative performance (start = 1.0)
      spy_values:        rebased SPY
      qqq_values:        rebased QQQ
      dia_values:        rebased DIA
      summary: {portfolio_return, spy_return, qqq_return, dia_return,
                portfolio_volatility, sharpe_vs_spy}
    """
    import yfinance as yf

    all_symbols = list(dict.fromkeys(tickers + BENCHMARKS))   # preserve order, dedupe
    period = f"{days}d"

    raw = yf.download(all_symbols, period=period, auto_adjust=True, progress=False)
    if raw.empty:
        return _empty_result()

    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
    else:
        prices = raw

    prices = prices.dropna(how="all")
    if prices.empty:
        return _empty_result()

    # ── Portfolio daily returns ───────────────────────────────────────────────
    available = [t for t in tickers if t in prices.columns]
    if available:
        daily_port = (
            prices[available]
            .pct_change()
            .fillna(0.0)
            .apply(
                lambda row: sum(weights.get(t, 0.0) * row[t] for t in available),
                axis=1,
            )
        )
    else:
        daily_port = pd.Series(0.0, index=prices.index)

    port_cum = (1.0 + daily_port).cumprod()
    dates = [d.strftime("%Y-%m-%d") for d in prices.index]

    spy_s = prices["SPY"] if "SPY" in prices.columns else pd.Series(dtype=float)
    qqq_s = prices["QQQ"] if "QQQ" in prices.columns else pd.Series(dtype=float)
    dia_s = prices["DIA"] if "DIA" in prices.columns else pd.Series(dtype=float)

    port_ret = float(port_cum.iloc[-1] - 1.0) if not port_cum.empty else 0.0
    port_vol = float(daily_port.std() * (252 ** 0.5))
    spy_ret = _total_return(spy_s)
    sharpe = (port_ret - spy_ret) / port_vol if port_vol > 1e-9 else 0.0

    # Align benchmark values to the same index as prices
    def _aligned_rebase(s: pd.Series) -> list[float]:
        aligned = s.reindex(prices.index)
        return _rebase(aligned)

    return {
        "dates": dates,
        "portfolio_values": [round(float(v), 6) for v in port_cum.tolist()],
        "spy_values":       _aligned_rebase(spy_s),
        "qqq_values":       _aligned_rebase(qqq_s),
        "dia_values":       _aligned_rebase(dia_s),
        "summary": {
            "portfolio_return":    round(port_ret, 4),
            "spy_return":          round(spy_ret, 4),
            "qqq_return":          round(_total_return(qqq_s), 4),
            "dia_return":          round(_total_return(dia_s), 4),
            "portfolio_volatility": round(port_vol, 4),
            "sharpe_vs_spy":       round(sharpe, 3),
        },
    }


def _empty_result() -> dict:
    return {
        "dates": [],
        "portfolio_values": [],
        "spy_values": [],
        "qqq_values": [],
        "dia_values": [],
        "summary": {
            "portfolio_return": 0.0, "spy_return": 0.0,
            "qqq_return": 0.0,       "dia_return": 0.0,
            "portfolio_volatility": 0.0, "sharpe_vs_spy": 0.0,
        },
    }
