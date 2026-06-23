#!/usr/bin/env python3
"""Dry-run test for the Portfolio Construction Extension.

This script validates the full pipeline WITHOUT making LLM API calls
by using mock data for both the screener results and the per-ticker
portfolio decisions.

Run from the repo root:
    python scripts/test_portfolio.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import tempfile
from datetime import date

# ---- Imports under test ----
from tradingagents.agents.portfolio.schemas import (
    ScreenerResult,
    PortfolioHolding,
    PortfolioView,
    RebalanceTrade,
    RebalanceRecommendation,
    RebalanceAction,
    ConvictionLevel,
    render_portfolio_view,
    render_rebalance_recommendation,
)
from tradingagents.agents.portfolio.screener import MomentumQualityScreener
from tradingagents.agents.portfolio.construction import (
    _parse_final_decision,
    _parse_trader_sizing,
    _parse_position_sizing,
    _apply_constraints,
)
from tradingagents.agents.portfolio.rebalancing import _compute_trades
from tradingagents.portfolio.output import generate_outputs
from tradingagents.default_config import DEFAULT_CONFIG


TRADE_DATE = str(date.today())

# ---------------------------------------------------------------------------
# Test 1: Schema round-trip
# ---------------------------------------------------------------------------

def test_schemas():
    print("\n[1] Testing schema round-trip …")

    holding = PortfolioHolding(
        ticker="AAPL",
        rating="Buy",
        target_weight=0.09,
        conviction=ConvictionLevel.HIGH,
        investment_thesis="Strong iPhone supercycle with AI integration.",
        momentum_score=1.23,
        quality_score=0.87,
        composite_score=1.05,
        price_target=230.0,
        time_horizon="6-12 months",
        overweight_reason="Best-in-class brand and ecosystem lock-in.",
    )

    view = PortfolioView(
        construction_date=TRADE_DATE,
        holdings=[holding],
        cash_weight=0.05,
        construction_rationale="Momentum + Quality — high-conviction tech overweights.",
        risk_considerations="Concentration in tech; monitor rates.",
        top_overweights="AAPL leads on both momentum and quality.",
        top_underweights="Energy excluded on poor momentum.",
        sector_weights={"Technology": 0.09, "Cash": 0.05},
    )

    rendered = render_portfolio_view(view)
    assert "AAPL" in rendered, "Portfolio view render missing AAPL"
    assert "9.0%" in rendered, "Portfolio view render missing weight"
    print("  ✓ PortfolioView renders correctly")

    trade = RebalanceTrade(
        ticker="AAPL",
        action=RebalanceAction.BUY,
        current_weight=0.05,
        target_weight=0.09,
        weight_delta=0.04,
        drift_pct=0.80,
        priority="High",
        rationale="Adding to AAPL to meet target allocation.",
    )
    rec = RebalanceRecommendation(
        trade_date=TRADE_DATE,
        rebalance_type="monthly_scheduled",
        trades=[trade],
        new_positions=[],
        exited_positions=[],
        portfolio_turnover_pct=0.04,
        summary="One trade to rebalance AAPL.",
        macro_context="Soft landing supports growth.",
    )
    rendered_rec = render_rebalance_recommendation(rec)
    assert "AAPL" in rendered_rec
    print("  ✓ RebalanceRecommendation renders correctly")


# ---------------------------------------------------------------------------
# Test 2: Position sizing parser
# ---------------------------------------------------------------------------

def test_position_sizing_parser():
    print("\n[2] Testing position sizing parser …")
    cases = [
        ("5% of portfolio", 0.05),
        ("3-5% allocation", 0.05),  # only one % sign, parser captures "5%"
        ("10%", 0.10),
        (None, None),
        ("", None),
        ("no specific guidance", None),
    ]
    for text, expected in cases:
        result = _parse_position_sizing(text)
        assert result == expected, f"  FAIL: '{text}' → {result}, expected {expected}"
    print("  ✓ All position sizing parsing cases pass")


# ---------------------------------------------------------------------------
# Test 3: Final decision parser
# ---------------------------------------------------------------------------

def test_decision_parser():
    print("\n[3] Testing PortfolioDecision markdown parser …")
    mock_decision = """**Rating**: Buy

