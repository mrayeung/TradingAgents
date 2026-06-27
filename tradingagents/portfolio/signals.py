"""
Signal aggregation: parse saved full_states_log JSON reports → conviction scores.

Each report JSON has these top-level string fields (all optional):
  market_report, sentiment_report, news_report, fundamentals_report,
  valuation_report, market_technician_report, quantitative_report,
  final_trade_decision

Produces one SignalRow per ticker (most recent run only).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

STALE_DAYS = 14


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalystVerdicts:
    market: str = ""
    sentiment: str = ""
    news: str = ""
    fundamentals: str = ""
    valuation: str = ""
    market_technician: str = ""
    quantitative: str = ""


@dataclass
class SignalRow:
    ticker: str
    date: str                    # YYYY-MM-DD
    age_days: int
    stale: bool
    rating: str                  # BUY / HOLD / SELL
    conviction: float            # 0..1
    expected_return: float       # annualised, e.g. 0.25 = 25%
    win_prob: float              # e.g. 0.70
    analyst_verdicts: AnalystVerdicts = field(default_factory=AnalystVerdicts)
    report_path: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Keyword scanners
# ─────────────────────────────────────────────────────────────────────────────

_BULLISH_KW = re.compile(
    r"\b(bullish|strong buy|outperform|overweight|upside|undervalued|buy)\b",
    re.I,
)
_BEARISH_KW = re.compile(
    r"\b(bearish|strong sell|underperform|underweight|downside|overvalued|sell)\b",
    re.I,
)
_VALUATION_VERDICT = re.compile(
    r"(?:Valuation Verdict|valuation verdict)[:\s]*\*{0,2}"
    r"(Significantly Undervalued|Moderately Undervalued|Fairly Valued|"
    r"Moderately Overvalued|Significantly Overvalued)",
    re.I,
)


def _sentiment_from_text(text: str) -> float:
    """Return -1..+1 based on keyword frequency in a report block."""
    if not text:
        return 0.0
    bull = len(_BULLISH_KW.findall(text))
    bear = len(_BEARISH_KW.findall(text))
    total = bull + bear
    if total == 0:
        return 0.0
    return (bull - bear) / total


def _parse_valuation_verdict(text: str) -> str:
    """Extract the Valuation Verdict label from valuation_report."""
    m = _VALUATION_VERDICT.search(text or "")
    return m.group(1) if m else ""


# Valuation verdict → expected return and win probability mappings
_VERDICT_TO_ERET: dict[str, float] = {
    "significantly undervalued": 0.30,
    "moderately undervalued":    0.15,
    "fairly valued":             0.07,
    "moderately overvalued":    -0.10,
    "significantly overvalued": -0.20,
}

_VERDICT_TO_WINPROB: dict[str, float] = {
    "significantly undervalued": 0.72,
    "moderately undervalued":    0.62,
    "fairly valued":             0.52,
    "moderately overvalued":     0.40,
    "significantly overvalued":  0.30,
}

# Maps the 5-tier sell-side scale returned by parse_rating() to a 0..1 score.
# Title-cased keys match parse_rating output exactly.
_RATING_TO_SCORE: dict[str, float] = {
    "Buy":         1.00,
    "Overweight":  0.75,
    "Hold":        0.50,
    "Underweight": 0.25,
    "Sell":        0.00,
    # Legacy uppercase variants (defensive)
    "BUY":  1.00,
    "HOLD": 0.50,
    "SELL": 0.00,
}


def _direction_label(score: float) -> str:
    if score > 0.25:
        return "bullish"
    if score < -0.25:
        return "bearish"
    return "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# Core aggregation
# ─────────────────────────────────────────────────────────────────────────────

def _score_report(doc: dict) -> SignalRow:
    """Derive a SignalRow from a single full_states_log document."""
    from tradingagents.agents.utils.rating import parse_rating

    final = doc.get("final_trade_decision", "")
    rating = parse_rating(final)

    verdicts = AnalystVerdicts(
        market=_direction_label(_sentiment_from_text(doc.get("market_report", ""))),
        sentiment=_direction_label(_sentiment_from_text(doc.get("sentiment_report", ""))),
        news=_direction_label(_sentiment_from_text(doc.get("news_report", ""))),
        fundamentals=_direction_label(_sentiment_from_text(doc.get("fundamentals_report", ""))),
        market_technician=_direction_label(_sentiment_from_text(doc.get("market_technician_report", ""))),
        quantitative=_direction_label(_sentiment_from_text(doc.get("quantitative_report", ""))),
        valuation=_parse_valuation_verdict(doc.get("valuation_report", "")),
    )

    # Average sentiment across all available textual reports
    text_fields = [
        "market_report", "sentiment_report", "news_report",
        "fundamentals_report", "market_technician_report", "quantitative_report",
    ]
    scores = [_sentiment_from_text(doc.get(f, "")) for f in text_fields if doc.get(f)]
    avg_sentiment = sum(scores) / len(scores) if scores else 0.0

    # Valuation verdict drives expected_return and win_prob when available
    verdict_key = verdicts.valuation.lower()
    if verdict_key in _VERDICT_TO_ERET:
        expected_return = _VERDICT_TO_ERET[verdict_key]
        win_prob = _VERDICT_TO_WINPROB[verdict_key]
    else:
        # Fall back to sentiment-based estimate
        expected_return = avg_sentiment * 0.20 + 0.07
        win_prob = 0.52 + avg_sentiment * 0.10

    # Conviction: blend rating (60%) + average analyst sentiment (40%)
    rating_score = _RATING_TO_SCORE.get(rating, 0.5)
    conviction = 0.6 * rating_score + 0.4 * ((avg_sentiment + 1) / 2)
    conviction = min(max(conviction, 0.0), 1.0)

    return SignalRow(
        ticker="",    # filled by caller
        date="",      # filled by caller
        age_days=0,   # filled by caller
        stale=False,
        rating=rating,
        conviction=round(conviction, 3),
        expected_return=round(expected_return, 4),
        win_prob=round(min(max(win_prob, 0.10), 0.95), 3),
        analyst_verdicts=verdicts,
    )


def aggregate_signals(results_dir: Path) -> list[SignalRow]:
    """Scan results_dir and return one SignalRow per ticker (most recent run).

    Looks for:  results_dir/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json
    """
    today = date.today()

    # Collect: ticker → [(date_str, path)]
    runs: dict[str, list[tuple[str, Path]]] = {}
    for path in results_dir.glob("*/TradingAgentsStrategy_logs/full_states_log_*.json"):
        ticker = path.parent.parent.name.upper()
        run_date = path.stem.replace("full_states_log_", "")
        runs.setdefault(ticker, []).append((run_date, path))

    signals: list[SignalRow] = []
    for ticker, run_list in runs.items():
        run_list.sort(key=lambda x: x[0], reverse=True)   # most recent first
        run_date_str, path = run_list[0]

        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue

        row = _score_report(doc)
        row.ticker = ticker
        row.date = run_date_str
        row.report_path = str(path)

        try:
            run_dt = datetime.strptime(run_date_str, "%Y-%m-%d").date()
            row.age_days = (today - run_dt).days
        except ValueError:
            row.age_days = 0
        row.stale = row.age_days > STALE_DAYS

        signals.append(row)

    signals.sort(key=lambda s: (-s.conviction, s.ticker))
    return signals
