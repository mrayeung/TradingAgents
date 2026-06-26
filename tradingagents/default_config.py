import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), "tradingagents")

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # OpenAI: "low"/"medium"/"high"/"max"
                                        # OpenRouter (DeepSeek): "xhigh" = max reasoning
                                        # e.g. set to "xhigh" when provider="openrouter"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        # News vendor chain:    finnhub (primary) → google_news (backup) → yfinance (fallback)
        # Sentiment chain:      finnhub (paid)    → stocktwits (free, no key)
        # Requires: FINNHUB_API_KEY in .env  +  pip install finnhub-python feedparser
        "news_data": "finnhub,google_news",
        "social_sentiment": "finnhub,stocktwits",
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },

    # ---------------------------------------------------------------------------
    # Portfolio Construction Extension
    # ---------------------------------------------------------------------------
    "portfolio": {
        # --- Universe ---
        # "sp500"  : screen the full S&P 500 (Wikipedia live fetch + seed fallback)
        # "sector" : screen a single GICS sector (set "sector" key below)
        # "list"   : use a custom ticker list (set "custom_tickers" key below)
        "universe": "sp500",
        "sector": None,           # e.g. "Technology" when universe="sector"
        "custom_tickers": [],     # e.g. ["AAPL","MSFT","NVDA"] when universe="list"

        # --- Screener ---
        # How many tickers the screener pre-filters before the full LLM analysis.
        # For a 100-ticker input, the screener scores all 100 quantitatively and
        # passes only the top pre_analysis_cap to the expensive LLM pipeline.
        # Rule of thumb: set to ~2× max_positions so the LLM has enough to choose from.
        "pre_analysis_cap": 50,
        # Momentum (price strength) vs Quality (financial health) blend
        "momentum_weight": 0.5,
        "quality_weight": 0.5,
        # Parallel workers for screener data fetching
        "screener_max_workers": 10,
        # Seconds between yfinance requests (gentle rate limiting)
        "screener_request_delay": 0.1,
        # Parallel workers for per-ticker LLM analysis (Step 2).
        # Each worker runs one full TradingAgentsGraph pipeline concurrently.
        # 3 is a safe default — raise to 5 if your API tier allows higher RPM.
        "max_analysis_workers": 3,

        # --- Portfolio Construction ---
        # Hard cap on final portfolio holdings — the portfolio will never exceed this
        # regardless of how many tickers were analysed.
        "max_positions": 30,      # Maximum number of holdings
        "min_weight": 0.02,       # Minimum position size (2%)
        "max_weight": 0.15,       # Maximum position size (15%)
        # Minimum agent rating to be considered investable: "Hold", "Overweight", or "Buy"
        "min_rating": "Hold",

        # --- Rebalancing ---
        # Day of month for scheduled monthly rebalance (1 = first of month)
        "rebalance_day": 1,
        # Relative drift threshold to trigger an intra-month rebalance
        # |current_w - target_w| / target_w > drift_threshold → flag for rebalance
        "drift_threshold": 0.25,

        # --- Outputs ---
        # Directory for portfolio Excel + Markdown outputs
        # Defaults to <results_dir>/portfolio if not set
        "output_dir": None,
    },
}
