"""Markov 2.0 regime analysis for TradingAgents.

A faithful Python port of the TradingView Pine v5 "Markov 2.0 — Regime
(corrected)" indicator. Exposes a deterministic regime/signal that can feed the
agent debate (as a Regime Analyst input) or gate portfolio weights.

Research tooling only — not investment advice.
"""

from .markov2 import (
    BEAR,
    SIDE,
    BULL,
    STATE_NAMES,
    MarkovConfig,
    MarkovResult,
    analyze,
    walk_forward,
)

__all__ = [
    "BEAR",
    "SIDE",
    "BULL",
    "STATE_NAMES",
    "MarkovConfig",
    "MarkovResult",
    "analyze",
    "walk_forward",
]
