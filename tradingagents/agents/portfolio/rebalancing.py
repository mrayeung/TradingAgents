"""Rebalancing Agent.

Compares a current holdings snapshot to the target PortfolioView and
produces a RebalanceRecommendation with concrete trade actions.

Supports two rebalance modes
-----------------------------
monthly_scheduled
    Full portfolio diff regardless of drift.  Run on the configured
    ``rebalance_day`` of each month (or any time the caller specifies
    ``rebalance_type="monthly_scheduled"``).

drift_triggered
    Only flag positions whose *relative* drift exceeds ``drift_threshold``:
        |current_weight − target_weight| / target_weight  > threshold
    New positions (in target but not in current) and exits (in current but
    not in target) are always included regardless of the drift threshold.

The LLM is used solely for generating per-trade rationale and the
executive summary; all quantitative decisions (which trades, size of
delta) are computed deterministically.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from tradingagents.agents.portfolio.schemas import (
    PortfolioView,
    RebalanceAction,
    RebalanceRecommendation,
    RebalanceTrade,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _priority(drift_pct: float, action: RebalanceAction) -> str:
    """Assign a qualitative priority based on drift magnitude and action type."""
    if action in (RebalanceAction.SELL, RebalanceAction.BUY) and drift_pct > 1.0:
        # New / exited positions — always high priority
        return "High"
    if drift_pct >= 0.50:
        return "High"
    if drift_pct >= 0.25:
        return "Medium"
    return "Low"


def _compute_trades(
    target_holdings: Dict[str, float],
    current_holdings: Dict[str, float],
    drift_threshold: float,
    rebalance_type: str,
) -> List[RebalanceTrade]:
    """Compute deterministic rebalance trades.

    Parameters
    ----------
    target_holdings : dict[ticker → target_weight]
    current_holdings : dict[ticker → current_weight]
    drift_threshold : float
        Relative drift threshold for drift_triggered mode (e.g. 0.25 = 25%).
    rebalance_type : str
        "monthly_scheduled" | "drift_triggered"

    Returns
    -------
    List[RebalanceTrade]  sorted by |weight_delta| descending
    """
    all_tickers = set(target_holdings) | set(current_holdings)
    trades: List[RebalanceTrade] = []

    for ticker in all_tickers:
        current_w = current_holdings.get(ticker, 0.0)
        target_w = target_holdings.get(ticker, 0.0)
        delta = round(target_w - current_w, 6)

        # Drift relative to target (avoid divide-by-zero when target is 0)
        if target_w > 0:
            drift_pct = abs(current_w - target_w) / target_w
        else:
            drift_pct = float("inf") if current_w > 0 else 0.0

        # Determine action
        if target_w == 0 and current_w > 0:
            action = RebalanceAction.SELL
        elif current_w == 0 and target_w > 0:
            action = RebalanceAction.BUY
        elif delta > 0.001:
            action = RebalanceAction.BUY
        elif delta < -0.001:
            action = RebalanceAction.TRIM
        else:
            action = RebalanceAction.HOLD

        # For drift_triggered mode, skip trades within tolerance
        if rebalance_type == "drift_triggered":
            if action == RebalanceAction.HOLD:
                continue
            # New/exit positions are always included
            if action not in (RebalanceAction.BUY, RebalanceAction.SELL):
                if drift_pct < drift_threshold:
                    action = RebalanceAction.HOLD
                    continue

        trades.append(
            RebalanceTrade(
                ticker=ticker,
                action=action,
                current_weight=round(current_w, 6),
                target_weight=round(target_w, 6),
                weight_delta=round(delta, 6),
                drift_pct=round(drift_pct, 4) if drift_pct != float("inf") else 9.99,
                priority=_priority(drift_pct, action),
                rationale="",  # filled by LLM below
            )
        )

    # Sort by |delta| descending so the biggest moves come first
    trades.sort(key=lambda t: abs(t.weight_delta), reverse=True)
    return trades


def _build_rationale_prompt(
    trades: List[RebalanceTrade],
    portfolio_view: PortfolioView,
    rebalance_type: str,
) -> str:
    """Build a compact prompt asking the LLM to add rationale to each trade."""
    lines = [
        "You are a portfolio manager writing a rebalancing memo.",
        "For each trade below, provide a 1-2 sentence rationale explaining WHY "
        "this change is being made, grounded in the portfolio thesis.",
        "",
        f"Portfolio methodology: {portfolio_view.methodology}",
        f"Construction rationale: {portfolio_view.construction_rationale}",
        "",
        "## Trades requiring rationale",
        "",
    ]
    for t in trades:
        if t.action == RebalanceAction.HOLD:
            continue
        delta_str = f"{t.weight_delta:+.1%}"
        lines.append(
            f"- {t.ticker}: {t.action.value} (current {t.current_weight:.1%} → "
            f"target {t.target_weight:.1%}, delta {delta_str}, drift {t.drift_pct:.0%})"
        )

    # Map ticker to thesis from holdings
    thesis_map = {h.ticker: h.investment_thesis for h in portfolio_view.holdings}

    lines += [
        "",
        "## Per-ticker thesis context",
        "",
    ]
    for t in trades:
        if t.action == RebalanceAction.HOLD:
            continue
        thesis = thesis_map.get(t.ticker, "")
        if thesis:
            lines.append(f"- {t.ticker}: {thesis[:200]}")

    lines += [
        "",
        "## Output format",
        "Return JSON like:",
        '[{"ticker": "AAPL", "rationale": "Adding to AAPL as..."}]',
        "",
        "Then on a new line:",
        "SUMMARY: <3-5 sentence executive summary of the full rebalance>",
        "MACRO_CONTEXT: <1-2 sentences on the market backdrop driving changes>",
    ]
    return "\n".join(lines)


def _parse_rationale_response(
    response_text: str,
    trades: List[RebalanceTrade],
) -> tuple[List[RebalanceTrade], str, str]:
    """Parse LLM rationale JSON and summary sections, filling in trade rationale."""
    import json
    import re

    # Try to parse JSON array
    json_match = re.search(r"(\[\s*\{.*?\}\s*\])", response_text, re.DOTALL)
    rationale_map: Dict[str, str] = {}
    if json_match:
        try:
            items = json.loads(json_match.group(1))
            for item in items:
                if "ticker" in item and "rationale" in item:
                    rationale_map[item["ticker"]] = item["rationale"]
        except (json.JSONDecodeError, KeyError):
            pass

    # Fill rationale into trade objects
    for trade in trades:
        if trade.ticker in rationale_map:
            trade = trade.model_copy(update={"rationale": rationale_map[trade.ticker]})
        elif trade.action != RebalanceAction.HOLD and not trade.rationale:
            trade = trade.model_copy(
                update={"rationale": f"{trade.action.value} {trade.ticker} per target allocation."}
            )

    # Extract summary + macro context
    summary_match = re.search(r"SUMMARY:\s*(.+?)(?=MACRO_CONTEXT:|$)", response_text, re.DOTALL | re.IGNORECASE)
    macro_match = re.search(r"MACRO_CONTEXT:\s*(.+?)$", response_text, re.DOTALL | re.IGNORECASE)

    summary = summary_match.group(1).strip() if summary_match else (
        f"Rebalancing {len([t for t in trades if t.action != RebalanceAction.HOLD])} positions "
        f"to align with updated target portfolio."
    )
    macro = macro_match.group(1).strip() if macro_match else ""

    return trades, summary, macro


def create_rebalancing_agent(llm):
    """Return a callable rebalancing function bound to ``llm``.

    Parameters
    ----------
    llm : LangChain LLM instance

    Returns
    -------
    callable
        ``generate_rebalance(portfolio_view, current_holdings, trade_date,
                              rebalance_type, drift_threshold)``
        → ``RebalanceRecommendation``
    """

    def generate_rebalance(
        portfolio_view: PortfolioView,
        current_holdings: Dict[str, float],
        trade_date: str,
        rebalance_type: str = "monthly_scheduled",
        drift_threshold: Optional[float] = None,
    ) -> RebalanceRecommendation:
        """Generate a rebalance recommendation.

        Parameters
        ----------
        portfolio_view : PortfolioView
            The freshly constructed target portfolio.
        current_holdings : dict[ticker → weight]
            Current portfolio weights as decimals.  Pass an empty dict for an
            initial portfolio construction (all positions are new buys).
        trade_date : str
            ISO date string (YYYY-MM-DD).
        rebalance_type : str
            "monthly_scheduled" or "drift_triggered".
        drift_threshold : float, optional
            Relative drift threshold for drift_triggered mode.  Defaults to 0.25.

        Returns
        -------
        RebalanceRecommendation
        """
        if drift_threshold is None:
            drift_threshold = 0.25

        # Build target weight dict from PortfolioView
        target_holdings = {h.ticker: h.target_weight for h in portfolio_view.holdings}

        # Compute trades
        trades = _compute_trades(
            target_holdings, current_holdings, drift_threshold, rebalance_type
        )

        active_trades = [t for t in trades if t.action != RebalanceAction.HOLD]

        new_positions = [
            t.ticker for t in active_trades
            if t.action == RebalanceAction.BUY and current_holdings.get(t.ticker, 0.0) == 0.0
        ]
        exited_positions = [
            t.ticker for t in active_trades if t.action == RebalanceAction.SELL
        ]

        # Estimated one-way turnover = sum(|delta|) / 2
        turnover = sum(abs(t.weight_delta) for t in active_trades) / 2.0

        # LLM rationale
        if active_trades:
            prompt = _build_rationale_prompt(active_trades, portfolio_view, rebalance_type)
            try:
                response = llm.invoke(prompt)
                response_text = (
                    response.content if hasattr(response, "content") else str(response)
                )
                trades, summary, macro = _parse_rationale_response(response_text, trades)
            except Exception as e:
                logger.warning("LLM rationale call failed: %s", e)
                summary = (
                    f"Rebalancing {len(active_trades)} positions to align with "
                    f"updated {portfolio_view.methodology} target portfolio."
                )
                macro = ""
        else:
            summary = "No rebalance trades required — portfolio is within drift tolerance."
            macro = ""

        return RebalanceRecommendation(
            trade_date=trade_date,
            rebalance_type=rebalance_type,
            trades=trades,
            new_positions=new_positions,
            exited_positions=exited_positions,
            portfolio_turnover_pct=round(turnover, 4),
            summary=summary,
            macro_context=macro,
        )

    return generate_rebalance
