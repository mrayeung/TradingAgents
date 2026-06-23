"""Portfolio Construction Agent.

Reads all per-ticker PortfolioDecisions (from TradingAgentsGraph.propagate)
plus the screener's quantitative scores, then uses an LLM to assemble a
target portfolio with conviction-weighted allocations.

Key design: the individual Portfolio Manager's own position_sizing field
(e.g. "5% of portfolio") is parsed and used as the *initial* weight
suggestion before the LLM re-scores in a cross-portfolio context and
portfolio-level constraints are applied.

Flow
----
    1. Filter candidates to investable ratings (Buy / Overweight, optionally Hold)
    2. Build prompt with all PortfolioDecisions + screener scores
       including each agent's suggested sizing
    3. LLM returns JSON weight assignments + narrative
    4. Apply hard constraints: min_weight, max_weight, max_positions, sum=100%
    5. Compute sector weights and return PortfolioView
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.agents.portfolio.schemas import (
    ConvictionLevel,
    PortfolioHolding,
    PortfolioView,
    ScreenerResult,
)

logger = logging.getLogger(__name__)

# Ratings considered investable (in priority order)
_INVESTABLE_RATINGS = {"Buy", "Overweight", "Hold"}
_HIGH_CONVICTION_RATINGS = {"Buy", "Overweight"}

# Regex to extract a percentage from position_sizing strings like "5% of portfolio"
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# Section markers returned by the LLM after the JSON block
_SECTION_MARKERS = [
    "CONSTRUCTION_RATIONALE",
    "RISK_CONSIDERATIONS",
    "TOP_OVERWEIGHTS",
    "TOP_UNDERWEIGHTS",
]


def _parse_position_sizing(sizing_text: Optional[str]) -> Optional[float]:
    """Extract a decimal weight from a free-text position sizing string.

    Examples
    --------
    "5% of portfolio"   → 0.05
    "3-5% allocation"   → 0.04  (midpoint)
    "10%"               → 0.10
    None / ""           → None
    """
    if not sizing_text:
        return None
    matches = _PCT_RE.findall(sizing_text)
    if not matches:
        return None
    values = [float(v) / 100.0 for v in matches]
    return sum(values) / len(values)  # midpoint for ranges


def _parse_final_decision(decision_text: str) -> Dict[str, Any]:
    """Extract structured fields from a rendered PortfolioDecision markdown string.

    Returns a dict with keys: rating, price_target, time_horizon, executive_summary,
    investment_thesis (all may be None if not found).
    """
    result: Dict[str, Any] = {
        "rating": None,
        "price_target": None,
        "time_horizon": None,
        "executive_summary": None,
        "investment_thesis": None,
    }
    for line in decision_text.splitlines():
        line = line.strip()
        if line.startswith("**Rating**:"):
            result["rating"] = line.split(":", 1)[-1].strip()
        elif line.startswith("**Price Target**:"):
            try:
                result["price_target"] = float(
                    line.split(":", 1)[-1].strip().replace(",", "")
                )
            except ValueError:
                pass
        elif line.startswith("**Time Horizon**:"):
            result["time_horizon"] = line.split(":", 1)[-1].strip()
        elif line.startswith("**Executive Summary**:"):
            result["executive_summary"] = line.split(":", 1)[-1].strip()
        elif line.startswith("**Investment Thesis**:"):
            result["investment_thesis"] = line.split(":", 1)[-1].strip()
    return result


def _parse_trader_sizing(trader_plan_text: str) -> Optional[float]:
    """Extract position sizing from a rendered TraderProposal markdown string."""
    for line in trader_plan_text.splitlines():
        if line.strip().startswith("**Position Sizing**:"):
            sizing_str = line.split(":", 1)[-1].strip()
            return _parse_position_sizing(sizing_str)
    return None


def _build_prompt(
    candidates: List[Tuple[str, Dict[str, Any], Optional[ScreenerResult]]],
    config: dict,
) -> str:
    """Build the LLM prompt for portfolio weight allocation.

    Parameters
    ----------
    candidates : list of (ticker, decision_fields, screener_result)
    config : portfolio config sub-dict
    """
    max_pos = config.get("max_positions", 15)
    min_w = config.get("min_weight", 0.02) * 100
    max_w = config.get("max_weight", 0.15) * 100

    sections = [
        "You are a Portfolio Construction Specialist using a Momentum + Quality strategy.",
        "Your task: review the research findings for each candidate and assign target "
        "portfolio weights that reflect relative conviction, quality, and price momentum.",
        "",
        "## CANDIDATE ANALYSES",
        "",
    ]

    for ticker, fields, sr in candidates:
        rating = fields.get("rating", "Unknown")
        agent_w = fields.get("agent_suggested_weight")
        agent_w_str = f"{agent_w:.1%}" if agent_w is not None else "not specified"
        mom_str = f"{sr.momentum_score:.2f}" if (sr and sr.momentum_score is not None) else "N/A"
        qual_str = f"{sr.quality_score:.2f}" if (sr and sr.quality_score is not None) else "N/A"
        comp_str = f"{sr.composite_score:.2f}" if (sr and sr.composite_score is not None) else "N/A"
        pt = fields.get("price_target")
        th = fields.get("time_horizon", "")
        summary = fields.get("executive_summary") or fields.get("investment_thesis") or ""
        sector = sr.sector if sr else "Unknown"

        sections.append(f"### {ticker}  [{rating}]  Sector: {sector}")
        sections.append(
            f"- Agent suggested weight: {agent_w_str}"
        )
        sections.append(
            f"- Screener scores  — Momentum z: {mom_str} | Quality z: {qual_str} | "
            f"Composite: {comp_str}"
        )
        if pt:
            sections.append(f"- Price target: ${pt:.2f}  |  Horizon: {th}")
        sections.append(f"- Analysis summary: {summary[:400]}")
        sections.append("")

    sections += [
        "## PORTFOLIO CONSTRAINTS",
        f"- Maximum positions: {max_pos}",
        f"- Position size range: {min_w:.0f}% – {max_w:.0f}%",
        "- Weights must sum to ~100% (small cash allowance up to 5% is acceptable)",
        "- Prefer Buy/Overweight names; include Hold names only if they rank strongly "
        "on Momentum + Quality",
        "- Diversify across sectors where possible",
        "- Use agent-suggested weights as starting points, then adjust based on "
        "cross-portfolio relative ranking",
        "",
        "## OUTPUT FORMAT",
        "Return EXACTLY the following structure (no extra commentary before the JSON):",
        "",
        '```json',
        '[',
        '  {',
        '    "ticker": "AAPL",',
        '    "target_weight": 0.09,',
        '    "conviction": "High",',
        '    "rationale": "2-3 sentence investment thesis",',
        '    "overweight_reason": "Why overweighted vs neutral benchmark (or null)",',
        '    "underweight_reason": null',
        '  }',
        ']',
        '```',
        "",
        "Then, on separate lines, provide:",
        "CONSTRUCTION_RATIONALE: <2-3 sentences on overall portfolio thesis>",
        "RISK_CONSIDERATIONS: <2-3 sentences on key risks>",
        "TOP_OVERWEIGHTS: <narrative on top 3-5 OW names>",
        "TOP_UNDERWEIGHTS: <narrative on excluded/UW names>",
    ]

    return "\n".join(sections)


def _parse_llm_response(
    response_text: str,
) -> Tuple[List[Dict], str, str, str, str]:
    """Parse the LLM's structured response into JSON holdings + narrative sections."""
    # Extract JSON block
    json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", response_text, re.DOTALL)
    if not json_match:
        # Fallback: try to find a raw JSON array
        json_match = re.search(r"(\[\s*\{.*?\}\s*\])", response_text, re.DOTALL)

    holdings_data = []
    if json_match:
        try:
            holdings_data = json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            logger.warning("Could not parse LLM JSON block: %s", e)

    # Extract narrative sections
    narratives = {}
    remaining = response_text
    if json_match:
        remaining = response_text[json_match.end():]

    for marker in _SECTION_MARKERS:
        pattern = rf"{marker}:\s*(.+?)(?={('|').join(_SECTION_MARKERS)}|$)"
        m = re.search(pattern, remaining, re.DOTALL | re.IGNORECASE)
        narratives[marker] = m.group(1).strip() if m else ""

    return (
        holdings_data,
        narratives.get("CONSTRUCTION_RATIONALE", ""),
        narratives.get("RISK_CONSIDERATIONS", ""),
        narratives.get("TOP_OVERWEIGHTS", ""),
        narratives.get("TOP_UNDERWEIGHTS", ""),
    )


