"""Output generators for the Portfolio Construction Extension.

Produces the following files per run:

  portfolio/
    AAPL_report_YYYYMMDD.md        ← individual ticker research report
    MSFT_report_YYYYMMDD.md
    NVDA_report_YYYYMMDD.md
    portfolio_YYYYMMDD.xlsx        ← combined portfolio workbook
    rebalance_memo_YYYYMMDD.md     ← human-readable rebalance memo
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from tradingagents.agents.portfolio.schemas import (
    PortfolioView,
    RebalanceAction,
    RebalanceRecommendation,
    ScreenerResult,
    render_portfolio_view,
    render_rebalance_recommendation,
)


# ---------------------------------------------------------------------------
# Excel helpers
# ---------------------------------------------------------------------------


def _portfolio_sheet(writer, portfolio_view: PortfolioView) -> None:
    """Write the Portfolio View sheet."""
    rows = []
    for h in portfolio_view.holdings:
        rows.append({
            "Ticker": h.ticker,
            "Rating": h.rating,
            "Conviction": h.conviction.value,
            "Target Weight (%)": round(h.target_weight * 100, 2),
            "Agent Suggested (%)": round(h.agent_suggested_weight * 100, 2) if h.agent_suggested_weight else None,
            "Momentum Score": round(h.momentum_score, 3) if h.momentum_score is not None else None,
            "Quality Score": round(h.quality_score, 3) if h.quality_score is not None else None,
            "Composite Score": round(h.composite_score, 3) if h.composite_score is not None else None,
            "Price Target": h.price_target,
            "Time Horizon": h.time_horizon,
            "Investment Thesis": h.investment_thesis,
            "Overweight Reason": h.overweight_reason or "",
            "Underweight Reason": h.underweight_reason or "",
        })
    # Cash row
    rows.append({
        "Ticker": "CASH",
        "Rating": "—",
        "Conviction": "—",
        "Target Weight (%)": round(portfolio_view.cash_weight * 100, 2),
        "Agent Suggested (%)": None,
        "Momentum Score": None,
        "Quality Score": None,
        "Composite Score": None,
        "Price Target": None,
        "Time Horizon": None,
        "Investment Thesis": "",
        "Overweight Reason": "",
        "Underweight Reason": "",
    })

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name="Portfolio View", index=False)

    # Auto-size columns
    ws = writer.sheets["Portfolio View"]
    for col_idx, col in enumerate(df.columns, start=1):
        max_len = max(len(str(col)), df[col].astype(str).str.len().max())
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 60)


def _rebalance_sheet(writer, rec: RebalanceRecommendation) -> None:
    """Write the Rebalance Trades sheet."""
    rows = []
    for t in rec.trades:
        rows.append({
            "Ticker": t.ticker,
            "Action": t.action.value,
            "Current Weight (%)": round(t.current_weight * 100, 2),
            "Target Weight (%)": round(t.target_weight * 100, 2),
            "Δ Weight (%)": round(t.weight_delta * 100, 2),
            "Drift (%)": round(t.drift_pct * 100, 1) if t.drift_pct < 9.0 else "New/Exit",
            "Priority": t.priority,
            "Rationale": t.rationale,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "Ticker", "Action", "Current Weight (%)", "Target Weight (%)",
            "Δ Weight (%)", "Drift (%)", "Priority", "Rationale",
        ])
    df.to_excel(writer, sheet_name="Rebalance Trades", index=False)

    ws = writer.sheets["Rebalance Trades"]
    for col_idx, col in enumerate(df.columns, start=1):
        max_len = max(len(str(col)), df[col].astype(str).str.len().max()) if not df.empty else len(col)
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 60)


def _screener_sheet(writer, screener_results: List[ScreenerResult]) -> None:
    """Write the Screener Results sheet.

    Includes every ticker that was scored — both survivors (passed_hard_filters=True)
    and tickers eliminated by hard filters (passed_hard_filters=False).  Rows are
    sorted descending by composite_score so the highest-ranked names appear first;
    filtered-out tickers fall to the bottom.
    """
    def _pct(v) -> Optional[float]:
        return round(v * 100, 2) if v is not None else None

    def _r2(v) -> Optional[float]:
        return round(v, 2) if v is not None else None

    def _r3(v) -> Optional[float]:
        return round(v, 3) if v is not None else None

    rows = []
    for r in screener_results:
        rows.append({
            # ── Identity ──────────────────────────────────────────────────
            "Ticker":              r.ticker,
            "Sector":              r.sector or "",
            "Industry":            r.industry or "",
            "Market Cap ($B)":     _r2(r.market_cap),
            "Avg Daily Vol ($M)":  _r2(r.avg_daily_volume),
            "Price":               _r2(r.price),
            "Beta":                _r2(r.beta),
            # ── Hard-filter status ────────────────────────────────────────
            "Passed Filters":      "Yes" if r.passed_hard_filters else "No",
            "Filter Reason":       r.filter_reason or "",
            # ── Composite & factor z-scores ───────────────────────────────
            "Composite Score":     _r3(r.composite_score),
            "Composite Rank":      r.composite_rank,
            "Quality Score":       _r3(r.quality_score),
            "Growth Score":        _r3(r.growth_score),
            "Valuation Score":     _r3(r.valuation_score),
            "Momentum Score":      _r3(r.momentum_score),
            "Analyst Score":       _r3(r.analyst_score),
            # ── Quality metrics ───────────────────────────────────────────
            "ROE (%)":             _pct(r.roe),
            "ROA (%)":             _pct(r.roa),
            "ROIC (%)":            _pct(r.roic),
            "Gross Margin (%)":    _pct(r.gross_margin),
            "Operating Margin (%)": _pct(r.operating_margin),
            "FCF Margin (%)":      _pct(r.fcf_margin),
            "FCF Yield (%)":       _pct(r.fcf_yield),
            "Debt/EBITDA":         _r2(r.debt_to_ebitda),
            "Interest Coverage":   _r2(r.interest_coverage),
            "Current Ratio":       _r2(r.current_ratio),
            # ── Growth metrics ────────────────────────────────────────────
            "Revenue Growth YoY (%)": _pct(r.revenue_growth_yoy),
            "EPS Growth YoY (%)":  _pct(r.eps_growth_yoy),
            "Fwd EPS Growth (%)":  _pct(r.forward_eps_growth),
            "3Y Earnings Growth (%)": _pct(r.earnings_growth_3y),
            # ── Valuation metrics ─────────────────────────────────────────
            "P/E (Trailing)":      _r2(r.pe_trailing),
            "P/E (Forward)":       _r2(r.pe_forward),
            "PEG Ratio":           _r2(r.peg_ratio),
            "EV/EBITDA":           _r2(r.ev_to_ebitda),
            "P/S":                 _r2(r.price_to_sales),
            "P/B":                 _r2(r.price_to_book),
            # ── Momentum ─────────────────────────────────────────────────
            "1M Return (%)":       _pct(r.momentum_1m),
            "3M Return (%)":       _pct(r.momentum_3m),
            "6M Return (%)":       _pct(r.momentum_6m),
            "12-1M Return (%)":    _pct(r.momentum_12_1m),
            # ── Analyst sentiment ─────────────────────────────────────────
            "Analyst Rating Mean": _r2(r.analyst_rating_mean),
            "Buy Pct (%)":         _pct(r.analyst_buy_pct),
            "Target Upside (%)":   _pct(r.analyst_target_upside),
            "# Analysts":          r.num_analysts,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        # Passed tickers first (sorted by composite score), then filtered ones
        df["_passed_sort"] = df["Passed Filters"].map({"Yes": 0, "No": 1})
        df = df.sort_values(
            ["_passed_sort", "Composite Score"],
            ascending=[True, False],
            na_position="last",
        ).drop(columns=["_passed_sort"])

    df.to_excel(writer, sheet_name="Screener Results", index=False)

    ws = writer.sheets["Screener Results"]
    for col_idx, col in enumerate(df.columns, start=1):
        max_len = max(len(str(col)), df[col].astype(str).str.len().max()) if not df.empty else len(col)
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 30)


def _sector_sheet(writer, portfolio_view: PortfolioView) -> None:
    """Write a Sector Exposure summary sheet."""
    if not portfolio_view.sector_weights:
        return

    rows = [
        {"Sector": sector, "Target Weight (%)": round(w * 100, 2)}
        for sector, w in sorted(
            portfolio_view.sector_weights.items(), key=lambda x: x[1], reverse=True
        )
    ]
    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name="Sector Exposure", index=False)


def generate_excel(
    portfolio_view: PortfolioView,
    rebalance_rec: Optional[RebalanceRecommendation],
    screener_results: List[ScreenerResult],
    trade_date: str,
    output_dir: str,
) -> str:
    """Generate the portfolio Excel workbook and return its file path."""
    filename = f"portfolio_{trade_date.replace('-', '')}.xlsx"
    path = os.path.join(output_dir, filename)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _portfolio_sheet(writer, portfolio_view)
        if rebalance_rec is not None:
            _rebalance_sheet(writer, rebalance_rec)
        _screener_sheet(writer, screener_results)
        _sector_sheet(writer, portfolio_view)

    return path


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


def generate_markdown(
    portfolio_view: PortfolioView,
    rebalance_rec: Optional[RebalanceRecommendation],
    trade_date: str,
    output_dir: str,
) -> str:
    """Generate the rebalance memo Markdown file and return its file path."""
    filename = f"rebalance_memo_{trade_date.replace('-', '')}.md"
    path = os.path.join(output_dir, filename)

    sections = [
        f"# Portfolio Rebalance Memo",
        f"**Date**: {trade_date}  |  **Methodology**: {portfolio_view.methodology}",
        "",
        "---",
        "",
        render_portfolio_view(portfolio_view),
    ]

    if rebalance_rec:
        sections += [
            "",
            "---",
            "",
            render_rebalance_recommendation(rebalance_rec),
        ]

    # Detailed per-position rationale
    sections += [
        "",
        "---",
        "",
        "## Position-Level Detail",
        "",
    ]
    for h in portfolio_view.holdings:
        ow_note = f"\n  > **Overweight reason**: {h.overweight_reason}" if h.overweight_reason else ""
        uw_note = f"\n  > **Underweight reason**: {h.underweight_reason}" if h.underweight_reason else ""
        pt_note = f"  |  Price Target: ${h.price_target:.2f}" if h.price_target else ""
        th_note = f"  |  Horizon: {h.time_horizon}" if h.time_horizon else ""
        mom = f"{h.momentum_score:.2f}" if h.momentum_score is not None else "—"
        qual = f"{h.quality_score:.2f}" if h.quality_score is not None else "—"

        sections.append(
            f"### {h.ticker}  —  {h.target_weight:.1%}  [{h.rating}, {h.conviction.value} conviction]"
        )
        sections.append(f"*Momentum z: {mom}  |  Quality z: {qual}{pt_note}{th_note}*")
        sections.append("")
        sections.append(h.investment_thesis)
        if ow_note:
            sections.append(ow_note)
        if uw_note:
            sections.append(uw_note)
        sections.append("")

    # Footer
    sections += [
        "---",
        "",
        f"*Generated by TradingAgents Portfolio Construction Extension on {trade_date}*",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(sections))

    return path


# ---------------------------------------------------------------------------
# Per-ticker research report
# ---------------------------------------------------------------------------


def generate_ticker_report(
    ticker: str,
    trade_date: str,
    full_state: Dict[str, Any],
    output_dir: str,
) -> str:
    """Write a self-contained Markdown research report for a single ticker.

    The report mirrors the sections produced by a standard TradingAgents run:
    Market Analysis, Sentiment, News, Fundamentals, Bull/Bear Debate,
    Investment Plan, Trader Proposal, Risk Debate, and Final PM Decision.

    Parameters
    ----------
    ticker : str
    trade_date : str     YYYY-MM-DD
    full_state : dict    The ``final_state`` dict from TradingAgentsGraph.propagate()
    output_dir : str     Portfolio output directory

    Returns
    -------
    str  Path to the saved report file
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{ticker}_report_{trade_date.replace('-', '')}.md"
    path = os.path.join(output_dir, filename)

    def _section(title: str, content: str) -> List[str]:
        content = (content or "").strip()
        if not content:
            return []
        return [f"## {title}", "", content, ""]

    lines: List[str] = [
        f"# {ticker} — Research Report",
        f"**Date**: {trade_date}  |  **Generated by**: TradingAgents Portfolio Extension",
        "",
        "---",
        "",
    ]

    # ---- Analyst reports ----
    lines += _section("Market Analysis", full_state.get("market_report", ""))
    lines += _section("Sentiment Analysis", full_state.get("sentiment_report", ""))
    lines += _section("News Analysis", full_state.get("news_report", ""))
    lines += _section("Fundamentals Analysis", full_state.get("fundamentals_report", ""))

    # ---- Bull / Bear debate ----
    debate = full_state.get("investment_debate_state") or {}
    bull_history = debate.get("bull_history", "")
    bear_history = debate.get("bear_history", "")
    debate_history = debate.get("history", "")

    if bull_history or bear_history:
        lines += ["## Bull / Bear Debate", ""]
        if bull_history:
            lines += ["### 🐂 Bull Case", "", bull_history.strip(), ""]
        if bear_history:
            lines += ["### 🐻 Bear Case", "", bear_history.strip(), ""]
        if debate.get("judge_decision"):
            lines += ["### Research Manager Verdict", "", debate["judge_decision"].strip(), ""]
    elif debate_history:
        lines += _section("Bull / Bear Debate", debate_history)

    # ---- Investment plan ----
    lines += _section("Investment Plan (Research Manager)", full_state.get("investment_plan", ""))

    # ---- Trader proposal ----
    lines += _section("Trader Proposal", full_state.get("trader_investment_plan", ""))

    # ---- Risk debate ----
    risk = full_state.get("risk_debate_state") or {}
    risk_history = risk.get("history", "")
    if risk_history:
        lines += ["## Risk Analyst Debate", ""]
        if risk.get("aggressive_history"):
            lines += ["### ⚡ Aggressive", "", risk["aggressive_history"].strip(), ""]
        if risk.get("conservative_history"):
            lines += ["### 🛡 Conservative", "", risk["conservative_history"].strip(), ""]
        if risk.get("neutral_history"):
            lines += ["### ⚖️ Neutral", "", risk["neutral_history"].strip(), ""]
        if risk.get("judge_decision"):
            lines += ["### Portfolio Manager Verdict", "", risk["judge_decision"].strip(), ""]

    # ---- Final decision (always last, highlighted) ----
    final = (full_state.get("final_trade_decision") or "").strip()
    if final:
        lines += [
            "---",
            "",
            "## ⭐ Final Portfolio Manager Decision",
            "",
            final,
            "",
        ]

    lines += [
        "---",
        "",
        f"*Generated by TradingAgents Portfolio Extension on {trade_date}*",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_outputs(
    portfolio_view: PortfolioView,
    rebalance_rec: Optional[RebalanceRecommendation],
    screener_results: List[ScreenerResult],
    trade_date: str,
    output_dir: str,
) -> Dict[str, str]:
    """Generate all output files and return a dict of {format: path}.

    Parameters
    ----------
    portfolio_view : PortfolioView
    rebalance_rec : RebalanceRecommendation or None
    screener_results : list of ScreenerResult
    trade_date : str   YYYY-MM-DD
    output_dir : str   directory to write outputs into

    Returns
    -------
    dict with keys "excel" and "markdown"
    """
    os.makedirs(output_dir, exist_ok=True)

    excel_path = generate_excel(
        portfolio_view, rebalance_rec, screener_results, trade_date, output_dir
    )
    md_path = generate_markdown(
        portfolio_view, rebalance_rec, trade_date, output_dir
    )

    return {"excel": excel_path, "markdown": md_path}
