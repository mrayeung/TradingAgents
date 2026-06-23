"""Pydantic schemas for the Portfolio Construction Extension.

These models extend the core TradingAgents schemas to support:
- Momentum + Quality screening of a ticker universe
- Portfolio view with target allocations and OW/UW rationale
- Rebalancing recommendations (monthly scheduled + drift-triggered)

The position_sizing field from TraderProposal and the full PortfolioDecision
produced by the per-ticker pipeline feed directly into PortfolioHolding,
so each weight is grounded in the individual agent's own sizing guidance.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------


class ScreenerResult(BaseModel):
    """Institutional-grade multi-factor screen result for a single ticker.

    Factor groups mirror approaches used by Goldman Sachs, AQR, and systematic
    hedge funds: Quality, Growth, Valuation, Momentum, and Analyst Sentiment.
    Hard filters (market cap, liquidity, financial health) are applied first
    before any scoring, eliminating obvious failures cheaply.
    """

    ticker: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None      # $B
    avg_daily_volume: Optional[float] = None  # $M average daily dollar volume
    price: Optional[float] = None
    beta: Optional[float] = None

    # ── Hard-filter metadata ──────────────────────────────────────────────
    passed_hard_filters: bool = True
    filter_reason: Optional[str] = None     # Why a ticker was eliminated

    # ── Factor 1: Quality ─────────────────────────────────────────────────
    # (ROE, FCF margin, gross margin, interest coverage, debt/EBITDA)
    roe: Optional[float] = None                 # Return on equity (decimal)
    roa: Optional[float] = None                 # Return on assets (decimal)
    roic: Optional[float] = None                # Return on invested capital
    gross_margin: Optional[float] = None        # Gross profit margin
    operating_margin: Optional[float] = None    # Operating margin
    fcf_margin: Optional[float] = None          # Free cash flow / Revenue
    fcf_yield: Optional[float] = None           # FCF / Market Cap
    debt_to_ebitda: Optional[float] = None      # Net Debt / EBITDA
    interest_coverage: Optional[float] = None   # EBIT / Interest expense
    current_ratio: Optional[float] = None
    quality_score: Optional[float] = None       # Composite z-score

    # ── Factor 2: Growth ──────────────────────────────────────────────────
    # (Revenue growth, EPS growth, forward EPS growth, FCF growth proxy)
    revenue_growth_yoy: Optional[float] = None   # YoY revenue growth
    eps_growth_yoy: Optional[float] = None       # YoY EPS growth (trailing)
    forward_eps_growth: Optional[float] = None   # Forward vs trailing EPS
    earnings_growth_3y: Optional[float] = None   # 3-year avg earnings growth
    growth_score: Optional[float] = None

    # ── Factor 3: Valuation ───────────────────────────────────────────────
    # (PEG, EV/EBITDA, FCF yield, forward P/E — GARP approach)
    pe_trailing: Optional[float] = None
    pe_forward: Optional[float] = None
    peg_ratio: Optional[float] = None            # P/E ÷ growth (GARP key metric)
    ev_to_ebitda: Optional[float] = None
    price_to_sales: Optional[float] = None
    price_to_book: Optional[float] = None
    valuation_score: Optional[float] = None

    # ── Factor 4: Momentum ────────────────────────────────────────────────
    # (Cross-sectional price momentum across multiple windows)
    momentum_1m: Optional[float] = None
    momentum_3m: Optional[float] = None
    momentum_6m: Optional[float] = None
    momentum_12_1m: Optional[float] = None       # 12m ex last month (avoids reversal)
    momentum_score: Optional[float] = None

    # ── Factor 5: Analyst Sentiment ───────────────────────────────────────
    # (Consensus rating, target price upside, analyst coverage depth)
    analyst_rating_mean: Optional[float] = None  # 1=Strong Buy … 5=Strong Sell
    analyst_buy_pct: Optional[float] = None       # % analysts with Buy/Strong Buy
    analyst_target_upside: Optional[float] = None # (target − price) / price
    num_analysts: Optional[int] = None
    analyst_score: Optional[float] = None

    # ── Composite ─────────────────────────────────────────────────────────
    composite_score: Optional[float] = None
    composite_rank: Optional[int] = None         # 1 = highest composite score


# ---------------------------------------------------------------------------
# Portfolio Construction
# ---------------------------------------------------------------------------


class ConvictionLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class PortfolioHolding(BaseModel):
    """A single position in the target portfolio.

    target_weight is informed by:
    1. The per-ticker agent's own position_sizing suggestion (TraderProposal)
    2. The PortfolioDecision rating (Buy > Overweight > Hold)
    3. Momentum + Quality composite score from the screener
    4. Portfolio-level constraints (min/max weight, max positions)
    """

    ticker: str = Field(description="Stock ticker symbol")
    rating: str = Field(
        description="Agent rating: Buy / Overweight / Hold / Underweight / Sell"
    )
    target_weight: float = Field(
        description="Target portfolio weight as a decimal (0.08 = 8%)"
    )
    agent_suggested_weight: Optional[float] = Field(
        default=None,
        description=(
            "Weight suggested by the per-ticker Portfolio Manager's position_sizing "
            "field, before portfolio-level constraint normalisation."
        ),
    )
    conviction: ConvictionLevel = Field(
        description="Conviction: High / Medium / Low"
    )
    momentum_score: Optional[float] = Field(
        default=None, description="Normalised momentum z-score from screener"
    )
    quality_score: Optional[float] = Field(
        default=None, description="Normalised quality z-score from screener"
    )
    composite_score: Optional[float] = Field(
        default=None, description="Weighted composite of momentum + quality z-scores"
    )
    price_target: Optional[float] = Field(
        default=None, description="Price target from the per-ticker Portfolio Manager"
    )
    time_horizon: Optional[str] = Field(
        default=None, description="Recommended holding period, e.g. '3-6 months'"
    )
    investment_thesis: str = Field(
        description="2-3 sentence investment rationale for this position"
    )
    overweight_reason: Optional[str] = Field(
        default=None,
        description="Why overweighted vs a neutral benchmark, if applicable",
    )
    underweight_reason: Optional[str] = Field(
        default=None,
        description="Why underweighted vs a neutral benchmark, if applicable",
    )


class PortfolioView(BaseModel):
    """Full target portfolio produced by the Portfolio Construction Agent.

    Holdings are sorted descending by target_weight.  The construction agent
    uses both the LLM-generated PortfolioDecisions and the quantitative
    screener scores to arrive at final weights.
    """

    construction_date: str = Field(
        description="ISO date the portfolio was constructed (YYYY-MM-DD)"
    )
    holdings: List[PortfolioHolding] = Field(
        description="Target holdings, sorted by weight descending"
    )
    cash_weight: float = Field(
        default=0.0, description="Target cash allocation as a decimal"
    )
    construction_rationale: str = Field(
        description="Overall portfolio thesis and how Momentum + Quality drove selection"
    )
    risk_considerations: str = Field(
        description="Key portfolio-level risks and mitigants"
    )
    top_overweights: str = Field(
        description="Narrative summary of the 3-5 highest-conviction overweight positions"
    )
    top_underweights: str = Field(
        description=(
            "Narrative summary of excluded or underweighted names and the reasons "
            "(poor quality, momentum reversal, or low agent conviction)"
        )
    )
    methodology: str = Field(
        default="Momentum + Quality",
        description="Portfolio construction methodology label",
    )

    # Sector exposure summary {sector: weight}
    sector_weights: Optional[Dict[str, float]] = Field(
        default=None,
        description="Aggregated target weights by GICS sector",
    )


# ---------------------------------------------------------------------------
# Rebalancing
# ---------------------------------------------------------------------------


class RebalanceAction(str, Enum):
    BUY = "Buy"    # New position or add to existing
    TRIM = "Trim"  # Reduce existing position
    SELL = "Sell"  # Exit position entirely
    HOLD = "Hold"  # Within drift tolerance — no action needed


class RebalanceTrade(BaseModel):
    """A single rebalance trade."""

    ticker: str
    action: RebalanceAction
    current_weight: float = Field(description="Current weight as decimal")
    target_weight: float = Field(description="Target weight as decimal")
    weight_delta: float = Field(description="target_weight − current_weight")
    drift_pct: float = Field(
        description=(
            "Relative drift: |current − target| / target.  "
            "E.g. 0.30 means 30% drift from target."
        )
    )
    priority: str = Field(description="High / Medium / Low")
    rationale: str = Field(description="Brief reason for this trade (1-2 sentences)")


class RebalanceRecommendation(BaseModel):
    """Full rebalance recommendation comparing current holdings to the target portfolio."""

    trade_date: str = Field(description="ISO date of the rebalance (YYYY-MM-DD)")
    rebalance_type: str = Field(
        description="monthly_scheduled | drift_triggered | initial_construction"
    )
    trades: List[RebalanceTrade] = Field(
        description="Recommended trades, sorted by |weight_delta| descending"
    )
    new_positions: List[str] = Field(
        description="Tickers entering the portfolio for the first time"
    )
    exited_positions: List[str] = Field(
        description="Tickers being fully sold out of the portfolio"
    )
    portfolio_turnover_pct: float = Field(
        description=(
            "Estimated one-way portfolio turnover as a decimal "
            "(sum of absolute weight changes / 2)"
        )
    )
    summary: str = Field(
        description="Executive summary of the rebalance recommendations (3-5 sentences)"
    )
    macro_context: str = Field(
        description="Market or macro context driving the rebalance decisions"
    )


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def render_portfolio_view(view: PortfolioView) -> str:
    """Render a PortfolioView to a compact markdown summary."""
    lines = [
        f"# Portfolio View — {view.construction_date}",
        f"**Methodology**: {view.methodology}",
        "",
        f"**Construction Rationale**: {view.construction_rationale}",
        "",
        "## Target Holdings",
        "| Ticker | Rating | Weight | Conviction | Composite Score |",
        "|--------|--------|--------|------------|-----------------|",
    ]
    for h in sorted(view.holdings, key=lambda x: x.target_weight, reverse=True):
        comp = f"{h.composite_score:.2f}" if h.composite_score is not None else "—"
        lines.append(
            f"| {h.ticker} | {h.rating} | {h.target_weight:.1%} | "
            f"{h.conviction.value} | {comp} |"
        )
    lines += [
        f"| CASH | — | {view.cash_weight:.1%} | — | — |",
        "",
        f"**Top Overweights**: {view.top_overweights}",
        "",
        f"**Top Underweights**: {view.top_underweights}",
        "",
        f"**Risk Considerations**: {view.risk_considerations}",
    ]
    return "\n".join(lines)


def render_rebalance_recommendation(rec: RebalanceRecommendation) -> str:
    """Render a RebalanceRecommendation to markdown."""
    lines = [
        f"# Rebalance Memo — {rec.trade_date}",
        f"**Type**: {rec.rebalance_type}  |  "
        f"**Estimated Turnover**: {rec.portfolio_turnover_pct:.1%}",
        "",
        f"**Summary**: {rec.summary}",
        "",
        f"**Macro Context**: {rec.macro_context}",
        "",
        "## Recommended Trades",
        "| Ticker | Action | Current | Target | Δ Weight | Drift | Priority |",
        "|--------|--------|---------|--------|----------|-------|----------|",
    ]
    for t in rec.trades:
        if t.action == RebalanceAction.HOLD:
            continue
        lines.append(
            f"| {t.ticker} | **{t.action.value}** | {t.current_weight:.1%} | "
            f"{t.target_weight:.1%} | {t.weight_delta:+.1%} | "
            f"{t.drift_pct:.0%} | {t.priority} |"
        )
    if rec.new_positions:
        lines += ["", f"**New Positions**: {', '.join(rec.new_positions)}"]
    if rec.exited_positions:
        lines += ["", f"**Exits**: {', '.join(rec.exited_positions)}"]
    return "\n".join(lines)