def _apply_constraints(
    raw_holdings: List[Dict],
    screener_map: Dict[str, ScreenerResult],
    decision_map: Dict[str, Dict],
    config: dict,
) -> List[PortfolioHolding]:
    """Normalise weights and enforce min/max/max_positions constraints."""
    min_w = config.get("min_weight", 0.02)
    max_w = config.get("max_weight", 0.15)
    max_pos = config.get("max_positions", 15)

    # Clamp each weight
    clamped = []
    for h in raw_holdings:
        w = max(min_w, min(max_w, float(h.get("target_weight", min_w))))
        clamped.append({**h, "target_weight": w})

    # Sort by weight desc, truncate to max_positions
    clamped.sort(key=lambda x: x["target_weight"], reverse=True)
    clamped = clamped[:max_pos]

    # Normalise so weights sum to ≤ 1.0 (leave room for cash)
    total = sum(h["target_weight"] for h in clamped)
    if total > 0:
        scale = min(1.0, 1.0 / total)  # scale down if over-weight, never up
        for h in clamped:
            h["target_weight"] = round(h["target_weight"] * scale, 4)

    holdings = []
    for h in clamped:
        ticker = h.get("ticker", "")
        sr = screener_map.get(ticker)
        fields = decision_map.get(ticker, {})

        conviction_str = h.get("conviction", "Medium")
        try:
            conviction = ConvictionLevel(conviction_str)
        except ValueError:
            conviction = ConvictionLevel.MEDIUM

        holdings.append(
            PortfolioHolding(
                ticker=ticker,
                rating=fields.get("rating", "Unknown"),
                target_weight=h["target_weight"],
                agent_suggested_weight=fields.get("agent_suggested_weight"),
                conviction=conviction,
                momentum_score=sr.momentum_score if sr else None,
                quality_score=sr.quality_score if sr else None,
                composite_score=sr.composite_score if sr else None,
                price_target=fields.get("price_target"),
                time_horizon=fields.get("time_horizon"),
                investment_thesis=h.get("rationale", ""),
                overweight_reason=h.get("overweight_reason") or None,
                underweight_reason=h.get("underweight_reason") or None,
            )
        )

    return holdings


