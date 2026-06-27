"""
LangChain tools for the Valuation Analyst.

Two tools:
- get_valuation_metrics: current multiples + historical 3yr table
- get_peer_comparables: comps table for a list of peer tickers
"""

from typing import Annotated

from langchain_core.tools import tool


@tool
def get_valuation_metrics(
    ticker: Annotated[str, "Ticker symbol, e.g. 'AAPL'"],
    trade_date: Annotated[str, "Trade/analysis date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve comprehensive valuation metrics for a stock, including:
    1. Current multiples (trailing P/E, forward P/E, EV/EBITDA, P/S, P/B, PEG, dividend yield)
    2. Growth and profitability ratios (revenue growth, margins, ROE, FCF)
    3. Sector-specific valuation framework guidance
    4. Historical multiples over the last 3 fiscal years for own-history comparison

    Call this FIRST before selecting peers. The sector field in the output tells
    you which valuation framework to apply and which metrics matter most for
    this specific company type.
    """
    from tradingagents.dataflows.valuation import get_current_multiples, get_historical_multiples

    current = get_current_multiples(ticker)
    historical = get_historical_multiples(ticker, years=3)
    return f"{current}\n\n---\n\n{historical}"


@tool
def get_peer_comparables(
    peer_tickers: Annotated[
        str,
        "Comma-separated list of peer ticker symbols, e.g. 'MSFT,GOOGL,META,AMZN'",
    ],
) -> str:
    """
    Build a peer comparables table for a list of ticker symbols.

    Call this AFTER get_valuation_metrics once you have identified appropriate
    sector peers.

    Select 6-10 peers that are:
    - In the same sector/industry as the target company
    - Similar in scale (within 0.3x–3x of target market cap is ideal)
    - True business comparables (similar revenue model, not just same sector)

    For niche industries (specialty materials, regional banks, micro-cap) you may
    use fewer peers if genuine comparables are limited.

    The tool validates each ticker against yfinance and silently skips any that
    lack sufficient data. Returns a Markdown comparables table.
    """
    from tradingagents.dataflows.valuation import get_peer_multiples

    tickers = [t.strip().upper() for t in peer_tickers.split(",") if t.strip()]
    return get_peer_multiples(tickers)
