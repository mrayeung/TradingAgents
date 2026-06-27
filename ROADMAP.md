# TradingDesk Roadmap

A personal portfolio research platform that combines multi-agent LLM analysis, institutional-grade portfolio construction, and real-time market intelligence — built on top of the open-source TradingAgents framework.

---

## What We Built (v1.0)

Starting from the TradingAgents open-source base, the following layers were designed and shipped:

**Multi-Agent Research Engine**
- Market, Sentiment, News, Fundamentals, Valuation, and Market Technician analysts
- Quantitative analyst (Markov 2.0 regime + edge detection)
- Self-contained valuation analyst with peer comparables and agentic tool loop (fixed GraphRecursionError)
- Finnhub news pipeline with Google News RSS fallback and SEC EDGAR integration

**Investment Debate Layer** (HedgeFund architecture)
- Bull Researcher → Bear Researcher → Research Manager synthesis
- Aggressive / Conservative / Neutral risk analysts → Portfolio Manager final decision
- Two-model routing: Gemini 3 Flash Preview for advocate nodes (serial TTFT optimisation), GPT-5.4 mini for risk analyst nodes (FinanceBench-optimised financial table parsing)
- Env-var config pattern (`TRADINGAGENTS_ADVOCATE_LLM_*` / `TRADINGAGENTS_RISK_LLM_*`) — swap models without touching code

**Portfolio Construction**
- Black-Litterman + mean-variance optimisation with analyst conviction as views
- Kelly criterion position sizing with correlation penalty
- Portfolio benchmark comparison vs SPY / QQQ / DIA
- Rebalance trade list with delta weights and dollar amounts

**Intelligence Layers**
- 13F Institutions Tracker — 50+ major funds, holdings, sector concentration, recent additions/exits
- Options Action page — IV surface, unusual flow detection, put/call ratio, trade ideas
- Reports Library — full analyst write-ups, debate transcripts, final decisions, collapsible reader

**Infrastructure**
- FastAPI desk-server (Docker) with serialised run executor (max_workers=1, avoids env key races)
- Run status lifecycle: queued → warming → started → done/error/cancelled
- Next.js web frontend with sidebar navigation
- Env-var override system for all config keys (`TRADINGAGENTS_*`)
- Reddit RSS + Finnhub sentiment with 429 backoff and fallback chain

---

## Next Milestones

### P0 — High Impact, Relatively Small Effort

**Parallel analyst execution**
The biggest single performance improvement available. Market, Sentiment, News, and Technician analysts are fully independent and can fan-out simultaneously in LangGraph. Fundamentals and Valuation can then run in a second parallel wave. Expected reduction: 8–10 min → 3–4 min per run.

Files: `tradingagents/graph/setup.py`, `tradingagents/graph/analyst_execution.py`

**Real-time SSE progress in the UI**
The desk-server already emits SSE events per analyst completion and per stats update — the web frontend ignores them and polls `/state` every 8 seconds. Wiring the SSE stream to the signals page would show "Running: News Analyst… (42s)" with a live elapsed timer and per-analyst completion checkmarks.

Files: `web/src/app/portfolio/signals/page.tsx`, new `useRunStream` hook

**CCI indicator cleanup**
`Indicator cci is not supported` appears in every run log — the market technician prompt requests CCI which yfinance doesn't support. Benign but wastes a tool call round-trip. Remove from prompt or remap to MFI (Money Flow Index), which is the closest supported substitute.

Files: `tradingagents/agents/analysts/market_technician.py`

---

### P1 — High Impact, Moderate Effort

**Adaptive staleness + watchlist**
A watchlist of tickers the system auto-analyzes on a schedule (e.g., every Monday morning). Pair with adaptive staleness: high-volatility names refresh every 3–5 days, stable blue chips every 2–3 weeks based on realised volatility from yfinance.

Files: new `desk_server/watchlist.py`, `web/src/app/portfolio/watchlist/page.tsx`

**Portfolio drift tracking**
The rebalance page generates correct trades but doesn't know what you actually hold. A "current holdings" input (manual CSV or broker API) lets the system show live drift vs. target allocation over time — turning the construct page from a one-off optimizer into a continuous portfolio tracker.

Files: `web/src/app/portfolio/construct/page.tsx`, new holdings persistence layer

**Options flow feeding into the debate**
The Options Action page surfaces unusual IV and flow but the signal is siloed — advocate nodes don't see it. Injecting a summarised options flow reading ("Unusual call buying at the $52 strike, 3× average volume, 2 weeks to expiry") into the bull/bear advocate prompt would make the debate more grounded in what informed money is positioning for.

Files: `tradingagents/agents/researchers/bull_researcher.py`, `bear_researcher.py`, `tradingagents/graph/trading_graph.py`

**Cost and performance dashboard**
`StatsCallbackHandler` already tracks token counts and LLM latency per run — that data is collected but never surfaced. A cost breakdown view (tokens per analyst, advocate vs. risk LLM cost per run, monthly spend) would help tune model choices with real data rather than FinanceBench benchmarks.

Files: new `web/src/app/portfolio/costs/page.tsx`, `desk_server/app.py` (expose stats endpoint)

---

### P2 — Meaningful, Deeper Effort

**Report diffing**
When FCX is run twice three weeks apart, the current system overwrites the previous signal. A diff view showing what changed between reports (sentiment shifted bearish, valuation moved from undervalued to fairly valued, bear argument now cites rising inventory) explains why a position's conviction changed — essential for building trust in the system's reasoning.

Files: new `web/src/app/portfolio/reports/[ticker]/diff/page.tsx`, diff logic in `desk_server/app.py`

**Concurrent runs (remove max_workers=1 constraint)**
The serialised executor exists because API keys are injected via `os.environ` and two concurrent runs would race. The correct fix is to pass keys as constructor arguments to `TradingAgentsGraph` rather than through the environment. This unblocks running 2–3 tickers simultaneously and enables batch sweeps across a full watchlist.

Files: `desk_server/runner.py`, `tradingagents/graph/trading_graph.py`, `desk_adapter/env.py`

**Macro regime injection**
The quantitative analyst does regime detection per-ticker but macro context (Fed rate cycle, VIX regime, yield curve shape) isn't injected into the debate. A shared macro briefing prepended to all analyst prompts would anchor the debate in the current market environment rather than analysing each ticker in isolation.

Files: `tradingagents/graph/trading_graph.py` (initial state), new `tradingagents/dataflows/macro_briefing.py`

---

## Architecture Notes

**Model routing (as of v1.0)**
```
Advocate nodes (Bull/Bear)         → google/gemini-3-flash-preview  via OpenRouter
Risk analyst nodes (Agg/Con/Neu)   → openai/gpt-5.4-mini            via OpenRouter
Research Manager / Portfolio Mgr   → deep_think_llm (main config)
All research analysts              → quick_think_llm (main config)
```

**Run serialisation**
Runs execute one at a time on `ThreadPoolExecutor(max_workers=1)`. Status lifecycle: `queued → warming → started → done`. Queued runs are visible in the UI with "Queued — waiting for active run" label.

**Config override pattern**
All engine config keys are overridable via `TRADINGAGENTS_*` environment variables defined in `_ENV_OVERRIDES` in `default_config.py`. No code changes needed to swap providers, models, or debate parameters.

---

## Contributing

Branch: `pr-1077`
Remote: `github.com/mrayeung/TradingAgents`

```bash
cd ~/projects/agents/TradingDesk-preview
git add -A
git commit -m "feat: <description>"
git push origin pr-1077
```
