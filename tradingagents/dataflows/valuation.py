"""
Valuation data-fetching module for the Valuation Analyst.

Provides:
- SECTOR_VALUATION_FRAMEWORKS: sector → primary metrics + commentary
- get_current_multiples(ticker): current price multiples + sector framework
- get_historical_multiples(ticker, years): 3-year own-history comparison
- get_peer_multiples(peer_tickers): comps table for a list of peers
"""

from __future__ import annotations

import yfinance as yf


SECTOR_VALUATION_FRAMEWORKS: dict[str, dict] = {
    "Technology": {
        "primary_metrics": ["forward_pe", "ev_to_revenue", "ev_to_ebitda", "price_to_sales"],
        "growth_adjusted": True,
        "commentary": (
            "Focus on forward P/E and EV/Revenue for growth names. "
            "PEG ratio normalizes for growth. Pre-profit companies valued on "
            "EV/Revenue or ARR multiples. SaaS comps often trade on NTM revenue multiples."
        ),
    },
    "Financial Services": {
        "primary_metrics": ["price_to_book", "price_to_tangible_book", "trailing_pe", "roe"],
        "growth_adjusted": False,
        "commentary": (
            "P/Book and P/Tangible Book are primary. ROE vs cost of equity "
            "determines premium/discount to book. Earnings-based multiples (P/E) secondary. "
            "Net interest margin and credit quality drive relative valuation."
        ),
    },
    "Real Estate": {
        "primary_metrics": ["ev_to_ebitda", "price_to_book", "dividend_yield"],
        "growth_adjusted": False,
        "commentary": (
            "Traditional P/E not meaningful for REITs — use EV/EBITDA as proxy for "
            "FFO multiple. Dividend yield and NAV discount/premium are key. "
            "Cap rate compression/expansion drives asset value."
        ),
    },
    "Energy": {
        "primary_metrics": ["ev_to_ebitda", "ev_to_revenue", "price_to_fcf"],
        "growth_adjusted": False,
        "commentary": (
            "EV/EBITDA dominates. FCF yield important given capex intensity. "
            "Commodity price sensitivity means through-cycle multiples matter more than spot. "
            "Reserve replacement and production growth are qualitative factors."
        ),
    },
    "Utilities": {
        "primary_metrics": ["trailing_pe", "ev_to_ebitda", "dividend_yield", "price_to_book"],
        "growth_adjusted": False,
        "commentary": (
            "Yield-oriented sector. P/E and EV/EBITDA standard. "
            "Regulated asset base (rate base growth) and dividend sustainability are key. "
            "Premium to market P/E justified by earnings stability."
        ),
    },
    "Healthcare": {
        "primary_metrics": ["forward_pe", "ev_to_ebitda", "ev_to_revenue", "price_to_sales"],
        "growth_adjusted": True,
        "commentary": (
            "Large pharma: P/E and EV/EBITDA. Biotech/pre-revenue: EV/Revenue or pipeline NPV. "
            "Pipeline maturity and patent cliff risk must be considered qualitatively. "
            "R&D productivity and pipeline conversion rates drive premium."
        ),
    },
    "Consumer Cyclical": {
        "primary_metrics": ["trailing_pe", "ev_to_ebitda", "price_to_sales"],
        "growth_adjusted": False,
        "commentary": (
            "EV/EBITDA most common. Same-store sales growth and margin trajectory "
            "are important qualitative inputs. Cyclicality means through-cycle "
            "valuation matters. Inventory turns and working capital efficiency inform quality."
        ),
    },
    "Consumer Defensive": {
        "primary_metrics": ["trailing_pe", "ev_to_ebitda", "dividend_yield", "price_to_sales"],
        "growth_adjusted": False,
        "commentary": (
            "Premium to market multiple justified by earnings stability and dividend reliability. "
            "Brand moat and pricing power inform premium magnitude. "
            "Organic volume growth vs. price/mix is the key debate."
        ),
    },
    "Industrials": {
        "primary_metrics": ["ev_to_ebitda", "trailing_pe", "price_to_fcf", "ev_to_revenue"],
        "growth_adjusted": False,
        "commentary": (
            "EV/EBITDA and FCF yield dominant. Backlog and order book "
            "for project-based businesses. Margin expansion/contraction is key value driver. "
            "Aftermarket/service mix drives quality premium."
        ),
    },
    "Communication Services": {
        "primary_metrics": ["ev_to_ebitda", "trailing_pe", "ev_to_revenue"],
        "growth_adjusted": True,
        "commentary": (
            "Mix of growth (streaming/digital ad) and value (legacy telecom). "
            "Apply growth multiples to digital businesses, EV/EBITDA to telecom. "
            "Subscriber growth and ARPU trends are leading indicators."
        ),
    },
    "Basic Materials": {
        "primary_metrics": ["ev_to_ebitda", "price_to_book", "price_to_fcf", "ev_to_revenue"],
        "growth_adjusted": False,
        "commentary": (
            "EV/EBITDA through-cycle is primary. P/Book for asset-heavy miners. "
            "FCF yield at mid-cycle commodity prices. "
            "Commodity price exposure amplifies valuation swings — use normalized earnings."
        ),
    },
    "default": {
        "primary_metrics": ["trailing_pe", "forward_pe", "ev_to_ebitda", "price_to_sales"],
        "growth_adjusted": False,
        "commentary": (
            "Apply standard multiples as baseline. Identify sector-specific adjustments "
            "based on the company's business model, capital intensity, and growth profile."
        ),
    },
}


