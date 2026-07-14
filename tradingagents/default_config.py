import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), "tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_LLM_MAX_RETRIES":      "llm_max_retries",
    # Provider-specific reasoning/thinking knobs (None = each provider's own
    # default). Settable here for non-interactive runs; the CLI also offers an
    # interactive choice, which is skipped when the matching var is set.
    "TRADINGAGENTS_GOOGLE_THINKING_LEVEL":   "google_thinking_level",
    "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
    "TRADINGAGENTS_ANTHROPIC_EFFORT":        "anthropic_effort",
}


_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value.

    Invalid values raise ``ValueError`` rather than silently falling back to a
    default — a misspelled boolean (e.g. ``treu``) or non-numeric int should fail
    loudly at startup, not quietly misconfigure an unattended run.
    """
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
    return config


DEFAULT_CONFIG = _apply_env_overrides({
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
    "deep_think_llm": "gpt-5.5",
    "quick_think_llm": "gpt-5.4-mini",
    # ---------------------------------------------------------------------------
    # Split-model debate configuration
    # ---------------------------------------------------------------------------
    # When set, the 5 debate nodes (Bull, Bear, Aggressive, Conservative, Neutral)
    # use a separate LLM from the main quick_think_llm.  This enables cross-provider
    # pairing, e.g. Gemini Flash for daytime runs and DeepSeek Flash for batch sweeps,
    # while keeping the deep reasoning model (Research Manager, Portfolio Manager) intact.
    #
    # Set to None to inherit from llm_provider / quick_think_llm / backend_url.
    #
    # Example — Gemini 3 Flash for debate:
    #   "debate_llm_provider": "google",
    #   "debate_llm_model":    "gemini-3-flash",
    #   "debate_backend_url":  None,
    #
    # Example — DeepSeek V4 Flash for overnight batch (direct):
    #   "debate_llm_provider": "deepseek",
    #   "debate_llm_model":    "deepseek-v4-flash",
    #   "debate_backend_url":  "https://api.deepseek.com",
    #
    # ---------------------------------------------------------------------------
    # NVIDIA NIM Pair configurations (free-tier; set NVIDIA_NIM_API_KEY in .env)
    # ---------------------------------------------------------------------------
    # Pair 1 — DeepSeek via NIM:
    #   "llm_provider":        "nvidia_nim",
    #   "deep_think_llm":      "deepseek-ai/deepseek-r1-0528",   # V4 Pro
    #   "quick_think_llm":     "deepseek-ai/deepseek-v3-0324",   # V4 Flash
    #   "debate_llm_provider": "nvidia_nim",
    #   "debate_llm_model":    "deepseek-ai/deepseek-v3-0324",
    #   "debate_backend_url":  None,
    #
    # Pair 2 — GLM via NIM:
    #   "llm_provider":        "nvidia_nim",
    #   "deep_think_llm":      "thudm/glm-z1-32b",               # GLM-5.2
    #   "quick_think_llm":     "thudm/glm-4-9b-chat",            # GLM-4.7 Flash
    #   "debate_llm_provider": "nvidia_nim",
    #   "debate_llm_model":    "thudm/glm-4-9b-chat",
    #   "debate_backend_url":  None,
    "debate_llm_provider": None,
    "debate_llm_model":    None,
    "debate_backend_url":  None,
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
    # Sampling temperature, forwarded to every provider when set. None leaves
    # each provider at its own default. Lower values reduce run-to-run
    # variation on models that honor it; reasoning models largely ignore it
    # and no setting makes LLM output bit-identical across runs (see README).
    "temperature": None,
    # SDK retry budget forwarded to every provider chat client. None leaves each
    # provider/SDK at its own default (usually 2). Raise it to ride out bursty
    # 429 throttling on rate-limited deployments instead of aborting a run (#1091).
    "llm_max_retries": None,
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
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category).
    # The configured value is the exact vendor chain — requests are NOT silently
    # routed to vendors you didn't choose. For ordered fallback, list several,
    # e.g. "yfinance,alpha_vantage". "default" uses all available vendors.
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "sec_data": "sec_edgar",             # SEC EDGAR — free, no key required
        # News vendor chain:    finnhub (primary) → google_news (backup) → yfinance (fallback)
        # Sentiment chain:      finnhub (paid)    → stocktwits (free, no key)
        # Requires: FINNHUB_API_KEY in .env  +  pip install finnhub-python feedparser
        "news_data": "finnhub,google_news",
        "social_sentiment": "finnhub,stocktwits",
        "macro_data": "fred",                # Options: fred (needs FRED_API_KEY)
        "prediction_markets": "polymarket",  # Options: polymarket (keyless)
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

    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",       # NSE India (Nifty 50)
        ".BO":  "^BSESN",      # BSE India (Sensex)
        ".T":   "^N225",       # Tokyo (Nikkei 225)
        ".HK":  "^HSI",        # Hong Kong (Hang Seng)
        ".L":   "^FTSE",       # London (FTSE 100)
        ".TO":  "^GSPTSE",     # Toronto (TSX Composite)
        ".AX":  "^AXJO",       # Australia (ASX 200)
        ".SS":  "000001.SS",   # Shanghai (SSE Composite)
        ".SZ":  "399001.SZ",   # Shenzhen (SZSE Component)
        "":     "SPY",         # default for US-listed tickers (no suffix)
    },
})
