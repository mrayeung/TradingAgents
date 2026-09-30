"""
Oasis Trading Desk — Backtesting Engine
========================================
Reads strategy trigger conditions from playbook_templates.yaml,
pulls historical OHLCV + earnings data, simulates entry/exit logic,
and outputs a BacktestResult with equity curve, trade log, and summary stats.

Usage:
    python backtest_engine.py \
        --template "Earnings Gap Hold" \
        --tickers AAPL MSFT NVDA META \
        --start 2024-01-01 --end 2026-09-24 \
        --capital 50000 --risk-pct 0.75

Dependencies:
    pip install yfinance pandas numpy pyyaml finnhub-python
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import yaml
import yfinance as yf

# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimulatedTrade:
    ticker:         str
    entry_date:     date
    exit_date:      date | None
    entry_price:    float
    stop_price:     float
    target_price:   float
    exit_price:     float | None
    exit_reason:    Literal["target", "stop", "time", "manual"] | None
    shares:         int
    pnl_dollars:    float | None
    pnl_pct:        float | None
    r_multiple:     float | None          # 1R = initial risk per share × shares
    setup_score:    int
    holding_days:   int | None
    setup_name:     str
    trigger_details: dict = field(default_factory=dict)


@dataclass
class BacktestResult:
    strategy_name:      str
    tickers:            list[str]
    start_date:         date
    end_date:           date
    starting_capital:   float
    ending_capital:     float
    total_return_pct:   float
    total_return_dollars: float
    trades:             list[SimulatedTrade]
    equity_curve:       pd.Series           # date-indexed portfolio value
    benchmark_return:   float | None        # SPY return over same period
    stats:              dict                # summary statistics dict


# ─────────────────────────────────────────────────────────────────────────────
# TRIGGER EVALUATORS
# Each strategy category has a dedicated evaluator that checks historical data
# for each trading day and returns a setup score (0–100) if triggered.
# ─────────────────────────────────────────────────────────────────────────────

class TriggerEvaluator:
    """Base class. Subclass per strategy category."""

    def __init__(self, template: dict, config: dict):
        self.template = template
        self.config = config

    def evaluate(
        self,
        ticker: str,
        date_: date,
        ohlcv: pd.DataFrame,
        earnings_df: pd.DataFrame | None = None,
    ) -> tuple[bool, int, dict]:
        """
        Returns (triggered: bool, score: int 0-100, details: dict).
        Override per strategy.
        """
        raise NotImplementedError


class EarningsGapHoldEvaluator(TriggerEvaluator):
    """
    Earnings Gap Hold trigger:
      1. Earnings released yesterday (beat EPS + revenue, guidance raised)
      2. Today's open is 5%+ above prior close
      3. Gap holds (today's low > prior close) for 30 min (approximated via daily data)
      4. Volume > 2× 20-day average
    """

    def evaluate(
        self,
        ticker: str,
        date_: date,
        ohlcv: pd.DataFrame,
        earnings_df: pd.DataFrame | None = None,
    ) -> tuple[bool, int, dict]:

        if date_ not in ohlcv.index:
            return False, 0, {}

        try:
            today     = ohlcv.loc[date_]
            prev_date = ohlcv.index[ohlcv.index.get_loc(date_) - 1]
            prev      = ohlcv.loc[prev_date]
            hist_20   = ohlcv.iloc[max(0, ohlcv.index.get_loc(date_) - 20) : ohlcv.index.get_loc(date_)]
        except (KeyError, IndexError):
            return False, 0, {}

        score   = 0
        details = {}

        # 1. Gap magnitude (30 pts)
        gap_pct = (today["Open"] - prev["Close"]) / prev["Close"] * 100
        details["gap_pct"] = round(gap_pct, 2)
        if gap_pct >= 15:     score += 30
        elif gap_pct >= 10:   score += 22
        elif gap_pct >= 7:    score += 16
        elif gap_pct >= 5:    score += 10
        else:
            return False, 0, {"gap_pct": gap_pct, "fail": "gap_below_5pct"}

        # 2. Gap holds (today low > prior close) — gap-and-go, not gap-and-fill (20 pts)
        gap_holds = today["Low"] > prev["Close"] * 0.99   # 1% tolerance
        details["gap_holds"] = gap_holds
        if gap_holds:
            score += 20
        else:
            # Gap fill → not a gap-hold setup → skip this day's entry
            return False, 0, {**details, "fail": "gap_filled"}

        # 3. Volume (20 pts)
        avg_vol = hist_20["Volume"].mean() if len(hist_20) >= 5 else today["Volume"]
        vol_ratio = today["Volume"] / avg_vol if avg_vol > 0 else 1
        details["volume_ratio"] = round(vol_ratio, 2)
        if vol_ratio >= 3.0:   score += 20
        elif vol_ratio >= 2.0: score += 15
        elif vol_ratio >= 1.5: score += 8

        # 4. Earnings data presence (20 pts) — use earnings_df if available
        if earnings_df is not None and not earnings_df.empty:
            # Look for earnings release within last 2 trading days
            window_start = prev_date - timedelta(days=3)
            recent_earnings = earnings_df[
                (earnings_df.index >= str(window_start)) &
                (earnings_df.index <= str(prev_date))
            ]
            if not recent_earnings.empty:
                score += 20
                details["earnings_confirmed"] = True

                # Bonus: surprise magnitude (10 pts)
                if "epsActual" in recent_earnings.columns and "epsEstimate" in recent_earnings.columns:
                    row = recent_earnings.iloc[-1]
                    if pd.notna(row["epsActual"]) and pd.notna(row["epsEstimate"]) and row["epsEstimate"] != 0:
                        surprise_pct = (row["epsActual"] - row["epsEstimate"]) / abs(row["epsEstimate"]) * 100
                        details["eps_surprise_pct"] = round(surprise_pct, 1)
                        if surprise_pct >= 20:  score += 10
                        elif surprise_pct >= 10: score += 6
                        elif surprise_pct >= 5:  score += 3
        else:
            # No earnings data — proxy: large gap on high volume is likely earnings
            score += 10
            details["earnings_proxied"] = True

        triggered = score >= self.config.get("min_setup_score", 70)
        return triggered, min(score, 100), details


class MorningGapGoEvaluator(TriggerEvaluator):
    """Morning Gap & Go: gap 5%+ on catalyst, gap holds first 15 min."""

    def evaluate(self, ticker, date_, ohlcv, earnings_df=None):
        if date_ not in ohlcv.index:
            return False, 0, {}
        try:
            today   = ohlcv.loc[date_]
            prev    = ohlcv.iloc[ohlcv.index.get_loc(date_) - 1]
            hist_20 = ohlcv.iloc[max(0, ohlcv.index.get_loc(date_) - 20):ohlcv.index.get_loc(date_)]
        except (KeyError, IndexError):
            return False, 0, {}

        score   = 0
        details = {}
        gap_pct = (today["Open"] - prev["Close"]) / prev["Close"] * 100
        details["gap_pct"] = round(gap_pct, 2)

        if gap_pct < 5:
            return False, 0, {**details, "fail": "gap_below_5pct"}
        score += min(int((gap_pct - 5) / 2) * 5 + 15, 35)

        gap_holds = today["Low"] > prev["Close"] * 0.99
        details["gap_holds"] = gap_holds
        if not gap_holds:
            return False, 0, {**details, "fail": "gap_filled"}
        score += 20

        avg_vol   = hist_20["Volume"].mean() if len(hist_20) >= 5 else today["Volume"]
        vol_ratio = today["Volume"] / avg_vol if avg_vol > 0 else 1
        details["volume_ratio"] = round(vol_ratio, 2)
        if vol_ratio >= 2.5:   score += 25
        elif vol_ratio >= 2.0: score += 18
        elif vol_ratio >= 1.5: score += 10
        else:
            return False, 0, {**details, "fail": "low_volume"}

        triggered = score >= self.config.get("min_setup_score", 65)
        return triggered, min(score, 100), details


class BreakoutContinuationEvaluator(TriggerEvaluator):
    """Tight consolidation (5–20 days) then breakout on volume."""

    def evaluate(self, ticker, date_, ohlcv, earnings_df=None):
        idx = ohlcv.index.get_loc(date_) if date_ in ohlcv.index else -1
        if idx < 20:
            return False, 0, {}

        today  = ohlcv.iloc[idx]
        recent = ohlcv.iloc[idx - 20:idx]
        score  = 0
        details = {}

        # Find base: smallest 5–20 day range in recent window
        best_window = None
        for window_size in range(5, 21):
            window = ohlcv.iloc[idx - window_size:idx]
            high_  = window["High"].max()
            low_   = window["Low"].min()
            range_pct = (high_ - low_) / low_ * 100
            if range_pct <= 8:
                if best_window is None or range_pct < best_window[1]:
                    best_window = (window, range_pct, high_, low_, window_size)

        if best_window is None:
            return False, 0, {"fail": "no_tight_base"}

        base_window, range_pct, base_high, base_low, base_days = best_window
        details["base_days"] = base_days
        details["base_range_pct"] = round(range_pct, 2)

        breakout = today["Close"] > base_high * 1.005
        details["breakout"] = breakout
        if not breakout:
            return False, 0, {**details, "fail": "no_breakout"}

        score += 40   # tight base breakout

        avg_vol   = recent["Volume"].mean()
        vol_ratio = today["Volume"] / avg_vol if avg_vol > 0 else 1
        details["volume_ratio"] = round(vol_ratio, 2)
        if vol_ratio >= 2.0:   score += 30
        elif vol_ratio >= 1.5: score += 20
        elif vol_ratio >= 1.2: score += 10
        else:
            return False, 0, {**details, "fail": "low_volume_on_breakout"}

        score += max(0, 30 - int(range_pct * 3))   # tighter base = higher score

        triggered = score >= self.config.get("min_setup_score", 65)
        return triggered, min(score, 100), details


# ─────────────────────────────────────────────────────────────────────────────
# POSITION SIZING
# ─────────────────────────────────────────────────────────────────────────────

def calculate_shares(
    account_equity: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
    max_position_pct: float = 0.15,
) -> int:
    """
    Risk-based position sizing:
      shares = (account × risk_pct) / (entry - stop)
    Capped at max_position_pct of account value.
    """
    risk_dollars    = account_equity * (risk_pct / 100)
    risk_per_share  = abs(entry_price - stop_price)
    if risk_per_share <= 0:
        return 0
    shares = int(risk_dollars / risk_per_share)
    max_shares = int((account_equity * max_position_pct) / entry_price)
    return min(shares, max_shares)


# ─────────────────────────────────────────────────────────────────────────────
# STOP / TARGET COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def compute_stop(method: str, ohlcv: pd.DataFrame, date_: date, **kwargs) -> float:
    idx = ohlcv.index.get_loc(date_) if date_ in ohlcv.index else -1
    today = ohlcv.iloc[idx]
    prev  = ohlcv.iloc[idx - 1] if idx > 0 else today

    dispatch = {
        "below_premarket_low":   lambda: today["Low"] * 0.99,
        "below_gap_day_low":     lambda: today["Low"] * 0.995,
        "below_day_low":         lambda: today["Low"] * 0.99,
        "below_range_high":      lambda: kwargs.get("base_high", today["Low"]) * 0.99,
        "above_swing_high":      lambda: today["High"] * 1.01,  # for shorts
        "below_200ma":           lambda: ohlcv["Close"].iloc[max(0, idx-200):idx].mean() * 0.995,
    }
    fn = dispatch.get(method, lambda: today["Low"] * 0.98)
    return fn()


def compute_target(
    method: str,
    ohlcv: pd.DataFrame,
    date_: date,
    entry: float,
    stop: float,
    min_rr: float,
    **kwargs,
) -> float:
    risk = abs(entry - stop)
    idx  = ohlcv.index.get_loc(date_) if date_ in ohlcv.index else -1

    dispatch = {
        "prior_resistance":         lambda: ohlcv["High"].iloc[max(0, idx-60):idx].max(),
        "prior_all_time_high":      lambda: ohlcv["High"].iloc[:idx].max(),
        "measured_move":            lambda: entry + kwargs.get("base_height", risk * 2),
        "prior_close_before_event": lambda: ohlcv["Close"].iloc[max(0, idx-5)],
        "fixed_rr":                 lambda: entry + risk * min_rr,
    }
    fn = dispatch.get(method, lambda: entry + risk * min_rr)
    target = fn()
    # Ensure minimum R:R is respected
    min_target = entry + risk * min_rr
    return max(target, min_target)


# ─────────────────────────────────────────────────────────────────────────────
# TRADE SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

def simulate_trade(
    ticker:       str,
    entry_date:   date,
    entry_price:  float,
    stop_price:   float,
    target_price: float,
    shares:       int,
    ohlcv:        pd.DataFrame,
    max_hold_days: int,
    setup_name:   str,
    setup_score:  int,
    trigger_details: dict,
) -> SimulatedTrade:
    """
    Walks forward day by day after entry.
    Checks: stop hit → exit at stop; target hit → exit at target; max hold → exit at close.
    """
    risk_per_share = abs(entry_price - stop_price)
    trade_start_idx = ohlcv.index.get_loc(entry_date) if entry_date in ohlcv.index else None

    if trade_start_idx is None:
        return SimulatedTrade(
            ticker=ticker, entry_date=entry_date, exit_date=None,
            entry_price=entry_price, stop_price=stop_price, target_price=target_price,
            exit_price=None, exit_reason=None, shares=shares,
            pnl_dollars=None, pnl_pct=None, r_multiple=None,
            setup_score=setup_score, holding_days=None,
            setup_name=setup_name, trigger_details=trigger_details,
        )

    exit_price  = None
    exit_reason = None
    exit_date   = None

    for i in range(1, max_hold_days + 1):
        future_idx = trade_start_idx + i
        if future_idx >= len(ohlcv):
            # End of data
            exit_price  = ohlcv.iloc[-1]["Close"]
            exit_date   = ohlcv.index[-1]
            exit_reason = "time"
            break

        future_bar = ohlcv.iloc[future_idx]
        future_date_val = ohlcv.index[future_idx]

        # Stop hit (intraday low touches stop)
        if future_bar["Low"] <= stop_price:
            exit_price  = stop_price
            exit_date   = future_date_val
            exit_reason = "stop"
            break

        # Target hit (intraday high touches target)
        if future_bar["High"] >= target_price:
            exit_price  = target_price
            exit_date   = future_date_val
            exit_reason = "target"
            break

        # Max hold reached → exit at close
        if i == max_hold_days:
            exit_price  = future_bar["Close"]
            exit_date   = future_date_val
            exit_reason = "time"

    pnl_dollars = ((exit_price - entry_price) * shares) if exit_price else None
    pnl_pct     = ((exit_price - entry_price) / entry_price * 100) if exit_price else None
    r_multiple  = ((exit_price - entry_price) / risk_per_share) if (exit_price and risk_per_share > 0) else None
    holding_days = (exit_date - entry_date).days if exit_date else None

    return SimulatedTrade(
        ticker=ticker, entry_date=entry_date, exit_date=exit_date,
        entry_price=entry_price, stop_price=stop_price, target_price=target_price,
        exit_price=exit_price, exit_reason=exit_reason, shares=shares,
        pnl_dollars=round(pnl_dollars, 2) if pnl_dollars else None,
        pnl_pct=round(pnl_pct, 2) if pnl_pct else None,
        r_multiple=round(r_multiple, 2) if r_multiple else None,
        setup_score=setup_score, holding_days=holding_days,
        setup_name=setup_name, trigger_details=trigger_details,
    )


# ─────────────────────────────────────────────────────────────────────────────
# STATS COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def compute_stats(trades: list[SimulatedTrade], equity_curve: pd.Series) -> dict:
    completed = [t for t in trades if t.pnl_dollars is not None]
    if not completed:
        return {}

    wins  = [t for t in completed if t.r_multiple and t.r_multiple > 0]
    losses = [t for t in completed if t.r_multiple and t.r_multiple <= 0]

    win_rate      = len(wins) / len(completed) * 100 if completed else 0
    avg_win_r     = np.mean([t.r_multiple for t in wins]) if wins else 0
    avg_loss_r    = abs(np.mean([t.r_multiple for t in losses])) if losses else 0
    expectancy    = (win_rate / 100 * avg_win_r) - ((1 - win_rate / 100) * avg_loss_r)
    profit_factor = (
        sum(t.pnl_dollars for t in wins) / abs(sum(t.pnl_dollars for t in losses))
        if losses and sum(t.pnl_dollars for t in losses) != 0 else float("inf")
    )

    # Max drawdown
    peak = equity_curve.cummax()
    dd   = (equity_curve - peak) / peak * 100
    max_drawdown = dd.min()

    # Sharpe (annualized, assumes ~252 trading days)
    daily_returns = equity_curve.pct_change().dropna()
    sharpe = (daily_returns.mean() / daily_returns.std() * math.sqrt(252)) if daily_returns.std() > 0 else 0

    # Avg holding
    holding_days = [t.holding_days for t in completed if t.holding_days]
    avg_hold = np.mean(holding_days) if holding_days else 0

    # Consecutive win/loss streaks
    results = [1 if t.r_multiple and t.r_multiple > 0 else -1 for t in completed]
    max_consec_wins = max_consec_losses = cur_w = cur_l = 0
    for r in results:
        if r > 0:
            cur_w += 1; cur_l = 0
        else:
            cur_l += 1; cur_w = 0
        max_consec_wins   = max(max_consec_wins, cur_w)
        max_consec_losses = max(max_consec_losses, cur_l)

    return {
        "total_trades":           len(completed),
        "wins":                   len(wins),
        "losses":                 len(losses),
        "win_rate_pct":           round(win_rate, 1),
        "avg_winner_r":           round(avg_win_r, 2),
        "avg_loser_r":            round(avg_loss_r, 2),
        "expectancy_r":           round(expectancy, 2),
        "profit_factor":          round(profit_factor, 2),
        "max_drawdown_pct":       round(max_drawdown, 2),
        "sharpe_ratio":           round(sharpe, 2),
        "avg_hold_days":          round(avg_hold, 1),
        "max_consecutive_wins":   max_consec_wins,
        "max_consecutive_losses": max_consec_losses,
        "best_trade_dollars":     round(max((t.pnl_dollars or 0) for t in completed), 2),
        "worst_trade_dollars":    round(min((t.pnl_dollars or 0) for t in completed), 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATOR REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

EVALUATOR_MAP: dict[str, type[TriggerEvaluator]] = {
    "Earnings Gap Hold":       EarningsGapHoldEvaluator,
    "Morning Gap & Go":        MorningGapGoEvaluator,
    "Breakout Continuation":   BreakoutContinuationEvaluator,
    # Add more as implemented:
    # "Sympathy Selloff Reversal": SympathyReversalEvaluator,
    # "VWAP Reclaim":              VWAPReclaimEvaluator,
    # "News Catalyst Momentum":    NewsCatalystEvaluator,
    # "RSI Exhaustion Short":      RSIExhaustionEvaluator,
    # "Pre-Event Straddle":        PreEventStraddleEvaluator,
}


# ─────────────────────────────────────────────────────────────────────────────
# MAIN BACKTEST RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def load_template(template_name: str, templates_path: str = "playbook_templates.yaml") -> dict:
    with open(templates_path) as f:
        templates = yaml.safe_load(f)
    for t in templates:
        if t["setup_name"] == template_name:
            return t
    raise ValueError(f"Template '{template_name}' not found in {templates_path}")


def run_backtest(
    template_name:      str,
    tickers:            list[str],
    start:              date,
    end:                date,
    starting_capital:   float = 50_000,
    risk_pct:           float = 0.75,
    max_position_pct:   float = 0.15,
    min_setup_score:    int   = 70,
    max_concurrent:     int   = 2,
    regime_filter:      str   = "any",      # "risk_on_only" | "any"
    benchmark_ticker:   str   = "SPY",
    templates_path:     str   = "playbook_templates.yaml",
) -> BacktestResult:

    template  = load_template(template_name, templates_path)
    config    = {"min_setup_score": min_setup_score}
    evaluator = EVALUATOR_MAP.get(template_name)

    if evaluator is None:
        raise NotImplementedError(
            f"No evaluator implemented for '{template_name}'. "
            f"Available: {list(EVALUATOR_MAP.keys())}"
        )

    ev = evaluator(template, config)

    # Pull OHLCV for all tickers + benchmark
    print(f"[backtest] Fetching data for {tickers + [benchmark_ticker]}…")
    raw_data: dict[str, pd.DataFrame] = {}
    for ticker in tickers + [benchmark_ticker]:
        df = yf.download(ticker, start=start - timedelta(days=60), end=end + timedelta(days=5),
                         auto_adjust=True, progress=False)
        df.index = pd.to_datetime(df.index).date
        raw_data[ticker] = df

    # Pull earnings data via yfinance (limited — upgrade to Finnhub for production)
    earnings_data: dict[str, pd.DataFrame | None] = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            eq = stock.earnings_dates
            if eq is not None:
                eq.index = pd.to_datetime(eq.index).date
            earnings_data[ticker] = eq
        except Exception:
            earnings_data[ticker] = None

    # Build trading day index
    if not raw_data[tickers[0]].empty:
        all_dates = [d for d in raw_data[tickers[0]].index if start <= d <= end]
    else:
        all_dates = []

    # Simulate
    equity          = starting_capital
    equity_series   = {}
    all_trades:     list[SimulatedTrade] = []
    open_positions: list[SimulatedTrade] = []   # track concurrent positions

    for day in all_dates:
        # Close any positions that have exited by today
        still_open = []
        for pos in open_positions:
            if pos.exit_date and pos.exit_date <= day:
                equity += pos.pnl_dollars or 0
            else:
                still_open.append(pos)
        open_positions = still_open

        equity_series[day] = equity

        # Check concurrent position limit
        if len(open_positions) >= max_concurrent:
            continue

        # Scan tickers for setups today
        for ticker in tickers:
            ohlcv = raw_data.get(ticker)
            if ohlcv is None or ohlcv.empty or day not in ohlcv.index:
                continue

            triggered, score, details = ev.evaluate(
                ticker, day, ohlcv, earnings_data.get(ticker)
            )

            if not triggered or score < min_setup_score:
                continue

            today_bar   = ohlcv.loc[day]
            entry_price = today_bar["Open"] * 1.001   # slight slippage

            stop_method   = template.get("stop_rule", "below_premarket_low")
            target_method = template.get("target_rule", "prior_resistance")

            stop_price   = compute_stop(stop_method, ohlcv, day)
            target_price = compute_target(
                target_method, ohlcv, day,
                entry=entry_price, stop=stop_price,
                min_rr=template.get("min_rr", 2.0),
            )

            if stop_price >= entry_price:
                continue

            shares = calculate_shares(
                account_equity=equity,
                risk_pct=risk_pct,
                entry_price=entry_price,
                stop_price=stop_price,
                max_position_pct=max_position_pct,
            )
            if shares <= 0:
                continue

            # Parse max hold from template holding_period string
            hold_str = template.get("holding_period", "2-5 days")
            try:
                max_hold = int(hold_str.split("-")[-1].split()[0])
            except (ValueError, IndexError):
                max_hold = 5

            trade = simulate_trade(
                ticker=ticker, entry_date=day,
                entry_price=entry_price, stop_price=stop_price,
                target_price=target_price, shares=shares,
                ohlcv=ohlcv, max_hold_days=max_hold,
                setup_name=template_name, setup_score=score,
                trigger_details=details,
            )

            all_trades.append(trade)
            open_positions.append(trade)

            if len(open_positions) >= max_concurrent:
                break   # filled all slots for today

    # Close any remaining open positions at last price
    for pos in open_positions:
        ticker = pos.ticker
        ohlcv  = raw_data.get(ticker)
        if ohlcv is not None and not ohlcv.empty:
            last_close    = ohlcv.iloc[-1]["Close"]
            pos.exit_price  = last_close
            pos.exit_date   = ohlcv.index[-1]
            pos.exit_reason = "time"
            pnl = (last_close - pos.entry_price) * pos.shares
            pos.pnl_dollars = round(pnl, 2)
            pos.pnl_pct     = round((last_close - pos.entry_price) / pos.entry_price * 100, 2)
            risk_per_share  = abs(pos.entry_price - pos.stop_price)
            pos.r_multiple  = round((last_close - pos.entry_price) / risk_per_share, 2) if risk_per_share > 0 else 0
            equity += pnl

    equity_series[end] = equity
    equity_curve = pd.Series(equity_series).sort_index()

    # Benchmark
    bm_data = raw_data.get(benchmark_ticker)
    if bm_data is not None and not bm_data.empty:
        bm_start = bm_data[bm_data.index >= start]
        bm_end_  = bm_data[bm_data.index <= end]
        if not bm_start.empty and not bm_end_.empty:
            bm_return = (bm_end_.iloc[-1]["Close"] - bm_start.iloc[0]["Open"]) / bm_start.iloc[0]["Open"] * 100
        else:
            bm_return = None
    else:
        bm_return = None

    total_return_dollars = equity - starting_capital
    total_return_pct     = total_return_dollars / starting_capital * 100
    stats = compute_stats(all_trades, equity_curve)

    return BacktestResult(
        strategy_name=template_name,
        tickers=tickers,
        start_date=start,
        end_date=end,
        starting_capital=starting_capital,
        ending_capital=round(equity, 2),
        total_return_pct=round(total_return_pct, 2),
        total_return_dollars=round(total_return_dollars, 2),
        trades=all_trades,
        equity_curve=equity_curve,
        benchmark_return=round(bm_return, 2) if bm_return else None,
        stats=stats,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def print_results(result: BacktestResult) -> None:
    s = result.stats
    alpha = (result.total_return_pct - result.benchmark_return) if result.benchmark_return else None

    print(f"\n{'='*60}")
    print(f"  BACKTEST: {result.strategy_name}")
    print(f"  Tickers : {', '.join(result.tickers)}")
    print(f"  Period  : {result.start_date} → {result.end_date}")
    print(f"{'='*60}")
    print(f"  Starting capital : ${result.starting_capital:>12,.2f}")
    print(f"  Ending capital   : ${result.ending_capital:>12,.2f}")
    print(f"  Total return     : {result.total_return_pct:>+8.1f}%  (${result.total_return_dollars:+,.0f})")
    if alpha is not None:
        print(f"  vs {result.benchmark_return:+.1f}% benchmark:  α = {alpha:+.1f}%")
    print(f"{'─'*60}")
    print(f"  Trades           : {s.get('total_trades', 0)}")
    print(f"  Win Rate         : {s.get('win_rate_pct', 0):.1f}%")
    print(f"  Avg Winner       : +{s.get('avg_winner_r', 0):.2f}R")
    print(f"  Avg Loser        : -{s.get('avg_loser_r', 0):.2f}R")
    print(f"  Expectancy       : {s.get('expectancy_r', 0):+.2f}R / trade")
    print(f"  Profit Factor    : {s.get('profit_factor', 0):.2f}")
    print(f"  Max Drawdown     : {s.get('max_drawdown_pct', 0):.1f}%")
    print(f"  Sharpe Ratio     : {s.get('sharpe_ratio', 0):.2f}")
    print(f"  Avg Hold         : {s.get('avg_hold_days', 0):.1f} days")
    print(f"  Best trade       : ${s.get('best_trade_dollars', 0):+,.0f}")
    print(f"  Worst trade      : ${s.get('worst_trade_dollars', 0):+,.0f}")
    print(f"{'─'*60}")

    print(f"\n  Trade Log ({min(10, len(result.trades))} of {len(result.trades)}):")
    print(f"  {'Date':<12} {'Ticker':<6} {'Entry':>8} {'Stop':>8} {'Target':>8} {'Exit':>8} {'P&L':>8} {'R':>6} {'Score':>5}")
    for t in result.trades[:10]:
        pnl_str = f"${t.pnl_dollars:+,.0f}" if t.pnl_dollars else "open"
        r_str   = f"{t.r_multiple:+.1f}R"   if t.r_multiple  else "—"
        print(f"  {str(t.entry_date):<12} {t.ticker:<6} "
              f"${t.entry_price:>7.2f} ${t.stop_price:>7.2f} ${t.target_price:>7.2f} "
              f"${t.exit_price or 0:>7.2f} {pnl_str:>8} {r_str:>6} {t.setup_score:>5}")


def main():
    parser = argparse.ArgumentParser(description="Oasis Backtesting Engine")
    parser.add_argument("--template",   default="Earnings Gap Hold")
    parser.add_argument("--tickers",    nargs="+", default=["AAPL", "MSFT", "NVDA", "META"])
    parser.add_argument("--start",      default="2024-01-01")
    parser.add_argument("--end",        default="2026-09-24")
    parser.add_argument("--capital",    type=float, default=50_000)
    parser.add_argument("--risk-pct",   type=float, default=0.75, dest="risk_pct")
    parser.add_argument("--min-score",  type=int,   default=70,   dest="min_score")
    parser.add_argument("--concurrent", type=int,   default=2)
    parser.add_argument("--benchmark",  default="SPY")
    parser.add_argument("--output",     default=None, help="Save results to JSON file")
    parser.add_argument("--templates-path", default="trading_desk/playbook_templates.yaml")
    args = parser.parse_args()

    result = run_backtest(
        template_name    = args.template,
        tickers          = args.tickers,
        start            = date.fromisoformat(args.start),
        end              = date.fromisoformat(args.end),
        starting_capital = args.capital,
        risk_pct         = args.risk_pct,
        min_setup_score  = args.min_score,
        max_concurrent   = args.concurrent,
        benchmark_ticker = args.benchmark,
        templates_path   = args.templates_path,
    )

    print_results(result)

    if args.output:
        out = {
            "strategy":          result.strategy_name,
            "tickers":           result.tickers,
            "period":            f"{result.start_date} → {result.end_date}",
            "total_return_pct":  result.total_return_pct,
            "benchmark_return":  result.benchmark_return,
            "stats":             result.stats,
            "trades": [
                {
                    "ticker":      t.ticker,
                    "entry_date":  str(t.entry_date),
                    "exit_date":   str(t.exit_date),
                    "entry_price": t.entry_price,
                    "exit_price":  t.exit_price,
                    "exit_reason": t.exit_reason,
                    "pnl_dollars": t.pnl_dollars,
                    "r_multiple":  t.r_multiple,
                    "setup_score": t.setup_score,
                    "holding_days": t.holding_days,
                }
                for t in result.trades
            ],
        }
        Path(args.output).write_text(json.dumps(out, indent=2))
        print(f"\n  Results saved → {args.output}")


if __name__ == "__main__":
    main()
