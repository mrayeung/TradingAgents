"""Markov 2.0 regime analysis exposed as an agent tool.

Wraps `tradingagents.regime.analyze` so the Market Analyst (and any other agent)
can request a deterministic Bull/Bear/Sideways regime read, a directional signal,
and a readiness flag for a ticker. Research tooling only — not investment advice.
"""

from datetime import datetime, timedelta
from typing import Annotated

import numpy as np
from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.regime import MarkovConfig, STATE_NAMES, analyze


def _parse_ohlc(raw: str):
    """Parse the vendor's get_stock_data CSV (``#`` comment header + table) into
    close/high/low arrays. Tolerant of column ordering and missing High/Low."""
    lines = [ln for ln in raw.splitlines() if ln and not ln.startswith("#")]
    if not lines:
        return np.array([]), None, None
    header = [h.strip().lower() for h in lines[0].split(",")]
    try:
        ci = header.index("close")
    except ValueError:
        return np.array([]), None, None
    hi = header.index("high") if "high" in header else None
    li = header.index("low") if "low" in header else None
    closes, highs, lows = [], [], []
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) <= ci:
            continue
        try:
            closes.append(float(parts[ci]))
            if hi is not None and li is not None:
                highs.append(float(parts[hi]))
                lows.append(float(parts[li]))
        except (ValueError, IndexError):
            continue
    c = np.array(closes, dtype=float)
    h = np.array(highs, dtype=float) if highs and len(highs) == len(closes) else None
    l = np.array(lows, dtype=float) if lows and len(lows) == len(closes) else None
    return c, h, l


def _reco_bias(res) -> str:
    """Map the Markov 2.0 calculation to an explicit, extractable recommendation
    aligned with the engine's 5-tier rating language."""
    if not res.ready:
        return "NEUTRAL — data not ready (insufficient history); no quantitative tilt"
    if not res.has_edge or res.position == 0:
        return "NEUTRAL — no quantitative edge over the base rate; do not tilt on this"
    if res.position > 0:
        return "OVERWEIGHT bias — quantitative regime edge favors long over the horizon"
    return "UNDERWEIGHT bias — quantitative regime edge favors reducing/short over the horizon"


def _format_report(symbol: str, curr_date: str, res, cfg: MarkovConfig) -> str:
    P = res.P_stride
    diag_stride = float(np.diag(res.P_stride).mean())
    diag_legacy = float(np.diag(res.P_overlap).mean())

    def row(r):
        return f"{P[r,0]*100:3.0f}%  {P[r,1]*100:3.0f}%  {P[r,2]*100:3.0f}%"

    h = res.horizon_bars  # one matrix step = one stride ≈ this many trading days (daily bars)
    f1 = res.forecast[0] if res.forecast else None

    lines = [
        f"## Markov 2.0 Regime Analysis — {symbol} (as of {curr_date})",
        "",
        f"### Quantitative recommendation: {_reco_bias(res)}",
        "",
        f"- **Current regime:** {res.regime_name}",
        f"- **Projection horizon:** ~{h} trading days (one matrix step). The edge lives "
        f"around this horizon and fades to zero beyond ~2 steps.",
    ]
    if f1:
        lines.append(
            f"- **Projected regime probabilities over the next ~{h} trading days** "
            f"(from the current {res.regime_name} state): "
            f"BULL {f1['p_bull']*100:.0f}% · SIDE {f1['p_side']*100:.0f}% · "
            f"BEAR {f1['p_bear']*100:.0f}%"
        )
    lines += [
        f"- **Signal** P(bull) − P(bear) over the horizon: **{res.signal:+.3f}** "
        f"(sign = direction, magnitude = conviction)",
        f"- **Edge vs base rate:** {res.edge:+.3f} ({res.edge_tag}) — the de-biased "
        f"signal after removing the long-run tilt; near zero means the projection is just "
        f"repeating the base rate, i.e. NO usable edge.",
        f"- **Readiness:** {'READY' if res.ready else 'NOT READY'} "
        f"(labels {'PASS' if res.verify_ok else 'FAIL'}, min {res.min_samples} "
        f"stride samples/state; need {cfg.ready_min_samples})",
        f"- **Recommended action ({cfg.mode} mode):** {res.action}",
        f"- **Position:** {res.position_label}",
        "",
        f"### Forward projection from the current {res.regime_name} state (edge decay)",
        "```",
        "horizon      BULL  SIDE  BEAR   signal    edge",
    ]
    for f in res.forecast:
        lines.append(
            f"~{f['bars']:>3}d      {f['p_bull']*100:4.0f}% {f['p_side']*100:4.0f}% "
            f"{f['p_bear']*100:4.0f}%   {f['signal']:+.3f}  {f['edge']:+.3f}"
        )
    lines += [
        "```",
        "_The edge column shrinking toward 0 as the horizon grows confirms the signal "
        "is short-horizon; do not act on multi-step-out projections._",
        "",
        "### Transition matrix (stride-sampled, statistically honest)",
        "```",
        "from \\ to   BEAR  SIDE  BULL",
        f"BEAR       {row(0)}",
        f"SIDE       {row(1)}",
        f"BULL       {row(2)}",
        "```",
        f"- Long-run mix (stationary): BEAR {res.stationary[0]*100:.0f}% · "
        f"SIDE {res.stationary[1]*100:.0f}% · BULL {res.stationary[2]*100:.0f}%",
        f"- Stickiness check: stride diagonal {diag_stride*100:.0f}% vs "
        f"overlapping (legacy) {diag_legacy*100:.0f}%. The legacy figure is inflated "
        f"by autocorrelation; only the stride matrix above is trustworthy.",
        "",
        "_Interpretation: treat this as a regime/timing overlay, not a stock-pick. "
        "If NOT READY or edge is 'none', do not lean on this signal._",
    ]
    return "\n".join(lines)


