"""
Position sizing via Kelly Criterion with ½-Kelly scaling and correlation penalty.

Kelly formula:  f* = (b·p - q) / b
  p = analyst win probability
  q = 1 - p
  b = expected return on a win (expected_return from valuation verdict)

Applied as ½-Kelly for robustness, then penalised -20% per high-correlation peer
(capped at -60% total reduction).
"""
from __future__ import annotations

from tradingagents.portfolio.signals import SignalRow


def compute_kelly_sizes(
    signal_rows: list[SignalRow],
    weights: dict[str, float],
    correlation_result: dict,
    kelly_fraction: float = 0.5,
    corr_threshold: float = 0.70,
    corr_penalty: float = 0.20,
) -> list[dict]:
    """Compute Kelly-based position sizes with correlation adjustment.

    Parameters
    ----------
    signal_rows:         Output of aggregate_signals() — source of win_prob/expected_return.
    weights:             Optimised weights from optimize_portfolio().
    correlation_result:  Output of compute_correlation_matrix().
    kelly_fraction:      Fraction of full Kelly to use (default 0.5 = ½ Kelly).
    corr_threshold:      |r| above which penalty applies (default 0.70).
    corr_penalty:        Proportional penalty per high-corr peer (default 0.20).

    Returns
    -------
    list of dicts with: ticker, weight, kelly_f, half_kelly,
                        correlation_penalty, final_size
    Sorted descending by final_size.
    """
    signal_map: dict[str, SignalRow] = {r.ticker: r for r in signal_rows}
    high_pairs: list[dict] = correlation_result.get("high_pairs", [])

    positions: list[dict] = []
    for ticker, weight in weights.items():
        sig = signal_map.get(ticker)

        if sig is None:
            # No analyst coverage — use optimiser weight as-is, no Kelly override
            positions.append({
                "ticker": ticker,
                "weight": weight,
                "kelly_f": None,
                "half_kelly": None,
                "correlation_penalty": 0.0,
                "final_size": weight,
            })
            continue

        p = sig.win_prob
        q = 1.0 - p
        # b = expected gain per unit risked; floor at 1% to avoid division by zero
        b = max(sig.expected_return, 0.01)

        kelly_f = max((b * p - q) / b, 0.0)
        half_kelly = kelly_f * kelly_fraction

        # Count high-corr peers to determine penalty
        n_high_corr = sum(
            1
            for pair in high_pairs
            if (pair["a"] == ticker or pair["b"] == ticker)
            and abs(pair["r"]) >= corr_threshold
        )
        penalty = min(n_high_corr * corr_penalty, 0.60)   # cap at 60%
        final_size = half_kelly * (1.0 - penalty)

        positions.append({
            "ticker": ticker,
            "weight": weight,
            "kelly_f": round(kelly_f, 3),
            "half_kelly": round(half_kelly, 3),
            "correlation_penalty": round(penalty, 3),
            "final_size": round(max(final_size, 0.0), 4),
        })

    positions.sort(key=lambda x: -x["final_size"])
    return positions
