#!/usr/bin/env python3
"""Retroactive dashboard generator for a completed (or in-progress) portfolio run.

Reads the output files already saved by the pipeline — individual ticker
report .md files, the portfolio Excel workbook, and the rebalance memo —
and builds the live HTML dashboard without requiring the pipeline to re-run.

Usage:
    # Auto-detect from default output dir
    uv run python scripts/generate_dashboard.py

    # Point at a specific directory + date
    uv run python scripts/generate_dashboard.py --dir ~/.tradingagents/logs/portfolio --date 2026-05-05

    # Point at a specific Excel file
    uv run python scripts/generate_dashboard.py --excel ~/.tradingagents/logs/portfolio/portfolio_20260505.xlsx
"""

import argparse
import glob
import os
import re
import sys
import webbrowser
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(description="Generate portfolio dashboard from saved output files.")
    p.add_argument("--dir",   default=None, help="Portfolio output directory")
    p.add_argument("--date",  default=None, help="Trade date YYYY-MM-DD (auto-detected if omitted)")
    p.add_argument("--excel", default=None, help="Path to portfolio_YYYYMMDD.xlsx (overrides --dir)")
    p.add_argument("--no-browser", action="store_true", help="Write dashboard but don't open browser")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Directory / file discovery
# ---------------------------------------------------------------------------

def _find_output_dir(args) -> str:
    if args.dir:
        return os.path.expanduser(args.dir)
    if args.excel:
        return os.path.dirname(os.path.abspath(args.excel))
    # Default from config
    from tradingagents.default_config import DEFAULT_CONFIG
    results_dir = DEFAULT_CONFIG.get("results_dir", os.path.expanduser("~/.tradingagents/logs"))
    portfolio_cfg = DEFAULT_CONFIG.get("portfolio", {})
    return portfolio_cfg.get("output_dir") or os.path.join(results_dir, "portfolio")


def _find_excel(output_dir: str, args) -> str | None:
    if args.excel:
        return os.path.expanduser(args.excel)
    # Most recent portfolio_*.xlsx in the directory
    pattern = os.path.join(output_dir, "portfolio_*.xlsx")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return files[0] if files else None


def _infer_date(excel_path: str | None, args) -> str:
    if args.date:
        return args.date
    if excel_path:
        m = re.search(r"portfolio_(\d{8})", os.path.basename(excel_path))
        if m:
            raw = m.group(1)
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return str(date.today())


def _find_reports(output_dir: str, trade_date: str) -> dict[str, str]:
    """Return {ticker: markdown_content} for all saved report files."""
    date_tag = trade_date.replace("-", "")
    reports = {}
    pattern = os.path.join(output_dir, f"*_report_{date_tag}.md")
    for path in sorted(glob.glob(pattern)):
        m = re.match(r"([A-Z0-9\.\-]+)_report_\d{8}\.md", os.path.basename(path))
        if m:
            ticker = m.group(1)
            try:
                with open(path, encoding="utf-8") as f:
                    reports[ticker] = f.read()
            except Exception:
                pass
    return reports


# ---------------------------------------------------------------------------
# Excel readers
# ---------------------------------------------------------------------------

