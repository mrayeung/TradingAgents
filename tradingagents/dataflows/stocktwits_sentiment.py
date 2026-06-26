"""StockTwits public API — no API key required.

Fetches the latest messages for a ticker from StockTwits and aggregates
bullish / bearish sentiment counts. Used as the free fallback behind
Finnhub for the get_social_sentiment vendor method.

No installation required beyond the standard `requests` library.

Raises StockTwitsUnavailableError on failure so interface.py cascades
to the next vendor without interrupting the agent pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_TIMEOUT = 15  # seconds


class StockTwitsUnavailableError(Exception):
    """Raised when StockTwits is unreachable — triggers vendor fallback."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_messages(ticker: str) -> list:
    """Fetch the latest 30 StockTwits messages for a ticker."""
    url = _BASE_URL.format(ticker=ticker)
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        if resp.status_code == 429:
            raise StockTwitsUnavailableError(f"StockTwits rate limited for {ticker}")
        if resp.status_code == 404:
            raise StockTwitsUnavailableError(f"Ticker {ticker} not found on StockTwits")
        if resp.status_code != 200:
            raise StockTwitsUnavailableError(
                f"StockTwits returned HTTP {resp.status_code} for {ticker}"
            )
        data = resp.json()
        return data.get("messages", [])
    except StockTwitsUnavailableError:
        raise
    except Exception as e:
        raise StockTwitsUnavailableError(
            f"StockTwits fetch failed for {ticker}: {e}"
        ) from e


def _parse_created_at(msg: dict) -> datetime | None:
    """Parse StockTwits created_at timestamp, e.g. '2026-06-25T12:34:56Z'."""
    raw = msg.get("created_at", "")
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+0000"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _sentiment_label(msg: dict) -> str | None:
    """Extract bullish/bearish label from a message's entities block."""
    entities = msg.get("entities", {})
    sentiment = entities.get("sentiment")
    if sentiment and isinstance(sentiment, dict):
        return sentiment.get("basic")   # "Bullish" or "Bearish" or None
    return None


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def get_social_sentiment_stocktwits(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """Fetch social sentiment from StockTwits (no API key required).

    Retrieves the latest 30 messages for the ticker, filters to the
    requested date window, counts bullish vs bearish signals, and returns
    a Markdown summary with sample message excerpts.

    Note: The free StockTwits API returns only the most recent 30 messages
    so historical coverage depends on posting volume. High-volume tickers
    (AAPL, TSLA, NVDA) typically cover 1-3 days; low-volume tickers may
    cover weeks.

    Args:
        ticker:     Stock ticker symbol, e.g. "AAPL".
        start_date: Start date YYYY-MM-DD (used for filtering).
        end_date:   End date   YYYY-MM-DD (used for filtering).

    Returns:
        Formatted Markdown string with sentiment counts and excerpts.

    Raises:
        StockTwitsUnavailableError: on network or API failure.
    """
    try:
        messages = _fetch_messages(ticker)

        if not messages:
            return f"No StockTwits messages found for {ticker}"

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt   = datetime.strptime(end_date,   "%Y-%m-%d") + timedelta(days=1)

        bullish_msgs  = []
        bearish_msgs  = []
        neutral_count = 0
        out_of_window = 0

        for msg in messages:
            pub_dt = _parse_created_at(msg)
            if pub_dt and not (start_dt <= pub_dt < end_dt):
                out_of_window += 1
                continue

            label = _sentiment_label(msg)
            body  = msg.get("body", "").replace("\n", " ")[:200]
            user  = msg.get("user", {}).get("username", "unknown")
            date  = pub_dt.strftime("%Y-%m-%d %H:%M") if pub_dt else ""

            entry = f"- **@{user}** ({date}): {body}"

            if label == "Bullish":
                bullish_msgs.append(entry)
            elif label == "Bearish":
                bearish_msgs.append(entry)
            else:
                neutral_count += 1

        total_tagged = len(bullish_msgs) + len(bearish_msgs)

        if total_tagged == 0 and neutral_count == 0:
            return (
                f"No StockTwits messages for {ticker} in window "
                f"{start_date} to {end_date} "
                f"({out_of_window} messages were outside the window)."
            )

        bull_pct = round(len(bullish_msgs) / total_tagged * 100) if total_tagged else 0
        bear_pct = round(len(bearish_msgs) / total_tagged * 100) if total_tagged else 0

        result = (
            f"## {ticker} Social Sentiment — StockTwits "
            f"(free tier, ~30 most recent messages)\n\n"
            f"**Window:** {start_date} to {end_date}\n\n"
            f"| Sentiment | Count | Share |\n"
            f"|-----------|-------|-------|\n"
            f"| 🟢 Bullish | {len(bullish_msgs)} | {bull_pct}% |\n"
            f"| 🔴 Bearish | {len(bearish_msgs)} | {bear_pct}% |\n"
            f"| ⬜ Neutral  | {neutral_count} | — |\n\n"
        )

        if bullish_msgs:
            result += "### Bullish messages\n"
            result += "\n".join(bullish_msgs[:5]) + "\n\n"

        if bearish_msgs:
            result += "### Bearish messages\n"
            result += "\n".join(bearish_msgs[:5]) + "\n\n"

        return result

    except StockTwitsUnavailableError:
        raise
    except Exception as e:
        logger.warning("StockTwits sentiment error for %s: %s", ticker, e)
        raise StockTwitsUnavailableError(
            f"StockTwits sentiment failed for {ticker}: {e}"
        ) from e
