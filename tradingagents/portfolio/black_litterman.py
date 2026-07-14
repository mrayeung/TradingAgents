"""
Black-Litterman posterior expected return computation.

Given:
  - prices_df:     historical daily closes (columns = tickers)
  - signal_rows:   SignalRow objects — analyst views (expected_return + conviction)
  - risk_aversion: market risk-aversion coefficient δ (typically 1.5–3.0)
  - tau:           uncertainty scaling on the prior covariance (default 0.05)

Returns:
  - dict[ticker, float]  — posterior expected annualised excess returns
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.portfolio.signals import SignalRow


def compute_bl_returns(
    tickers: list[str],
    prices_df: pd.DataFrame,
    signal_rows: list[SignalRow],
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> dict[str, float]:
    """Compute Black-Litterman posterior expected returns.

    Parameters
    ----------
    tickers:       Ordered list of ticker symbols to optimise over.
    prices_df:     Daily close prices, columns = tickers, index = dates.
    signal_rows:   Output of aggregate_signals(); each row contributes one view.
    risk_aversion: Market risk aversion coefficient δ (default 2.5).
    tau:           Uncertainty scaling on the prior Σ (default 0.05).

    Returns
    -------
    dict mapping ticker → posterior expected annualised return (e.g. 0.18).
    """
    n = len(tickers)
    if n == 0:
        return {}

    # ── 1. Covariance matrix from historical daily returns ────────────────────
    available = [t for t in tickers if t in prices_df.columns]
    if len(available) >= 2:
        rets = prices_df[available].pct_change().dropna()
        sigma_sub = rets.cov().values * 252          # annualise
        # Expand to full n×n; non-available tickers get diagonal variance 0.04
        sigma = np.eye(n) * 0.04
        for i, ti in enumerate(tickers):
            for j, tj in enumerate(tickers):
                if ti in available and tj in available:
                    ai, aj = available.index(ti), available.index(tj)
                    sigma[i, j] = sigma_sub[ai, aj]
    else:
        sigma = np.eye(n) * 0.04

    # ── 2. Market-implied equilibrium returns (equal-weight prior) ────────────
    w_mkt = np.full(n, 1.0 / n)
    pi = risk_aversion * sigma @ w_mkt

    # ── 3. Build views matrix P and view vector Q ─────────────────────────────
    signal_map: dict[str, SignalRow] = {r.ticker: r for r in signal_rows}
    view_indices = [i for i, t in enumerate(tickers) if t in signal_map]

    if not view_indices:
        # No analyst coverage — return the equilibrium prior
        return {t: round(float(pi[i]), 4) for i, t in enumerate(tickers)}

    k = len(view_indices)
    P = np.zeros((k, n))
    Q = np.zeros(k)
    Omega_diag = np.zeros(k)

    for row_idx, col_idx in enumerate(view_indices):
        t = tickers[col_idx]
        sig = signal_map[t]
        P[row_idx, col_idx] = 1.0
        Q[row_idx] = sig.expected_return
        # View uncertainty: lower conviction → wider Omega
        uncertainty = (1.0 - sig.conviction) * 0.10 + 0.01
        Omega_diag[row_idx] = uncertainty ** 2

    Omega = np.diag(Omega_diag)

    # ── 4. BL posterior ────────────────────────────────────────────────────────
    # μ_BL = [(τΣ)⁻¹ + Pᵀ Ω⁻¹ P]⁻¹ [(τΣ)⁻¹ π + Pᵀ Ω⁻¹ Q]
    tau_sigma = tau * sigma

    def _safe_inv(M: np.ndarray) -> np.ndarray:
        try:
            return np.linalg.inv(M)
        except np.linalg.LinAlgError:
            return np.linalg.pinv(M)

    tau_sigma_inv = _safe_inv(tau_sigma)
    omega_inv = _safe_inv(Omega)

    A = tau_sigma_inv + P.T @ omega_inv @ P
    b = tau_sigma_inv @ pi + P.T @ omega_inv @ Q

    try:
        mu_bl = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        mu_bl = np.linalg.lstsq(A, b, rcond=None)[0]

    return {t: round(float(mu_bl[i]), 4) for i, t in enumerate(tickers)}