def _read_excel(excel_path: str) -> dict:
    """Read portfolio Excel workbook. Returns dict with keys: screener, portfolio, rebalance."""
    try:
        import pandas as pd
    except ImportError:
        print("  ✗  pandas not installed — Excel data unavailable")
        return {}

    result = {}

    try:
        xl = pd.ExcelFile(excel_path, engine="openpyxl")
    except Exception as e:
        print(f"  ✗  Could not open Excel: {e}")
        return {}

    # ── Screener Results sheet ────────────────────────────────────────
    if "Screener Results" in xl.sheet_names:
        try:
            df = xl.parse("Screener Results")
            passed, filtered = [], []
            for _, row in df.iterrows():
                d = {
                    "ticker":              str(row.get("Ticker", "")).strip(),
                    "sector":              str(row.get("Sector", "") or ""),
                    "market_cap":          _safe_float(row.get("Market Cap ($B)")),
                    "composite_score":     _safe_float(row.get("Composite Score")),
                    "composite_rank":      _safe_int(row.get("Composite Rank")),
                    "quality_score":       _safe_float(row.get("Quality Score")),
                    "growth_score":        _safe_float(row.get("Growth Score")),
                    "valuation_score":     _safe_float(row.get("Valuation Score")),
                    "momentum_score":      _safe_float(row.get("Momentum Score")),
                    "analyst_score":       _safe_float(row.get("Analyst Score")),
                    "passed_hard_filters": str(row.get("Passed Filters","")).strip() == "Yes",
                    "filter_reason":       str(row.get("Filter Reason","") or "").strip() or None,
                }
                if not d["ticker"] or d["ticker"] == "nan":
                    continue
                if d["passed_hard_filters"]:
                    passed.append(d)
                else:
                    filtered.append(d)
            result["screener"] = {
                "n_universe": len(passed) + len(filtered),
                "n_passed":   len(passed),
                "n_filtered": len(filtered),
                "passed":     passed,
                "filtered":   filtered,
            }
        except Exception as e:
            print(f"  ⚠  Screener sheet parse error: {e}")

    # ── Portfolio View sheet ──────────────────────────────────────────
    if "Portfolio View" in xl.sheet_names:
        try:
            df = xl.parse("Portfolio View")
            holdings = []
            cash_weight = 0.0
            for _, row in df.iterrows():
                ticker = str(row.get("Ticker","")).strip()
                if not ticker or ticker == "nan":
                    continue
                if ticker == "CASH":
                    cash_weight = (row.get("Target Weight (%)", 0) or 0) / 100
                    continue
                holdings.append({
                    "ticker":             ticker,
                    "rating":             str(row.get("Rating","") or "—"),
                    "target_weight":      (row.get("Target Weight (%)", 0) or 0) / 100,
                    "conviction":         str(row.get("Conviction","") or "—"),
                    "price_target":       _safe_float(row.get("Price Target")),
                    "time_horizon":       str(row.get("Time Horizon","") or ""),
                    "investment_thesis":  str(row.get("Investment Thesis","") or ""),
                    "overweight_reason":  str(row.get("Overweight Reason","") or ""),
                    "underweight_reason": str(row.get("Underweight Reason","") or ""),
                })
            result["portfolio"] = {
                "holdings":    holdings,
                "cash_weight": cash_weight,
            }
        except Exception as e:
            print(f"  ⚠  Portfolio sheet parse error: {e}")

    # ── Sector Exposure sheet ─────────────────────────────────────────
    if "Sector Exposure" in xl.sheet_names and "portfolio" in result:
        try:
            df = xl.parse("Sector Exposure")
            sw = {}
            for _, row in df.iterrows():
                sector = str(row.get("Sector","")).strip()
                w      = _safe_float(row.get("Target Weight (%)"))
                if sector and sector != "nan" and w is not None:
                    sw[sector] = w / 100
            result["portfolio"]["sector_weights"] = sw
        except Exception:
            pass

    # ── Rebalance Trades sheet ────────────────────────────────────────
    if "Rebalance Trades" in xl.sheet_names:
        try:
            df = xl.parse("Rebalance Trades")
            trades = []
            for _, row in df.iterrows():
                ticker = str(row.get("Ticker","")).strip()
                if not ticker or ticker == "nan":
                    continue
                trades.append({
                    "ticker":         ticker,
                    "action":         str(row.get("Action","") or "Hold"),
                    "current_weight": (row.get("Current Weight (%)", 0) or 0) / 100,
                    "target_weight":  (row.get("Target Weight (%)", 0) or 0) / 100,
                    "weight_delta":   (row.get("Δ Weight (%)", 0) or 0) / 100,
                    "drift_pct":      _safe_float(row.get("Drift (%)")) or 0,
                    "priority":       str(row.get("Priority","") or "—"),
                    "rationale":      str(row.get("Rationale","") or ""),
                })
            result["rebalance"] = {
                "trades":              trades,
                "new_positions":       [],
                "exited_positions":    [],
                "rebalance_turnover":  None,
                "summary":             "(Loaded from saved Excel — see rebalance memo for full narrative)",
                "macro_context":       "",
            }
        except Exception as e:
            print(f"  ⚠  Rebalance sheet parse error: {e}")

    return result


# ---------------------------------------------------------------------------
# Rebalance memo reader (picks up narrative missing from Excel)
# ---------------------------------------------------------------------------

def _read_rebalance_memo(output_dir: str, trade_date: str) -> dict:
    date_tag = trade_date.replace("-", "")
    path = os.path.join(output_dir, f"rebalance_memo_{date_tag}.md")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        # Extract turnover from "Estimated Turnover: 12.3%"
        turnover = None
        m = re.search(r"Estimated Turnover[:\*\s]+([0-9.]+)%", content)
        if m:
            turnover = float(m.group(1)) / 100
        # Extract summary paragraph (first paragraph after "## Rebalance")
        summary = ""
        m = re.search(r"\*\*Summary\*\*[:]\s*(.+?)(?:\n\n|\Z)", content, re.S)
        if m:
            summary = m.group(1).strip()
        macro = ""
        m = re.search(r"\*\*Macro Context\*\*[:]\s*(.+?)(?:\n\n|\Z)", content, re.S)
        if m:
            macro = m.group(1).strip()
        return {"rebalance_turnover": turnover, "summary": summary, "macro_context": macro}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if f != f else f   # NaN check
    except Exception:
        return None


