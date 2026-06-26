"""Finnhub news and social sentiment data fetching.

Provides company-specific news, general market news, and social sentiment
(Reddit + StockTwits aggregate) via the Finnhub API.

Requires:
    pip install finnhub-python
    FINNHUB_API_KEY env var set to your Finnhub API key.

When Finnhub is unavailable (missing key, rate limit, network error) this
module raises FinnhubUnavailableError, which interface.py catches to trigger
fallback to the next configured vendor (google_news → yfinance).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class FinnhubUnavailableError(Exception):
    """Raised when Finnhub is unreachable or misconfigured — triggers vendor fallback."""


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _get_client():
    """Return an authenticated Finnhub client, or raise FinnhubUnavailableError."""
    try:
        import finnhub
    except ImportError:
        raise FinnhubUnavailableError(
            "finnhub-python not installed — run: pip install finnhub-python"
        )
    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        raise FinnhubUnavailableError(
            "FINNHUB_API_KEY not set — add it to your .env file"
        )
    return finnhub.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# Company news
# ---------------------------------------------------------------------------

def get_news_finnhub(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch company-specific news from Finnhub.

    Args:
        ticker:     Stock ticker symbol, e.g. "AAPL".
        start_date: Start date  YYYY-MM-DD.
        end_date:   End date    YYYY-MM-DD.

    Returns:
        Formatted Markdown string of news articles.

    Raises:
        FinnhubUnavailableError: on missing key, rate limit, or network failure.
    """
    try:
        client = _get_client()
        articles = client.company_news(ticker, _from=start_date, to=end_date)

        if not articles:
            return f"No Finnhub news found for {ticker} between {start_date} and {end_date}"

        news_str = ""
        for a in articles[:20]:
            headline = a.get("headline", "No title")
            summary  = a.get("summary", "")
            source   = a.get("source", "Unknown")
            url      = a.get("url", "")
            ts       = a.get("datetime", 0)
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
            sentiment = a.get("sentiment", "")

            news_str += f"### {headline} (source: {source}, {date_str})\n"
            if sentiment:
                news_str += f"Sentiment: {sentiment}\n"
            if summary:
                news_str += f"{summary[:400]}\n"
            if url:
                news_str += f"Link: {url}\n"
            news_str += "\n"

        return f"## {ticker} News from Finnhub, {start_date} to {end_date}:\n\n{news_str}"

    except FinnhubUnavailableError:
        raise
    except Exception as e:
        logger.warning("Finnhub company news error for %s: %s", ticker, e)
        raise FinnhubUnavailableError(f"Finnhub company news failed: {e}") from e


# ---------------------------------------------------------------------------
# Global / macro news
# ---------------------------------------------------------------------------

def get_global_news_finnhub(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 10,
) -> str:
    """Fetch general market news from Finnhub.

    Args:
        curr_date:      Current date YYYY-MM-DD (no look-ahead bias).
        look_back_days: How many days back to include.
        limit:          Max articles to return.

    Returns:
        Formatted Markdown string.

    Raises:
        FinnhubUnavailableError: on error.
    """
    try:
        client = _get_client()
        # Finnhub general news categories: general, forex, crypto, merger
        articles = client.general_news("general", min_id=0)

        if not articles:
            return f"No Finnhub global news found around {curr_date}"

        curr_dt  = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - timedelta(days=look_back_days)

        news_str = ""
        count = 0
        for a in articles:
            if count >= limit:
                break
            ts = a.get("datetime", 0)
            if ts:
                pub_dt = datetime.fromtimestamp(ts)
                if not (start_dt <= pub_dt <= curr_dt + timedelta(days=1)):
                    continue

            headline = a.get("headline", "No title")
            summary  = a.get("summary", "")
            source   = a.get("source", "Unknown")
            url      = a.get("url", "")

            news_str += f"### {headline} (source: {source})\n"
            if summary:
                news_str += f"{summary[:400]}\n"
            if url:
                news_str += f"Link: {url}\n"
            news_str += "\n"
            count += 1

        if not news_str:
            return f"No Finnhub global news found in the last {look_back_days} days"

        return (
            f"## Global Market News from Finnhub,"
            f" last {look_back_days} days:\n\n{news_str}"
        )

    except FinnhubUnavailableError:
        raise
    except Exception as e:
        logger.warning("Finnhub global news error: %s", e)
        raise FinnhubUnavailableError(f"Finnhub global news failed: {e}") from e


# ---------------------------------------------------------------------------
# Social sentiment  (Reddit + StockTwits)
# ---------------------------------------------------------------------------

def get_social_sentiment_finnhub(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """Fetch social sentiment from Finnhub (Reddit + StockTwits aggregate).

    This is the data source that properly backs the social_media_analyst —
    actual crowd sentiment counts and scores, not just news articles.

    Args:
        ticker:     Stock ticker symbol.
        start_date: Start date YYYY-MM-DD.
        end_date:   End date   YYYY-MM-DD.

    Returns:
        Formatted Markdown string with daily mention counts and sentiment scores.

    Raises:
        FinnhubUnavailableError: on error.
    """
    try:
        client = _get_client()
        data = client.stock_social_sentiment(ticker, _from=start_date, to=end_date)

        reddit  = data.get("reddit", [])
        twitter = data.get("twitter", [])   # Finnhub labels StockTwits as twitter

        if not reddit and not twitter:
            return (
                f"No social sentiment data found for {ticker} "
                f"between {start_date} and {end_date}"
            )

        result = (
            f"## {ticker} Social Sentiment (Finnhub / Reddit + StockTwits),"
            f" {start_date} to {end_date}:\n\n"
        )

        if reddit:
            result += "### Reddit\n"
            result += "| Date | Mentions | Positive Score | Negative Score |\n"
            result += "|------|----------|---------------|----------------|\n"
            for d in sorted(reddit, key=lambda x: x.get("atTime", ""))[-14:]:
                date = d.get("atTime", "")[:10]
                mention = d.get("mention", 0)
                pos     = round(d.get("positiveScore", 0), 3)
                neg     = round(d.get("negativeScore", 0), 3)
                result += f"| {date} | {mention} | {pos} | {neg} |\n"
            result += "\n"

        if twitter:
            result += "### StockTwits\n"
            result += "| Date | Mentions | Positive Score | Negative Score |\n"
            result += "|------|----------|---------------|----------------|\n"
            for d in sorted(twitter, key=lambda x: x.get("atTime", ""))[-14:]:
                date = d.get("atTime", "")[:10]
                mention = d.get("mention", 0)
                pos     = round(d.get("positiveScore", 0), 3)
                neg     = round(d.get("negativeScore", 0), 3)
                result += f"| {date} | {mention} | {pos} | {neg} |\n"
            result += "\n"

        return result

    except FinnhubUnavailableError:
        raise
    except Exception as e:
        logger.warning("Finnhub social sentiment error for %s: %s", ticker, e)
        raise FinnhubUnavailableError(f"Finnhub social sentiment failed: {e}") from e
