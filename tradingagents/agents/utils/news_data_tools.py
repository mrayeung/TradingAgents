from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.sec_edgar import SECEdgarUnavailableError

@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    return route_to_vendor("get_news", ticker, start_date, end_date)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor.
    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back (default 7)
        limit (int): Maximum number of articles to return (default 5)
    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker)


@tool
def get_social_sentiment(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve social media sentiment data for a given ticker symbol from Reddit
    and StockTwits (via Finnhub).  Returns daily mention counts and positive /
    negative sentiment scores so the social media analyst can assess crowd
    sentiment trends.
    Args:
        ticker (str): Ticker symbol, e.g. "AAPL"
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: Formatted Markdown tables of daily Reddit and StockTwits mentions
             and sentiment scores.
    """
    try:
        return route_to_vendor("get_social_sentiment", ticker, start_date, end_date)
    except RuntimeError:
        # No vendor available (e.g. Finnhub free plan doesn't include social sentiment).
        # Return a soft message so the agent pipeline continues uninterrupted.
        return (
            f"Social sentiment data is not available for {ticker} "
            f"(requires a Finnhub paid plan upgrade at https://finnhub.io/pricing). "
            f"Proceeding with news-based sentiment analysis only."
        )


@tool
def get_sec_filings(
    ticker: Annotated[str, "Ticker symbol, e.g. 'AAPL'"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve SEC EDGAR filings (10-K annual reports, 10-Q quarterly reports)
    for a given US-listed company. Extracts key sections including Risk Factors,
    Management's Discussion & Analysis (MD&A), and Business Overview directly
    from the official SEC filing documents. No API key required.

    Use this to ground fundamental analysis in audited, legally-filed financial
    disclosures rather than aggregated third-party data.

    Args:
        ticker (str): US stock ticker symbol, e.g. "AAPL", "MSFT", "NVDA"
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: Formatted Markdown with filing metadata and extracted sections
             (Risk Factors, MD&A, Business Overview) from the most recent 10-K.
    """
    try:
        return route_to_vendor("get_sec_filings", ticker, start_date, end_date)
    except (RuntimeError, SECEdgarUnavailableError) as e:
        return (
            f"SEC EDGAR filings not available for {ticker}: {e}. "
            f"Proceeding with yfinance fundamental data only."
        )
