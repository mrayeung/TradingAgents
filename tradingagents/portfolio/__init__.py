"""Portfolio Construction module for TradingAgents."""

from tradingagents.portfolio.signals import SignalRow, aggregate_signals
from tradingagents.portfolio.black_litterman import compute_bl_returns
from tradingagents.portfolio.optimizer import optimize_portfolio
from tradingagents.portfolio.correlation import compute_correlation_matrix
from tradingagents.portfolio.sizing import compute_kelly_sizes
from tradingagents.portfolio.benchmark import compute_benchmark_comparison

__all__ = [
    "SignalRow",
    "aggregate_signals",
    "compute_bl_returns",
    "optimize_portfolio",
    "compute_correlation_matrix",
    "compute_kelly_sizes",
    "compute_benchmark_comparison",
]