def _fmt_num(val: float | None, decimals: int = 1, suffix: str = "") -> str:
    """Format a number for display; return 'N/A' if None or non-finite."""
    if val is None:
        return "N/A"
    try:
        f = float(val)
        if not (f == f):  # NaN check
            return "N/A"
        return f"{f:.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct(val: float | None) -> str:
    """Format a decimal fraction as a percentage string."""
    if val is None:
        return "N/A"
    try:
        f = float(val)
        if not (f == f):
            return "N/A"
        return f"{f * 100:.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_mktcap(val: float | None) -> str:
    """Format market cap as $XXB / $XXM / $XXK."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if v >= 1e12:
            return f"${v/1e12:.1f}T"
        if v >= 1e9:
            return f"${v/1e9:.1f}B"
        if v >= 1e6:
            return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return "N/A"


def get_current_multiples(ticker: str) -> str:
    """
    Return current valuation multiples + sector-appropriate framework guidance.

    Pulls data from yfinance .info and returns a formatted Markdown string
    with three sections:
      1. Company overview (sector, industry, mkt cap)
      2. Valuation multiples table
      3. Sector framework: which metrics to focus on and why
    """
    stock = yf.Ticker(ticker)
    info = stock.info or {}

    company_name = info.get("longName") or info.get("shortName") or ticker
    sector = info.get("sector") or "Unknown"
    industry = info.get("industry") or "Unknown"
    mkt_cap = info.get("marketCap")
    enterprise_val = info.get("enterpriseValue")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    framework = SECTOR_VALUATION_FRAMEWORKS.get(sector, SECTOR_VALUATION_FRAMEWORKS["default"])

    lines = [
        f"## Valuation Metrics — {company_name} ({ticker.upper()})",
        f"**Sector:** {sector}  |  **Industry:** {industry}",
        f"**Market Cap:** {_fmt_mktcap(mkt_cap)}  |  **Enterprise Value:** {_fmt_mktcap(enterprise_val)}  |  **Current Price:** ${_fmt_num(current_price, 2)}",
        "",
        "### Current Multiples",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Trailing P/E | {_fmt_num(info.get('trailingPE'), 1, 'x')} |",
        f"| Forward P/E | {_fmt_num(info.get('forwardPE'), 1, 'x')} |",
        f"| EV / EBITDA | {_fmt_num(info.get('enterpriseToEbitda'), 1, 'x')} |",
        f"| EV / Revenue | {_fmt_num(info.get('enterpriseToRevenue'), 1, 'x')} |",
        f"| Price / Sales (TTM) | {_fmt_num(info.get('priceToSalesTrailingTwelveMonths'), 1, 'x')} |",
        f"| Price / Book | {_fmt_num(info.get('priceToBook'), 1, 'x')} |",
        f"| PEG Ratio | {_fmt_num(info.get('pegRatio'), 2, 'x')} |",
        f"| Dividend Yield | {_fmt_pct(info.get('dividendYield'))} |",
        f"| Beta | {_fmt_num(info.get('beta'), 2)} |",
        "",
        "### Growth & Profitability",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Revenue Growth (YoY) | {_fmt_pct(info.get('revenueGrowth'))} |",
        f"| Earnings Growth (YoY) | {_fmt_pct(info.get('earningsGrowth'))} |",
        f"| Gross Margin | {_fmt_pct(info.get('grossMargins'))} |",
        f"| EBITDA Margin | {_fmt_pct(info.get('ebitdaMargins'))} |",
        f"| Net Profit Margin | {_fmt_pct(info.get('profitMargins'))} |",
        f"| Return on Equity | {_fmt_pct(info.get('returnOnEquity'))} |",
        f"| Return on Assets | {_fmt_pct(info.get('returnOnAssets'))} |",
        f"| Debt / Equity | {_fmt_num(info.get('debtToEquity'), 1, 'x')} |",
        f"| Free Cash Flow | {_fmt_mktcap(info.get('freeCashflow'))} |",
        "",
        "### Sector Valuation Framework",
        f"**Sector:** {sector}",
        f"**Key Metrics for this sector:** {', '.join(framework['primary_metrics'])}",
        f"**Growth-adjusted multiples recommended:** {'Yes (use PEG or forward multiples)' if framework['growth_adjusted'] else 'No (trailing multiples preferred)'}",
        "",
        f"**Framework guidance:** {framework['commentary']}",
    ]

    return "\n".join(lines)


def get_historical_multiples(ticker: str, years: int = 3) -> str:
    """
    Return a table of year-end valuation multiples for the last `years` fiscal years.

    Uses yfinance annual financials + price history to compute:
    - Year-end stock price
    - Trailing P/E (price / EPS)
    - Price/Sales (mkt cap / revenue)
    - EV/EBITDA (approximate: uses year-end price × shares + debt - cash)

    Returns a Markdown table. Missing data rows are shown as N/A.
    """
    stock = yf.Ticker(ticker)
    info = stock.info or {}

    shares = info.get("sharesOutstanding")

    # Fetch annual financials — columns are Timestamps (most recent first)
    try:
        financials = stock.financials  # income statement
        balance_sheet = stock.balance_sheet
    except Exception:
        return "### Historical Multiples\n_Unable to fetch historical financial data._"

    if financials is None or financials.empty:
        return "### Historical Multiples\n_Historical financial data not available for this ticker._"

    cols = list(financials.columns)[:years]  # most recent `years` fiscal year-end dates

    rows = []
    for col in cols:
        year_label = col.strftime("%Y") if hasattr(col, "strftime") else str(col)[:4]

        # Fetch year-end price (last trading day of the fiscal year)
        try:
            col_date = col.date() if hasattr(col, "date") else col
            import datetime
            start = col_date - datetime.timedelta(days=7)
            end = col_date + datetime.timedelta(days=1)
            hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
            year_end_price = float(hist["Close"].iloc[-1]) if not hist.empty else None
        except Exception:
            year_end_price = None

        # Net Income
        net_income = None
        for key in ("Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operations"):
            if key in financials.index:
                val = financials.loc[key, col]
                if val is not None and str(val) not in ("nan", "None"):
                    net_income = float(val)
                    break

        # Total Revenue
        revenue = None
        for key in ("Total Revenue", "Revenue"):
            if key in financials.index:
                val = financials.loc[key, col]
                if val is not None and str(val) not in ("nan", "None"):
                    revenue = float(val)
                    break

        # EBITDA
        ebitda = None
        for key in ("EBITDA", "Normalized EBITDA", "Reconciled Depreciation"):
            if key in financials.index:
                val = financials.loc[key, col]
                if val is not None and str(val) not in ("nan", "None"):
                    ebitda = float(val)
                    break

        # Total Debt and Cash from balance sheet
        total_debt = None
        cash = None
        if balance_sheet is not None and not balance_sheet.empty and col in balance_sheet.columns:
            for key in ("Total Debt", "Long Term Debt"):
                if key in balance_sheet.index:
                    v = balance_sheet.loc[key, col]
                    if v is not None and str(v) not in ("nan", "None"):
                        total_debt = float(v)
                        break
            for key in ("Cash And Cash Equivalents", "Cash", "Cash Cash Equivalents And Short Term Investments"):
                if key in balance_sheet.index:
                    v = balance_sheet.loc[key, col]
                    if v is not None and str(v) not in ("nan", "None"):
                        cash = float(v)
                        break

        # Compute multiples
        pe = None
        if year_end_price and net_income and shares and shares > 0:
            eps = net_income / shares
            if eps > 0:
                pe = year_end_price / eps

        ps = None
        if year_end_price and revenue and shares and shares > 0:
            mktcap = year_end_price * shares
            ps = mktcap / revenue

        ev_ebitda = None
        if year_end_price and ebitda and shares and shares > 0 and ebitda > 0:
            mktcap = year_end_price * shares
            debt = total_debt or 0.0
            c = cash or 0.0
            ev = mktcap + debt - c
            ev_ebitda = ev / ebitda

        price_str = f"${year_end_price:.2f}" if year_end_price else "N/A"
        rows.append(
            f"| {year_label} | {price_str} | {_fmt_num(pe, 1, 'x')} | {_fmt_num(ps, 1, 'x')} | {_fmt_num(ev_ebitda, 1, 'x')} |"
        )

    lines = [
        "### Historical Multiples (Fiscal Year-End)",
        "| Year | Year-End Price | P/E | P/S | EV/EBITDA |",
        "|------|----------------|-----|-----|-----------|",
    ] + rows

    if not rows:
        lines.append("| — | N/A | N/A | N/A | N/A |")

    return "\n".join(lines)


def get_peer_multiples(peer_tickers: list[str]) -> str:
    """
    Build a peer comparables table for a list of ticker symbols.

    Validates each ticker via yfinance; skips tickers with missing data.
    Returns a Markdown table with key multiples.
    """
    header = [
        "### Peer Comparables",
        "| Ticker | Company | Mkt Cap | Trailing P/E | Fwd P/E | EV/EBITDA | P/S | Rev Growth | EBITDA Margin |",
        "|--------|---------|---------|--------------|---------|-----------|-----|------------|---------------|",
    ]

    rows = []
    for ticker in peer_tickers:
        try:
            info = yf.Ticker(ticker).info or {}
            if not info.get("shortName") and not info.get("longName"):
                continue  # empty — ticker not found
            name = (info.get("shortName") or info.get("longName") or ticker)[:28]
            rows.append(
                f"| {ticker.upper()} | {name} "
                f"| {_fmt_mktcap(info.get('marketCap'))} "
                f"| {_fmt_num(info.get('trailingPE'), 1, 'x')} "
                f"| {_fmt_num(info.get('forwardPE'), 1, 'x')} "
                f"| {_fmt_num(info.get('enterpriseToEbitda'), 1, 'x')} "
                f"| {_fmt_num(info.get('priceToSalesTrailingTwelveMonths'), 1, 'x')} "
                f"| {_fmt_pct(info.get('revenueGrowth'))} "
                f"| {_fmt_pct(info.get('ebitdaMargins'))} |"
            )
        except Exception:
            continue  # skip tickers that error

    if not rows:
        return "\n".join(header) + "\n| — | No peer data available | — | — | — | — | — | — | — |"

    return "\n".join(header + rows)
