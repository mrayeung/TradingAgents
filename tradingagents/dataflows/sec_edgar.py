"""SEC EDGAR API integration — no API key required.

Fetches 10-K (annual) and 10-Q (quarterly) filings for any US-listed
company using the public SEC EDGAR REST APIs.

Primary APIs used:
  Ticker → CIK:  https://www.sec.gov/files/company_tickers.json
  Filing list:   https://data.sec.gov/submissions/CIK{cik:010d}.json
  Filing doc:    https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/

SEC rate limit: 10 requests/second. A User-Agent header with contact
info is required per SEC policy (https://www.sec.gov/developer).

Raises SECEdgarUnavailableError on failure so interface.py cascades
to the next vendor without interrupting the agent pipeline.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_SEC_BASE        = "https://data.sec.gov"
_SEC_ARCHIVE     = "https://www.sec.gov/Archives/edgar/data"
_TICKERS_URL     = "https://www.sec.gov/files/company_tickers.json"
_USER_AGENT      = "TradingAgents research/1.0 (contact: research@example.com)"
_TIMEOUT         = 20  # seconds per request
_RATE_DELAY      = 0.12  # 120 ms between requests → stays under 10 req/s

# Characters to return per extracted section (Risk Factors, MD&A, etc.)
_SECTION_MAX_CHARS = 3_000


class SECEdgarUnavailableError(Exception):
    """Raised when SEC EDGAR is unreachable — triggers vendor fallback."""


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get(url: str) -> requests.Response:
    """GET with required User-Agent and timeout, respecting SEC rate limit."""
    time.sleep(_RATE_DELAY)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp
    except requests.HTTPError as e:
        raise SECEdgarUnavailableError(f"SEC EDGAR HTTP error {e.response.status_code} for {url}") from e
    except Exception as e:
        raise SECEdgarUnavailableError(f"SEC EDGAR request failed: {e}") from e


# ---------------------------------------------------------------------------
# Ticker → CIK resolution
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_ticker_map() -> dict[str, str]:
    """Download and cache the full SEC ticker→CIK map (one call per process)."""
    try:
        resp = requests.get(
            _TICKERS_URL,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        # Format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        return {
            v["ticker"].upper(): str(v["cik_str"]).zfill(10)
            for v in data.values()
        }
    except Exception as e:
        raise SECEdgarUnavailableError(f"Failed to load SEC ticker map: {e}") from e


def _resolve_cik(ticker: str) -> str:
    """Return zero-padded 10-digit CIK for a ticker, e.g. '0000320193'."""
    mapping = _load_ticker_map()
    cik = mapping.get(ticker.upper())
    if not cik:
        raise SECEdgarUnavailableError(
            f"Ticker '{ticker}' not found in SEC EDGAR — "
            f"may be a non-US or recently listed company"
        )
    return cik


# ---------------------------------------------------------------------------
# Filing metadata
# ---------------------------------------------------------------------------

def _get_submissions(cik: str) -> dict:
    """Fetch filing submission metadata for a CIK."""
    url = f"{_SEC_BASE}/submissions/CIK{cik}.json"
    return _get(url).json()


def _find_recent_filings(
    cik: str,
    form_types: list[str],
    start_date: str,
    end_date: str,
    limit: int = 3,
) -> list[dict]:
    """Return up to `limit` filings of the given form types within the date range."""
    submissions  = _get_submissions(cik)
    recent       = submissions.get("filings", {}).get("recent", {})
    forms        = recent.get("form", [])
    dates        = recent.get("filingDate", [])
    accessions   = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d")

    results = []
    for form, date, accession, doc in zip(forms, dates, accessions, primary_docs):
        if form not in form_types:
            continue
        try:
            filing_dt = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            continue
        if not (start_dt <= filing_dt <= end_dt):
            continue
        results.append({
            "form":       form,
            "date":       date,
            "accession":  accession.replace("-", ""),  # strip dashes for URL
            "accession_raw": accession,
            "primary_doc": doc,
        })
        if len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Text extraction from filings
# ---------------------------------------------------------------------------

_HTML_TAG_RE   = re.compile(r"<[^>]+>")
_MULTI_SPACE   = re.compile(r"\s{3,}")
_SECTION_ITEMS = [
    # (label_for_output, regex_pattern_for_header)
    ("Risk Factors",
     r"item\s+1a[\.\s]*[–—-]?\s*risk\s+factors"),
    ("Management's Discussion & Analysis",
     r"item\s+7[\.\s]*[–—-]?\s*management.{0,30}discussion"),
    ("Business Overview",
     r"item\s+1[\.\s]*[–—-]?\s*business\b"),
]


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = _HTML_TAG_RE.sub(" ", html)
    text = _MULTI_SPACE.sub("\n", text)
    return text.strip()


def _extract_sections(raw_text: str) -> dict[str, str]:
    """Extract key 10-K/10-Q sections from plain text (post HTML stripping).

    10-K documents have two occurrences of each section header:
      1. Table of Contents — followed only by a page number ("... 20")
      2. Actual section body — followed by substantive prose

    We iterate ALL matches and take the last one that has >200 chars of
    real content before the next Item header (skipping TOC entries).
    """
    text   = raw_text.lower()
    result = {}

    for label, pattern in _SECTION_ITEMS:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if not matches:
            continue

        chosen = None
        for m in matches:
            start   = m.end()
            window  = raw_text[start : start + _SECTION_MAX_CHARS + 2_000]
            # Skip Table of Contents entries: content is just whitespace + a number
            stripped = window.lstrip()
            if re.match(r"^[\d\s\.]{0,10}$", stripped[:50]):
                continue
            # Skip if there's almost no content
            if len(stripped) < 150:
                continue
            chosen = (start, window)
            # Don't break — prefer later matches (actual body over TOC)

        if not chosen:
            # Fall back to first match if all look like TOC (edge case)
            m      = matches[-1]
            start  = m.end()
            window = raw_text[start : start + _SECTION_MAX_CHARS + 2_000]
            chosen = (start, window)

        start, window = chosen
        # Trim at the next "Item N" header
        next_item = re.search(r"\bitem\s+\d", window.lower())
        end_idx   = next_item.start() if next_item else _SECTION_MAX_CHARS
        snippet   = window[:end_idx].strip()
        snippet   = _MULTI_SPACE.sub("\n", snippet)
        result[label] = snippet[:_SECTION_MAX_CHARS]

    return result


def _fetch_filing_document(cik: str, accession_nodashes: str, primary_doc: str) -> str:
    """Download the primary HTML/text document for a filing."""
    url = f"{_SEC_ARCHIVE}/{int(cik)}/{accession_nodashes}/{primary_doc}"
    try:
        time.sleep(_RATE_DELAY)
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.text
        # Strip HTML if it's an HTML document
        if "<html" in content[:500].lower() or "<HTML" in content[:500]:
            content = _strip_html(content)
        return content
    except Exception as e:
        raise SECEdgarUnavailableError(f"Failed to fetch filing document {url}: {e}") from e


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def get_sec_filings(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch recent SEC 10-K and 10-Q filings for a ticker.

    Retrieves filing metadata + extracts Risk Factors, MD&A, and Business
    Overview sections from the most recent annual report (10-K) within the
    date window. Falls back to 10-Q if no 10-K is found.

    Args:
        ticker:     Stock ticker symbol, e.g. "AAPL".
        start_date: Start date YYYY-MM-DD (look-back window for filings).
        end_date:   End date   YYYY-MM-DD.

    Returns:
        Formatted Markdown string with filing excerpts.

    Raises:
        SECEdgarUnavailableError: on network, parse, or CIK resolution failure.
    """
    try:
        cik = _resolve_cik(ticker)
        company_name = ""
        try:
            subs = _get_submissions(cik)
            company_name = subs.get("name", ticker)
        except SECEdgarUnavailableError:
            company_name = ticker

        # Prefer 10-K (annual) — search up to 18 months back so we always get one
        wide_start = (
            datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=548)
        ).strftime("%Y-%m-%d")

        annual  = _find_recent_filings(cik, ["10-K"],       wide_start, end_date, limit=1)
        quarter = _find_recent_filings(cik, ["10-Q"],       start_date, end_date, limit=1)

        # Put 10-K first so section extraction runs on the annual report
        filings = annual + [q for q in quarter if q not in annual]

        if not filings:
            filings = _find_recent_filings(
                cik, ["10-K", "10-Q"], wide_start, end_date, limit=1
            )

        if not filings:
            return (
                f"No SEC 10-K or 10-Q filings found for {ticker} "
                f"({company_name}) near {end_date}. "
                f"The company may have a different fiscal year calendar."
            )

        result = (
            f"## SEC EDGAR Filings — {ticker} ({company_name})\n\n"
        )

        for filing in filings[:2]:
            form   = filing["form"]
            date   = filing["date"]
            acc    = filing["accession_raw"]
            result += f"### {form} filed {date}  (Accession: {acc})\n\n"

            # Only extract sections from the most recent 10-K to limit tokens
            if filing == filings[0] and filing["primary_doc"]:
                try:
                    doc_text = _fetch_filing_document(
                        cik, filing["accession"], filing["primary_doc"]
                    )
                    sections = _extract_sections(doc_text)
                    if sections:
                        for section_name, content in sections.items():
                            result += f"#### {section_name}\n{content}\n\n"
                    else:
                        result += (
                            "_Section extraction not available for this filing format. "
                            f"View full filing: https://www.sec.gov/cgi-bin/browse-edgar"
                            f"?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=10_\n\n"
                        )
                except SECEdgarUnavailableError as e:
                    result += f"_Could not fetch filing document: {e}_\n\n"

            result += (
                f"[View on EDGAR](https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&CIK={cik}&type={form}"
                f"&dateb=&owner=include&count=10)\n\n"
            )

        return result

    except SECEdgarUnavailableError:
        raise
    except Exception as e:
        logger.warning("SEC EDGAR error for %s: %s", ticker, e)
        raise SECEdgarUnavailableError(f"SEC EDGAR failed for {ticker}: {e}") from e


def get_sec_filings_summary(ticker: str, end_date: str) -> str:
    """Lightweight version — filing metadata only, no document fetch.

    Useful when you need to know what's been filed recently without
    the overhead of downloading the full document.
    """
    start_date = (
        datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=548)
    ).strftime("%Y-%m-%d")
    try:
        cik      = _resolve_cik(ticker)
        filings  = _find_recent_filings(
            cik, ["10-K", "10-Q", "8-K"], start_date, end_date, limit=5
        )
        if not filings:
            return f"No recent SEC filings found for {ticker} in the last 18 months."

        lines = [f"## Recent SEC Filings — {ticker}\n"]
        for f in filings:
            lines.append(
                f"- **{f['form']}** filed {f['date']}  "
                f"(Accession: {f['accession_raw']})"
            )
        return "\n".join(lines)
    except SECEdgarUnavailableError:
        raise
    except Exception as e:
        raise SECEdgarUnavailableError(f"SEC EDGAR summary failed for {ticker}: {e}") from e
