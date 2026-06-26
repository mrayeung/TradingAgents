"""Google News RSS feed fetcher — no API key required.

Provides company-specific and macro market news by parsing Google News RSS
feeds. Used as the fallback behind Finnhub in the news_data vendor chain.

Requires:
    pip install feedparser

Raises GoogleNewsUnavailableError on failure so interface.py can cascade
to the next vendor (yfinance) without interrupting the agent pipeline.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "TradingAgents/1.0 (research tool; contact@example.com)"}
_TIMEOUT = 15  # seconds per RSS fetch


class GoogleNewsUnavailableError(Exception):
    """Raised when Google News RSS is unreachable — triggers vendor fallback."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_rss(url: str) -> list:
    """Download and parse an RSS feed URL. Returns list of feedparser entries."""
    try:
        import feedparser
    except ImportError:
        raise GoogleNewsUnavailableError(
            "feedparser not installed — run: pip install feedparser"
        )
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            content = resp.read()
        feed = feedparser.parse(content)
        return feed.entries or []
    except GoogleNewsUnavailableError:
        raise
    except Exception as e:
        raise GoogleNewsUnavailableError(f"RSS fetch failed for {url}: {e}") from e


def _parse_pub_date(entry) -> datetime | None:
    """Parse an RSS entry's published date, returning None if unparseable."""
    from email.utils import parsedate_to_datetime
    try:
        if hasattr(entry, "published") and entry.published:
            return parsedate_to_datetime(entry.published).replace(tzinfo=None)
    except Exception:
        pass
    return None


def _clean_summary(raw: str, max_len: int = 350) -> str:
    """Strip HTML tags and truncate summary text."""
    clean = re.sub(r"<[^>]+>", "", raw or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:max_len] if len(clean) > max_len else clean


def _source_name(entry) -> str:
    """Extract publisher name from a feedparser entry."""
    src = getattr(entry, "source", None)
    if isinstance(src, dict):
        return src.get("title", "Google News")
    return "Google News"


# ---------------------------------------------------------------------------
# Company news
# ---------------------------------------------------------------------------

def get_news_google_rss(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch company-specific news via Google News RSS.

    Args:
        ticker:     Stock ticker symbol, e.g. "AAPL".
        start_date: Start date YYYY-MM-DD.
        end_date:   End date   YYYY-MM-DD.

    Returns:
        Formatted Markdown string of news articles.

    Raises:
        GoogleNewsUnavailableError: on network or parse failure.
    """
    try:
        query   = urllib.parse.quote(f"{ticker} stock earnings")
        url     = (
            f"https://news.google.com/rss/search"
            f"?q={query}&hl=en-US&gl=US&ceid=US:en"
        )
        entries = _fetch_rss(url)

        if not entries:
            return f"No Google News found for {ticker}"

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt   = datetime.strptime(end_date,   "%Y-%m-%d")

        news_str = ""
        count = 0
        for entry in entries:
            if count >= 20:
                break
            pub_date = _parse_pub_date(entry)
            if pub_date and not (start_dt <= pub_date <= end_dt + timedelta(days=1)):
                continue

            title    = entry.get("title", "No title")
            link     = entry.get("link", "")
            summary  = _clean_summary(entry.get("summary", ""))
            source   = _source_name(entry)
            date_str = pub_date.strftime("%Y-%m-%d") if pub_date else ""

            news_str += f"### {title} (source: {source}, {date_str})\n"
            if summary and summary != title:
                news_str += f"{summary}\n"
            if link:
                news_str += f"Link: {link}\n"
            news_str += "\n"
            count += 1

        if not news_str:
            return (
                f"No Google News articles found for {ticker} "
                f"between {start_date} and {end_date}"
            )
        return f"## {ticker} News from Google News RSS, {start_date} to {end_date}:\n\n{news_str}"

    except GoogleNewsUnavailableError:
        raise
    except Exception as e:
        logger.warning("Google News RSS error for %s: %s", ticker, e)
        raise GoogleNewsUnavailableError(f"Google News RSS failed for {ticker}: {e}") from e


# ---------------------------------------------------------------------------
# Global / macro news
# ---------------------------------------------------------------------------

_MACRO_QUERIES = [
    "stock market investing outlook",
    "Federal Reserve interest rates policy",
    "inflation economy GDP",
    "earnings season corporate results",
]


def get_global_news_google_rss(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 10,
) -> str:
    """Fetch macro market news via Google News RSS.

    Searches several macro-focused queries, deduplicates by title, and
    filters to the requested look-back window.

    Args:
        curr_date:      Current date YYYY-MM-DD.
        look_back_days: Days to look back.
        limit:          Max articles to return.

    Returns:
        Formatted Markdown string.

    Raises:
        GoogleNewsUnavailableError: if all queries fail.
    """
    try:
        curr_dt  = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - timedelta(days=look_back_days)

        seen_titles: set[str] = set()
        all_entries: list = []

        for query in _MACRO_QUERIES:
            encoded = urllib.parse.quote(query)
            url     = (
                f"https://news.google.com/rss/search"
                f"?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            )
            try:
                for entry in _fetch_rss(url):
                    title = entry.get("title", "")
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_entries.append(entry)
            except GoogleNewsUnavailableError:
                continue   # try next query
            if len(all_entries) >= limit * 3:
                break

        if not all_entries:
            raise GoogleNewsUnavailableError(
                "All Google News macro queries failed"
            )

        news_str = ""
        count = 0
        for entry in all_entries:
            if count >= limit:
                break
            pub_date = _parse_pub_date(entry)
            if pub_date:
                if pub_date > curr_dt + timedelta(days=1):
                    continue   # look-ahead guard
                if pub_date < start_dt:
                    continue

            title    = entry.get("title", "No title")
            link     = entry.get("link", "")
            summary  = _clean_summary(entry.get("summary", ""))
            source   = _source_name(entry)
            date_str = pub_date.strftime("%Y-%m-%d") if pub_date else ""

            news_str += f"### {title} (source: {source}, {date_str})\n"
            if summary and summary != title:
                news_str += f"{summary}\n"
            if link:
                news_str += f"Link: {link}\n"
            news_str += "\n"
            count += 1

        if not news_str:
            return f"No Google News global articles found in the last {look_back_days} days"

        return (
            f"## Global Market News from Google News RSS,"
            f" last {look_back_days} days:\n\n{news_str}"
        )

    except GoogleNewsUnavailableError:
        raise
    except Exception as e:
        logger.warning("Google News global RSS error: %s", e)
        raise GoogleNewsUnavailableError(f"Google News global RSS failed: {e}") from e
