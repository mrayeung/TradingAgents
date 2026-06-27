"""Quantitative Analyst — Markov 2.0 regime/edge contributor.

A deterministic analyst node (no LLM, no tool loop, zero tokens). It runs first
in the graph, computes the Markov 2.0 regime analysis for the ticker, and writes
a standalone ``quantitative_report`` with an explicit, extractable recommendation.
The Trader and Portfolio Manager read this field directly, and the app renders it
as its own "Quantitative analyst" section.

Research tooling only — not investment advice.
"""

from __future__ import annotations

from tradingagents.agents.utils.regime_tools import compute_regime_report


def create_quantitative_analyst(llm=None):
    """Factory mirrors the other ``create_*_analyst`` helpers. ``llm`` is accepted
    for signature parity but unused — this analyst is purely quantitative."""

    def quantitative_analyst_node(state):
        symbol = state["company_of_interest"]
        current_date = state["trade_date"]
        report = compute_regime_report(symbol, current_date)
        return {"quantitative_report": report}

    return quantitative_analyst_node