def compute_regime_report(
    symbol: str,
    curr_date: str,
    lookback_days: int = 5475,
    cfg: MarkovConfig = None,
) -> str:
    """Plain (non-tool) entry point: fetch prices via the data vendor and return the
    Markov 2.0 markdown report. Used both by the @tool wrapper and by the Market
    Analyst node so the regime is a *guaranteed* input (not dependent on the LLM
    choosing to call a tool). Never raises — returns a readable message on failure.
    """
    cfg = cfg or MarkovConfig()
    try:
        start = (
            datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=lookback_days)
        ).strftime("%Y-%m-%d")
    except ValueError:
        return f"Regime analysis: invalid date '{curr_date}', expected YYYY-mm-dd."

    try:
        raw = route_to_vendor("get_stock_data", symbol, start, curr_date)
        closes, highs, lows = _parse_ohlc(raw)
    except Exception as e:  # data-vendor failure must not break the run
        return f"Regime analysis unavailable for {symbol}: data fetch failed ({e})."

    if len(closes) < 60:
        return (
            f"Regime analysis unavailable for {symbol}: only {len(closes)} price "
            f"points in the window (need >= 60). Try a larger lookback_days."
        )

    res = analyze(closes, cfg, highs, lows)
    return _format_report(symbol, curr_date, res, cfg)


@tool
def get_regime_analysis(
    symbol: Annotated[str, "ticker symbol of the company, e.g. AAPL, SPY"],
    curr_date: Annotated[str, "the current trading date, YYYY-mm-dd"],
    lookback_days: Annotated[
        int,
        "calendar days of price history to analyse. Default ~15y: non-overlapping "
        "stride sampling needs long daily history for the readiness gate to trip.",
    ] = 5475,
) -> str:
    """Markov 2.0 regime analysis for a ticker.

    Labels each day BULL / BEAR / SIDEWAYS from its 20-day cumulative return, builds
    a statistically honest (non-overlapping) state-transition matrix, and reports:
    the current regime, a directional signal P(bull next) − P(bear next), the edge
    vs the long-run base rate, a readiness flag, and a suggested FILTER-mode action.
    Use it as a regime/timing overlay alongside the other analysts — it does not
    pick stocks. Returns a markdown report.
    """
    return compute_regime_report(symbol, curr_date, lookback_days)
