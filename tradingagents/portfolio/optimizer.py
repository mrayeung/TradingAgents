"""
Mean-variance portfolio optimiser using scipy constrained optimisation.

Objective: minimise  w' Σ w - (1/δ) μ' w
Subject to:
  • Σ wᵢ = 1          (fully invested)
  • min_position ≤ wᵢ ≤ max_position  (concentration limits)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def _build_covariance(tickers: list[str], prices_df: pd.DataFrame) -> np.ndarray:
    """Annualised covariance matrix from daily price history."""
    available = [t for t in tickers if t in prices_df.columns]
    n = len(tickers)
    sigma = np.eye(n) * 0.04   # fallback: 20% vol, uncorrelated

    if len(available) >= 2:
        rets = prices_df[available].pct_change().dropna()
        if len(rets) >= 20:
            sub = rets.cov().values * 252
            for i, ti in enumerate(tickers):
                for j, tj in enumerate(tickers):
                    if ti in available and tj in available:
                        ai, aj = available.index(ti), available.index(tj)
                        sigma[i, j] = sub[ai, aj]
    return sigma


def optimize_portfolio(
    tickers: list[str],
    prices_df: pd.DataFrame,
    bl_returns: dict[str, float],
    risk_aversion: float = 2.5,
    max_position: float = 0.40,
    min_position: float = 0.02,
) -> dict:
    """Run constrained mean-variance optimisation.

    Parameters
    ----------
    tickers:       Symbols to include in the portfolio.
    prices_df:     Daily close prices for covariance estimation.
    bl_returns:    Posterior expected returns from compute_bl_returns().
    risk_aversion: Risk aversion δ (higher → more conservative).
    max_position:  Maximum weight per ticker (default 40%).
    min_position:  Minimum weight per ticker (default 2%).

    Returns
    -------
    dict with:
      weights:         {ticker: weight}
      expected_return: annualised, portfolio-level
      volatility:      annualised standard deviation
      sharpe:          return / volatility (no risk-free rate subtracted)
    """
    n = len(tickers)
    if n == 0:
        return {"weights": {}, "expected_return": 0.0, "volatility": 0.0, "sharpe": 0.0}

    sigma = _build_covariance(tickers, prices_df)
    mu = np.array([bl_returns.get(t, 0.06) for t in tickers])

    def objective(w: np.ndarray) -> float:
        return float(w @ sigma @ w - (1.0 / risk_aversion) * mu @ w)

    def gradient(w: np.ndarray) -> np.ndarray:
        return 2.0 * sigma @ w - mu / risk_aversion

    w0 = np.full(n, 1.0 / n)
    bounds = [(min_position, max_position)] * n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]

    result = minimize(
        objective,
        w0,
        jac=gradient,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-10},
    )

    w = result.x if result.success else w0

    # Numeric clean-up: clip + renormalise
    w = np.clip(w, min_position, max_position)
    w /= w.sum()

    port_ret = float(mu @ w)
    port_vol = float(np.sqrt(w @ sigma @ w))
    sharpe = port_ret / port_vol if port_vol > 1e-9 else 0.0

    return {
        "weights": {t: round(float(w[i]), 4) for i, t in enumerate(tickers)},
        "expected_return": round(port_ret, 4),
        "volatility": round(port_vol, 4),
        "sharpe": round(sharpe, 3),
    }