**Executive Summary**: Strong conviction to enter AAPL given AI-driven supercycle.

**Investment Thesis**: iPhone 16 with Apple Intelligence features is driving upgrade cycle.

**Price Target**: 230.0

**Time Horizon**: 6-12 months"""

    fields = _parse_final_decision(mock_decision)
    assert fields["rating"] == "Buy", f"Rating parse failed: {fields['rating']}"
    assert fields["price_target"] == 230.0, f"Price target parse failed"
    assert fields["time_horizon"] == "6-12 months"
    print("  ✓ PortfolioDecision markdown parsing works")


# ---------------------------------------------------------------------------
# Test 4: Rebalance trade computation
# ---------------------------------------------------------------------------

def test_rebalance_computation():
    print("\n[4] Testing rebalance trade computation …")
    target = {"AAPL": 0.09, "MSFT": 0.08, "NVDA": 0.07, "GOOGL": 0.06}
    current = {"AAPL": 0.12, "MSFT": 0.08, "AMZN": 0.05}  # NVDA & GOOGL new, AMZN exit

    trades = _compute_trades(target, current, drift_threshold=0.25, rebalance_type="monthly_scheduled")

    trade_map = {t.ticker: t for t in trades}

    # AAPL: current 12% vs target 9% → TRIM
    assert trade_map["AAPL"].action == RebalanceAction.TRIM, f"AAPL should TRIM, got {trade_map['AAPL'].action}"
    # MSFT: exactly on target → HOLD
    assert trade_map["MSFT"].action == RebalanceAction.HOLD, f"MSFT should HOLD, got {trade_map['MSFT'].action}"
    # NVDA: new position → BUY
    assert trade_map["NVDA"].action == RebalanceAction.BUY, f"NVDA should BUY"
    # GOOGL: new position → BUY
    assert trade_map["GOOGL"].action == RebalanceAction.BUY, f"GOOGL should BUY"
    # AMZN: in current but not in target → SELL
    assert trade_map["AMZN"].action == RebalanceAction.SELL, f"AMZN should SELL"

    print("  ✓ Rebalance trade computation correct")


# ---------------------------------------------------------------------------
# Test 5: Constraint application
# ---------------------------------------------------------------------------

def test_constraint_application():
    print("\n[5] Testing portfolio constraint application …")
    mock_holdings_data = [
        {"ticker": "AAPL", "target_weight": 0.30, "conviction": "High",  # exceeds max 15%
         "rationale": "Great stock"},
        {"ticker": "MSFT", "target_weight": 0.01, "conviction": "Low",   # below min 2%
         "rationale": "Solid"},
        {"ticker": "NVDA", "target_weight": 0.08, "conviction": "Medium",
         "rationale": "AI chips"},
    ]
    config = {
        "portfolio": {
            "min_weight": 0.02,
            "max_weight": 0.15,
            "max_positions": 10,
        }
    }
    portfolio_cfg = config["portfolio"]
    screener_map = {}
    decision_map = {
        "AAPL": {"rating": "Buy", "agent_suggested_weight": 0.10},
        "MSFT": {"rating": "Overweight", "agent_suggested_weight": None},
        "NVDA": {"rating": "Buy", "agent_suggested_weight": 0.08},
    }

    holdings = _apply_constraints(mock_holdings_data, screener_map, decision_map, portfolio_cfg)

    for h in holdings:
        assert h.target_weight >= portfolio_cfg["min_weight"], f"{h.ticker} below min_weight"
        assert h.target_weight <= portfolio_cfg["max_weight"], f"{h.ticker} above max_weight"
    total = sum(h.target_weight for h in holdings)
    assert total <= 1.0, f"Total weight {total} > 100%"
    print(f"  ✓ Constraints applied: {len(holdings)} holdings, total weight {total:.1%}")


# ---------------------------------------------------------------------------
# Test 6: Output generation
# ---------------------------------------------------------------------------

def test_output_generation():
    print("\n[6] Testing output file generation …")

    holding = PortfolioHolding(
        ticker="AAPL",
        rating="Buy",
        target_weight=0.09,
        conviction=ConvictionLevel.HIGH,
        investment_thesis="AI-driven supercycle in consumer electronics.",
        momentum_score=1.23,
        quality_score=0.87,
        composite_score=1.05,
        price_target=230.0,
        time_horizon="6-12 months",
        overweight_reason="Best-in-class brand.",
    )
    view = PortfolioView(
        construction_date=TRADE_DATE,
        holdings=[holding],
        cash_weight=0.05,
        construction_rationale="High-conviction Momentum + Quality portfolio.",
        risk_considerations="Tech concentration risk.",
        top_overweights="AAPL — highest composite score.",
        top_underweights="Energy — poor momentum.",
        sector_weights={"Technology": 0.09},
    )

    trade = RebalanceTrade(
        ticker="AAPL",
        action=RebalanceAction.BUY,
        current_weight=0.05,
        target_weight=0.09,
        weight_delta=0.04,
        drift_pct=0.80,
        priority="High",
        rationale="Increasing to target weight.",
    )
    rec = RebalanceRecommendation(
        trade_date=TRADE_DATE,
        rebalance_type="monthly_scheduled",
        trades=[trade],
        new_positions=[],
        exited_positions=[],
        portfolio_turnover_pct=0.04,
        summary="One trade to rebalance AAPL to target.",
        macro_context="Rates stabilising — growth outlook constructive.",
    )

    screener = ScreenerResult(
        ticker="AAPL",
        sector="Technology",
        market_cap=3200.0,
        price=210.5,
        # Momentum
        momentum_1m=0.03,
        momentum_3m=0.12,
        momentum_6m=0.25,
        momentum_12_1m=0.38,
        momentum_score=1.23,
        # Quality
        roe=0.16,
        gross_margin=0.46,
        fcf_margin=0.28,
        fcf_yield=0.033,
        debt_to_ebitda=0.9,
        interest_coverage=35.0,
        quality_score=0.87,
        # Growth
        revenue_growth_yoy=0.08,
        eps_growth_yoy=0.12,
        growth_score=0.72,
        # Valuation
        pe_forward=28.5,
        peg_ratio=1.8,
        ev_to_ebitda=22.0,
        valuation_score=0.45,
        # Analyst
        analyst_rating_mean=1.8,
        analyst_buy_pct=0.72,
        analyst_target_upside=0.12,
        num_analysts=42,
        analyst_score=0.65,
        # Composite
        composite_score=1.05,
        composite_rank=1,
        passed_hard_filters=True,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = generate_outputs(
            portfolio_view=view,
            rebalance_rec=rec,
            screener_results=[screener],
            trade_date=TRADE_DATE,
            output_dir=tmpdir,
        )

        assert "excel" in paths and os.path.exists(paths["excel"]), "Excel not generated"
        assert "markdown" in paths and os.path.exists(paths["markdown"]), "Markdown not generated"

        excel_size = os.path.getsize(paths["excel"])
        md_size = os.path.getsize(paths["markdown"])
        print(f"  ✓ Excel generated ({excel_size:,} bytes): {os.path.basename(paths['excel'])}")
        print(f"  ✓ Markdown generated ({md_size:,} bytes): {os.path.basename(paths['markdown'])}")

        # Verify markdown content
        with open(paths["markdown"]) as f:
            md_content = f.read()
        assert "AAPL" in md_content
        assert "Momentum + Quality" in md_content
        print("  ✓ Markdown content verified")


# ---------------------------------------------------------------------------
# Test 7: Default config has portfolio keys
# ---------------------------------------------------------------------------

def test_default_config():
    print("\n[7] Testing default config …")
    cfg = DEFAULT_CONFIG
    assert "portfolio" in cfg, "Missing 'portfolio' key in DEFAULT_CONFIG"
    portfolio_cfg = cfg["portfolio"]
    required_keys = [
        "universe",
        "pre_analysis_cap",   # replaces old num_candidates
        "max_positions",
        "min_weight",
        "max_weight",
        "momentum_weight",
        "quality_weight",
        "drift_threshold",
        "rebalance_day",
    ]
    for key in required_keys:
        assert key in portfolio_cfg, f"Missing portfolio config key: {key}"
    # Check funnel invariant: pre_analysis_cap >= max_positions
    assert portfolio_cfg["pre_analysis_cap"] >= portfolio_cfg["max_positions"], (
        "pre_analysis_cap must be >= max_positions so the LLM sees enough candidates"
    )
    print(f"  ✓ All {len(required_keys)} portfolio config keys present")
    print(f"  ✓ Funnel: {portfolio_cfg['pre_analysis_cap']} analysed → "
          f"max {portfolio_cfg['max_positions']} in portfolio")


# ---------------------------------------------------------------------------
# Test 8: ScreenerResult expanded fields + hard-filter flag
# ---------------------------------------------------------------------------

def test_screener_result_fields():
    print("\n[8] Testing expanded ScreenerResult schema …")

    # Full institutional-grade result
    sr = ScreenerResult(
        ticker="MSFT",
        sector="Technology",
        industry="Software",
        market_cap=3100.0,
        avg_daily_volume=1500.0,
        price=430.0,
        beta=0.9,
        # Quality
        roe=0.35,
        roa=0.15,
        roic=0.28,
        gross_margin=0.70,
        operating_margin=0.45,
        fcf_margin=0.33,
        fcf_yield=0.025,
        debt_to_ebitda=0.5,
        interest_coverage=40.0,
        current_ratio=1.8,
        quality_score=1.5,
        # Growth
        revenue_growth_yoy=0.17,
        eps_growth_yoy=0.22,
        forward_eps_growth=0.18,
        earnings_growth_3y=0.20,
        growth_score=1.2,
        # Valuation
        pe_trailing=35.0,
        pe_forward=30.0,
        peg_ratio=1.4,
        ev_to_ebitda=25.0,
        price_to_sales=13.0,
        price_to_book=12.0,
        valuation_score=0.3,
        # Momentum
        momentum_1m=0.04,
        momentum_3m=0.15,
        momentum_6m=0.28,
        momentum_12_1m=0.42,
        momentum_score=1.3,
        # Analyst
        analyst_rating_mean=1.6,
        analyst_buy_pct=0.80,
        analyst_target_upside=0.15,
        num_analysts=50,
        analyst_score=0.9,
        # Composite
        composite_score=1.25,
        composite_rank=1,
        passed_hard_filters=True,
    )

    assert sr.ticker == "MSFT"
    assert sr.quality_score == 1.5
    assert sr.growth_score == 1.2
    assert sr.valuation_score == 0.3
    assert sr.momentum_score == 1.3
    assert sr.analyst_score == 0.9
    assert sr.passed_hard_filters is True
    print("  ✓ Full ScreenerResult with all 5-factor scores round-trips correctly")

    # Hard-filter failure
    failed = ScreenerResult(
        ticker="PENNY",
        passed_hard_filters=False,
        filter_reason="market cap: $0.01B < $0.5B minimum",
    )
    assert failed.passed_hard_filters is False
    assert "market cap" in (failed.filter_reason or "")
    print("  ✓ Hard-filter failure ScreenerResult records reason correctly")


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("TradingAgents Portfolio Extension — Dry-Run Test Suite")
    print("=" * 60)

    tests = [
        test_schemas,
        test_position_sizing_parser,
        test_decision_parser,
        test_rebalance_computation,
        test_constraint_application,
        test_output_generation,
        test_default_config,
        test_screener_result_fields,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