def _safe_int(v) -> int | None:
    try:
        return int(v)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = _parse_args()

    output_dir = _find_output_dir(args)
    print(f"\n📂  Output directory : {output_dir}")

    excel_path = _find_excel(output_dir, args)
    trade_date = _infer_date(excel_path, args)
    print(f"📅  Trade date       : {trade_date}")
    print(f"📊  Excel file       : {excel_path or '(not found — will use report files only)'}")

    # ── Load data ────────────────────────────────────────────────────
    print("\nReading output files …")

    excel_data = _read_excel(excel_path) if excel_path else {}
    reports    = _find_reports(output_dir, trade_date)
    print(f"  ✓  {len(reports)} ticker report(s) found")

    # Build analysis tickers from reports + portfolio sheet
    tickers_done = set(reports.keys())
    portfolio_tickers = {h["ticker"] for h in excel_data.get("portfolio", {}).get("holdings", [])}
    screener_passed   = {r["ticker"] for r in excel_data.get("screener", {}).get("passed", [])}
    all_candidate_tickers = tickers_done | portfolio_tickers | screener_passed

    analysis_tickers = {}
    for sym in sorted(all_candidate_tickers):
        if sym in tickers_done:
            analysis_tickers[sym] = {
                "status":    "complete",
                "rating":    _extract_rating(reports.get(sym, "")),
                "elapsed":   None,
                "report_md": reports.get(sym, ""),
            }
        else:
            analysis_tickers[sym] = {"status": "pending"}

    n_done = sum(1 for v in analysis_tickers.values() if v["status"] == "complete")
    print(f"  ✓  {n_done}/{len(analysis_tickers)} tickers with completed reports")

    # Merge rebalance memo narrative into Excel data
    if "rebalance" in excel_data:
        memo_extras = _read_rebalance_memo(output_dir, trade_date)
        excel_data["rebalance"].update(memo_extras)

    # Determine stage
    if excel_data.get("portfolio"):
        stage = "complete" if not n_done < len(analysis_tickers) else "portfolio"
    elif n_done > 0:
        stage = "analysis"
    elif excel_data.get("screener"):
        stage = "screener_done"
    else:
        stage = "initializing"

    # ── Build dashboard data ──────────────────────────────────────────
    from tradingagents.portfolio.dashboard import PortfolioDashboard
    from datetime import datetime

    dash = PortfolioDashboard(output_dir=output_dir, trade_date=trade_date)

    # Directly inject all data (bypass the typed update methods)
    dash._data["meta"]["stage"]            = stage
    dash._data["meta"]["refresh_interval"] = 0    # static — no auto-refresh
    dash._data["meta"]["generated_at"]     = datetime.now().isoformat(timespec="seconds")

    if excel_data.get("screener"):
        dash._data["screener"] = excel_data["screener"]

    dash._data["analysis"] = {
        "total":    len(analysis_tickers),
        "complete": n_done,
        "tickers":  analysis_tickers,
    }

    if excel_data.get("portfolio"):
        port = excel_data["portfolio"]
        dash._data["portfolio"] = {
            **port,
            "construction_rationale": "(Loaded from saved Excel)",
            "top_overweights":        "",
            "top_underweights":       "",
            "methodology":            "Momentum + Quality",
        }

    if excel_data.get("rebalance"):
        dash._data["rebalance"] = excel_data["rebalance"]

    # ── Correlation matrix from portfolio holdings ────────────────────
    holding_tickers = [h["ticker"] for h in excel_data.get("portfolio", {}).get("holdings", [])]
    if len(holding_tickers) >= 2:
        print(f"  Computing return correlations for {len(holding_tickers)} holdings …")
        try:
            from tradingagents.portfolio.correlation import compute_correlation_matrix
            corr_data = compute_correlation_matrix(holding_tickers, trade_date)
            if corr_data:
                dash._data["correlation"] = corr_data
                print(f"  ✓  Correlation matrix: {len(corr_data['tickers'])} tickers · {corr_data['n_obs']} trading days")
            else:
                print("  ⚠  Correlation matrix: insufficient price data")
        except Exception as e:
            print(f"  ⚠  Correlation matrix failed: {e}")

    dash._write()

    print(f"\n✅  Dashboard written → {dash.path}")
    print(f"    Stage            : {stage}")
    print(f"    Screener tickers : {excel_data.get('screener', {}).get('n_universe', 0)}")
    print(f"    Reports loaded   : {n_done}")
    print(f"    Portfolio holds  : {len(excel_data.get('portfolio', {}).get('holdings', []))}")

    if not args.no_browser:
        webbrowser.open(f"file://{os.path.abspath(dash.path)}")
        print("    Browser opened   : ✓")
    else:
        print(f"    Open manually    : file://{os.path.abspath(dash.path)}")

    print()


def _extract_rating(md: str) -> str:
    for line in md.splitlines():
        if line.strip().startswith("**Rating**:"):
            return line.split(":", 1)[-1].strip()
    return "—"


if __name__ == "__main__":
    main()