def create_portfolio_construction_agent(llm):
    """Return a callable portfolio construction function bound to ``llm``.

    Parameters
    ----------
    llm : LangChain LLM instance
        The deep-thinking LLM (same one used by the Portfolio Manager).

    Returns
    -------
    callable
        ``build_portfolio(ticker_results, screener_results, config)``
        → ``PortfolioView``
    """

    def build_portfolio(
        ticker_results: List[Tuple[str, str, str]],
        screener_results: List[ScreenerResult],
        config: dict,
    ) -> PortfolioView:
        """Construct a target portfolio from individual ticker analyses.

        Parameters
        ----------
        ticker_results : list of (ticker, final_trade_decision, trader_investment_plan)
            The ``final_trade_decision`` and ``trader_investment_plan`` strings
            come directly from ``TradingAgentsGraph.propagate()`` final_state.
        screener_results : list of ScreenerResult
            Quantitative momentum + quality scores from the screener.
        config : dict
            The ``portfolio`` sub-key of the main TradingAgents config.

        Returns
        -------
        PortfolioView
        """
        portfolio_cfg = config.get("portfolio", {})
        min_rating_str = portfolio_cfg.get("min_rating", "Hold")

        screener_map = {sr.ticker: sr for sr in screener_results}

        # ---- Build per-ticker decision dicts ----
        decision_map: Dict[str, Dict] = {}
        for ticker, final_decision, trader_plan in ticker_results:
            fields = _parse_final_decision(final_decision)
            fields["agent_suggested_weight"] = _parse_trader_sizing(trader_plan)
            decision_map[ticker] = fields

        # ---- Filter to investable candidates ----
        investable_ratings = {"Buy", "Overweight"}
        if min_rating_str == "Hold":
            investable_ratings.add("Hold")

        candidates = []
        for ticker, fields in decision_map.items():
            rating = (fields.get("rating") or "Unknown").strip()
            # Normalise variant spellings
            if rating in investable_ratings:
                sr = screener_map.get(ticker)
                candidates.append((ticker, fields, sr))

        if not candidates:
            logger.warning(
                "No investable candidates found (all ratings below %s)", min_rating_str
            )
            # Fall back: include all tickers with at least a rating
            candidates = [
                (t, f, screener_map.get(t))
                for t, f in decision_map.items()
                if f.get("rating")
            ]

        logger.info(
            "Building portfolio from %d investable candidates: %s",
            len(candidates),
            [c[0] for c in candidates],
        )

        # ---- LLM weight allocation ----
        prompt = _build_prompt(candidates, portfolio_cfg)
        try:
            response = llm.invoke(prompt)
            response_text = (
                response.content if hasattr(response, "content") else str(response)
            )
        except Exception as e:
            logger.error("LLM call failed in construction agent: %s", e)
            response_text = ""

        (
            raw_holdings,
            construction_rationale,
            risk_considerations,
            top_overweights,
            top_underweights,
        ) = _parse_llm_response(response_text)

        # If LLM parsing failed, create equal-weight holdings as fallback
        if not raw_holdings:
            logger.warning("LLM response parse failed; falling back to equal-weight")
            n = min(len(candidates), portfolio_cfg.get("max_positions", 15))
            eq_w = round(1.0 / n, 4) if n > 0 else 0.0
            raw_holdings = [
                {
                    "ticker": c[0],
                    "target_weight": eq_w,
                    "conviction": "Medium",
                    "rationale": c[1].get("executive_summary") or "",
                    "overweight_reason": None,
                    "underweight_reason": None,
                }
                for c in candidates[:n]
            ]

        # ---- Apply constraints ----
        holdings = _apply_constraints(raw_holdings, screener_map, decision_map, portfolio_cfg)

        # ---- Cash allocation ----
        invested = sum(h.target_weight for h in holdings)
        cash_weight = round(max(0.0, 1.0 - invested), 4)

        # ---- Sector weights ----
        sector_weights: Dict[str, float] = {}
        for h in holdings:
            sr = screener_map.get(h.ticker)
            sector = (sr.sector if sr else None) or "Unknown"
            sector_weights[sector] = round(sector_weights.get(sector, 0.0) + h.target_weight, 4)

        # Sort holdings by weight desc
        holdings.sort(key=lambda x: x.target_weight, reverse=True)

        return PortfolioView(
            construction_date=str(date.today()),
            holdings=holdings,
            cash_weight=cash_weight,
            construction_rationale=construction_rationale or (
                "Portfolio constructed using Momentum + Quality strategy with "
                "LLM-assessed conviction from individual ticker research."
            ),
            risk_considerations=risk_considerations or (
                "Concentration risk, factor crowding, and macro regime shifts "
                "are the primary portfolio-level risks."
            ),
            top_overweights=top_overweights or "",
            top_underweights=top_underweights or "",
            methodology="Momentum + Quality",
            sector_weights=sector_weights if sector_weights else None,
        )

    return build_portfolio
