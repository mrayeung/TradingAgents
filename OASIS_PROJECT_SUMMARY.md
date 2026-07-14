# Oasis Terminal — Project Summary & Handover
*Generated July 2026 · Covers all planning and architecture decisions from this Cowork session*

---

## 1. What This Project Is

**TradingAgents** is the Python multi-agent research engine.  
**TradingDesk-preview** is the Next.js frontend (already built, running locally).  
**Oasis Terminal** is the commercial product brand that wraps both.

The goal: transform the multi-agent debate engine into a full portfolio intelligence product with investable candidates, AI-generated debate views, risk-aware weights, and rebalance recommendations — distributed via a Next.js product (primary) and OpenBB Terminal Pro (distribution channel).

---

## 2. What's Already Built (Completed Tasks)

### Backend — TradingAgents Python engine
- **7 analyst agents**: `fundamentals_analyst.py`, `market_analyst.py`, `market_technician.py`, `news_analyst.py`, `quantitative_analyst.py`, `social_media_analyst.py`, `valuation_analyst.py`
- **3 researcher agents**: `bull_researcher.py`, `bear_researcher.py`
- **3 risk debate agents**: `aggressive_debator.py`, `conservative_debator.py`, `neutral_debator.py`
- **Managers**: `portfolio_manager.py` (structured output via `PortfolioDecision` Pydantic schema)
- **Portfolio engine**: `tradingagents/portfolio/` — `correlation.py`, `dashboard.py`, `output.py`
- **Signal processing**: `signal_processing.py` → `SignalProcessor.process_signal()` extracts 5-tier rating
- **Structured schemas**: `agents/schemas.py` — `PortfolioDecision`, `ResearchPlan`, `TraderProposal`, all with Pydantic + render helpers
- **Debate LLM**: separate `debate_llm` config keys in `default_config.py`, dedicated client in `trading_graph.py`, wired into all 5 debate nodes with guardrail prompts
- **Markov 2.0 quantitative analyst**: regime detection + edge scoring feeding into debate context

### Frontend — TradingDesk-preview (Next.js)
- Signal Dashboard page
- Portfolio Construction + Weights page
- Benchmark, Correlation, Rebalance pages
- Institutions tile grid + detail page (SEC EDGAR 13F data)
- Options Action page
- Cross-asset Macro Dashboard
- Renaissance Pairs Trading page
- Sidebar navigation for all above
- FastAPI backend (`desk_server/app.py`) with CORS + all endpoints including `/pairs/thesis`

### Documents
- `Oasis_Terminal_PRD_v1.0.docx` — 16-section PRD including:
  - Section 9: Phase plan (Phases 1-10)
  - Section 14: Creator economy
  - Section 15: System architecture & scale design (6 subsections, scale tiers, microservices, caching TTL taxonomy, security controls, LLM token optimization, self-hosted models)
  - Section 16: Appendix with quarterly constants

---

## 3. Product Strategy — Path C

**Three distribution paths were evaluated:**
- Path A: Next.js only (own user relationship, high CAC, full control)
- Path B: OpenBB only (worst monetization, OpenBB owns users)
- **Path C (chosen): Both** — Next.js = primary product, OpenBB = distribution channel, same FastAPI backend

**Critical gating rule:** OpenBB plugin must require Oasis account for any substantive feature. Free tier gets 4 widgets. Gate Alpha Zoo, signal history, debate view, portfolio tools behind Oasis auth to convert OpenBB users into registered Oasis users.

---

## 4. Reordered Build Sequence (Path C — Product First)

### Phase A — Next.js Product + Vibe-Trading AI (Weeks 1–8, localhost)
Run on yfinance locally. No production infra needed yet.

| Week | Work |
|------|------|
| W1-3 | Next.js auth pages (login, signup, forgot password) + onboarding wizard |
| W2-3 | Billing UI shell — subscription page, plan comparison, upgrade prompts (Stripe test keys) |
| W3-5 | Alpha Zoo integration (pip install vibe-trading-ai[factors]) — 456 factors feeding analyst agents |
| W5-6 | Context compression L3/L5 (Vibe-Trading pattern) — 40K token threshold, 65-75% reduction |
| W6-8 | Persistent memory / Living thesis — per-ticker thesis file, incremental updates, FTS5 search |
| W7-8 | Marketing landing page (localhost preview) |

### Phase B — OpenBB Widget Development (Weeks 5–10, parallel, localhost)
Build all 14 widgets. Test in OpenBB Terminal Pro dev workspace (supports localhost URLs).

| Week | Work |
|------|------|
| W5-6 | widgets.json + apps.json scaffold. @register_widget decorator. Ticker sync via groups. |
| W7-8 | Feature gate logic — Free (4 widgets), Student (10), Individual (14). Coded but bypassed locally. |
| W9-10 | Account CTA flow — free tier limit hit → Oasis sign-up prompt |
| W10 | Full 14-widget integration test in OpenBB dev workspace |

### Phase C — Infrastructure + Monetization (Weeks 9–14)
**Hard gate: OpenBB public launch cannot happen until Phase C is complete.**

| Week | Work |
|------|------|
| W9-10 | Hetzner CX41 deploy. Nginx + SSL. Public backend URL. Switch yfinance → Polygon.io. Redis. |
| W10-11 | TimescaleDB + 5yr OHLCV backfill. APScheduler nightly jobs. |
| W11-12 | Polygon.io WebSocket. Redis pub/sub. Live Z-scores. |
| W12-13 | Supabase Auth (prod). API key generation. JWT middleware on all FastAPI endpoints. |
| W13-14 | Stripe live keys. Subscription webhooks. Plan tier enforcement. Usage tracking. |

### Phase D — Public Launch (Week 15, both surfaces simultaneously)
Next.js + OpenBB go live on same day. One launch story.

### Phase E — API Tier + MCP + Community (Week 16+)
- Developer docs site (Scalar/Mintlify). API tier $49-99/mo.
- MCP server — Oasis tools for Claude Desktop, Cursor. Publish to MCP registry.
- Creator economy (Section 14 PRD). Stripe Connect. FINRA BrokerCheck verification.

---

## 5. Monetization — Stripe Setup

### Existing Stripe env vars and their tier mapping:

| Stripe Env Var | Display Name | Price |
|----------------|--------------|-------|
| `STRIPE_FREE_PRICE_ID` | Free | $0 forever |
| `STRIPE_STUDENT_PRICE_ID` | Student (annual) | ~$120/yr |
| `STRIPE_STUDENT_MONTHLY_PRICE_ID` | Student (monthly) | ~$12/mo |
| `STRIPE_FAMILY_LITE_PRICE_ID` | Individual (monthly) | ~$39/mo |
| `STRIPE_FAMILY_PRO_PRICE_ID` | Pro / Team (monthly) | ~$99/mo |
| `STRIPE_SECRET_KEY` | Backend Stripe client | — |
| `STRIPE_WEBHOOK_SECRET` | Webhook validation | — |

**Note:** "Family" naming in Stripe is from a previous product. UI displays these as Free / Student / Individual / Pro — the display name is decoupled from the price ID.

**Missing:** Annual price IDs for Individual and Pro tiers. Either create `STRIPE_INDIVIDUAL_ANNUAL_PRICE_ID` / `STRIPE_PRO_ANNUAL_PRICE_ID`, or apply a 20% annual coupon at Stripe Checkout (simpler to start).

### Feature gates per tier:

| Feature | Free | Student | Individual | Pro |
|---------|------|---------|------------|-----|
| Signal scanner | 5 tickers | 20 tickers | Unlimited | Unlimited |
| Signals/day | 3 | 10 | Unlimited | Unlimited |
| Debate view | ✗ | ✓ | ✓ | ✓ |
| Portfolio construction | ✗ | ✓ | ✓ | ✓ |
| Alpha Zoo factors | ✗ | ✗ | ✓ | ✓ |
| Options overlay | ✗ | ✗ | ✓ | ✓ |
| All 14 OpenBB widgets | 4 only | 10 | 14 | 14 |
| REST API access | ✗ | ✗ | ✗ | ✓ |
| Team seats | 1 | 1 | 1 | 5 |

---

## 6. Vibe-Trading Integration (MIT, 18.5k stars)

**Source:** https://github.com/HKUDS/Vibe-Trading

Three components worth integrating. The backtesting engine is tightly coupled to their agent loop — do NOT try to extract it. Use vectorbt for backtesting instead.

### 6A. Alpha Zoo — 456 pre-built quantitative factors
- `qlib158`: Microsoft Qlib Alpha158 (154 factors, Apache-2.0)
- `alpha101`: WorldQuant 101 Formulaic Alphas
- `gtja191`: Guotai Junan 191 short-horizon factors
- `academic`: Fama-French 5 + Carhart momentum

**Integration:** `pip install vibe-trading-ai[factors]`. Wire `ZooSignalEngine` to produce factor z-scores per ticker. Inject as structured input into analyst agent context. Expose as "Alpha Zoo" widget in OpenBB (Pro tier) and as a panel in Next.js ticker deep dive.

### 6B. Context Compression L3/L5
- L3 auto_compact: LLM-generated structured summary at 40K token threshold
- Fixed sections: Goal, Constraints, Progress, Key Decisions, Resolved Questions, Pending Asks, Relevant Files, Remaining Work, Critical Context
- L5 iterative update: Nth compression updates previous summary (prevents info decay)
- Target: 65-75% token reduction per signal call

**Integration:** Adopt the structured summary template. Set 40K token threshold as compaction trigger. Each analyst sub-report summarised to bullets before entering synthesis context.

### 6C. Persistent Memory / Living Thesis
- Per-ticker thesis file (bull case, bear case, key risks, price target, confidence)
- New analysis updates changed sections only — incremental, not full regeneration
- SQLite FTS5 full-text search across all theses
- Storage layer for signal outcome logging (Phase 5 data moat)

**This is the "Living Thesis Document" pattern** described in PRD Section 15.6.

---

## 7. OpenBB Integration Architecture

**Source:** https://github.com/OpenBB-finance/OpenBB

OpenBB Terminal Pro widget protocol:
- `GET /widgets.json` — manifest of available widgets
- `GET /apps.json` — layout definitions with cross-widget param sync (`groups`)
- Data endpoints: return `List[Dict]` for tables, Plotly dict for charts
- CORS must include `https://pro.openbb.co` and `http://localhost:1420`
- `@register_widget` decorator pattern: co-locates widget config with endpoint

### 14 Oasis widgets planned across 5 tabs:
1. **Signals tab**: Signal Scanner, Signal Score Card, Debate View
2. **Analysis tab**: Alpha Zoo Factors, Valuation Score, Earnings Calendar
3. **Portfolio tab**: Portfolio Weights, Rebalance Recommendations, Pairs Z-Score
4. **Macro tab**: Macro Pulse, Sector Rotation, Yield Curve
5. **Options tab**: Options Flow, Volatility Surface

### Cross-widget ticker sync:
`groups` field in `apps.json` propagates ticker changes across all tabs simultaneously.

---

## 8. Report Format → UI Mapping

The existing `final_state` from `trading_graph.py` already contains everything the UI needs. **No new LLM calls required.** One new endpoint needed.

| Existing field | → | UI component |
|---|---|---|
| `investment_debate_state["bull_history"]` | → | Bull analyst panel |
| `investment_debate_state["bear_history"]` | → | Bear analyst panel |
| `risk_debate_state["judge_decision"]` | → | Risk officer panel |
| `PortfolioDecision.rating` | → | Signal badge (Buy→85, OW→68, Hold→50, UW→32, Sell→15) |
| `PortfolioDecision.executive_summary` | → | Conviction banner |
| `PortfolioDecision.investment_thesis` | → | Living thesis body |
| `PortfolioDecision.price_target` | → | Price target display |
| `TraderProposal.stop_loss` | → | Risk officer stop-loss |
| `TraderProposal.position_sizing` | → | Suggested weight |

**Gap to fix:** `desk_server/app.py` currently returns `final_trade_decision` as rendered markdown (via `render_pm_decision()`). Add a `/signal/{ticker}/structured` endpoint returning raw JSON fields. Keep existing markdown endpoint unchanged.

```python
# Add to desk_server/app.py
RATING_TO_SCORE = {"Buy": 85, "Overweight": 68, "Hold": 50, "Underweight": 32, "Sell": 15}

@router.get("/signal/{ticker}/structured")
async def get_signal_structured(ticker: str):
    state = await run_or_fetch_cached(ticker)
    decision = state["_portfolio_decision"]   # store raw Pydantic obj alongside markdown
    return {
        "rating":            decision.rating.value,
        "score":             RATING_TO_SCORE[decision.rating.value],
        "executive_summary": decision.executive_summary,
        "investment_thesis": decision.investment_thesis,
        "price_target":      decision.price_target,
        "time_horizon":      decision.time_horizon,
        "bull_history":      state["investment_debate_state"]["bull_history"],
        "bear_history":      state["investment_debate_state"]["bear_history"],
        "risk_decision":     state["risk_debate_state"]["judge_decision"],
        "stop_loss":         state["_trader_proposal"].stop_loss,
        "position_sizing":   state["_trader_proposal"].position_sizing,
    }
```

---

## 9. Model Routing (Runtime LLM Config)

Recommended model routing for Oasis signal engine:

| Role | Model | Why |
|------|-------|-----|
| `analyst_llm` | `claude-sonnet-5` | Speed + intelligence for 7 analyst agents |
| `debate_llm` | `claude-opus-4-8` | Deep reasoning for bull/bear/risk debate |
| `screening_llm` | `claude-haiku-4-5` | Fast screening, high volume |
| `synthesis_llm` | `claude-sonnet-5` | Portfolio manager synthesis |
| `fallback_llm` | `claude-fable-5` | Complex edge cases, 1M context |

Current pricing (July 2026):
- `claude-fable-5`: $10/$50/MTok, 1M context, always-on adaptive thinking
- `claude-opus-4-8`: $5/$25/MTok, 1M context
- `claude-sonnet-5`: $2/$10/MTok intro (through Aug 31, then $3/$15)
- `claude-haiku-4-5-20251001`: $1/$5/MTok, 200k context

---

## 10. UI Design Decisions

### User experience paradigm
- **TradingView**: chart-first, user forms their own thesis from technicals
- **Oasis**: signal-first, agents debate and form the thesis, user evaluates and decides
- Chart is present but secondary — a supporting element, not the hero

### Four key screens
1. **Morning brief / Dashboard**: Portfolio MTD, new signals count, rebalance alerts, VIX
2. **Signal scanner**: Table with score bars, conviction, 30d returns, factor confirmation
3. **Ticker deep dive** (hero screen): Conviction banner → 3-column debate (bull/bear/risk) → chart + metrics → Alpha Zoo factor grid
4. **Portfolio**: Holdings with drift indicators and rebalance action per position

### Next.js BFF pattern (recommended over direct API calls)
```
Next.js browser → Next.js API routes → FastAPI backend
```
Reasons: FastAPI URL stays private, API keys injected server-side, BFF shapes response for UI (merges signal + thesis + factors into one payload).

OpenBB widgets call FastAPI directly (required by widget protocol).

### Who owns what
- **Next.js product**: Oasis owns everything — domain, session, users, every pixel
- **OpenBB workspace**: OpenBB owns the container; Oasis owns widget contents only

---

## 11. Data Feed Strategy

Current (free tier, development):
- `yfinance` — equity prices, options chain
- `FRED` — macro data (VIX, yields, FX)
- `CBOE` — implied correlation indices (ICJ, ICK)

Planned upgrade (production):
- `Polygon.io` — real-time WebSocket, options, crypto, commodities (bundled plan)
- `EODHD` ($20/mo) — international markets (TSX, Euronext, XETRA, LSE, Tokyo, HK, Singapore, ASX, Korea)

---

## 12. Key Files & Locations

```
TradingAgents/
├── tradingagents/
│   ├── agents/
│   │   ├── analysts/           # 7 analyst agents
│   │   ├── researchers/        # bull_researcher.py, bear_researcher.py
│   │   ├── risk_mgmt/          # aggressive, conservative, neutral debators
│   │   ├── managers/           # portfolio_manager.py
│   │   ├── portfolio/          # trader.py
│   │   ├── schemas.py          # PortfolioDecision, ResearchPlan, TraderProposal
│   │   └── utils/              # rating.py, agent_utils.py, data tools
│   ├── graph/
│   │   ├── trading_graph.py    # main orchestrator, debate_llm wired here
│   │   ├── setup.py            # GraphSetup, debate node wiring
│   │   ├── signal_processing.py # SignalProcessor → parse_rating()
│   │   ├── portfolio_graph.py  # portfolio construction graph
│   │   └── reflection.py       # memory/reflection loop
│   └── portfolio/              # correlation.py, dashboard.py, output.py
├── Oasis_Terminal_PRD_v1.0.docx  # 16-section PRD
└── OASIS_PROJECT_SUMMARY.md       # this file

TradingDesk-preview/
└── web/
    ├── app/                    # Next.js pages
    │   ├── signals/            # Signal Dashboard
    │   ├── portfolio/          # Portfolio Construction, Pairs, Rebalance
    │   ├── institutions/       # 13F viewer
    │   ├── options/            # Options Action
    │   └── macro/              # Macro Dashboard
    └── desk_server/            # FastAPI backend
        └── app.py              # All endpoints + CORS
```

---

## 13. Immediate Next Steps (Priority Order)

1. **Add `/signal/{ticker}/structured` endpoint** to `desk_server/app.py` — exposes raw `PortfolioDecision` + debate history as JSON for the UI (see Section 8 above)
2. **Build Next.js auth pages** — login, signup, onboarding wizard (Phase A, W1-3)
3. **Integrate Alpha Zoo** — `pip install vibe-trading-ai[factors]`, wire into analyst context (Phase A, W3-5)
4. **Build the Ticker Deep Dive page** in Next.js — conviction banner, 3-column debate view, factor scores
5. **Start OpenBB widget scaffold** — widgets.json, apps.json, @register_widget on existing endpoints (Phase B, W5-6)
6. **Wire Stripe test keys** — billing UI shell, plan tier feature flags (no live payments yet)

---

## 14. Architecture Reference Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Data Sources                          │
│  yfinance │ Polygon.io │ FRED │ CBOE │ SEC EDGAR │ News │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│              TradingAgents Engine (Python)                │
│                                                          │
│  7 Analysts → Bull/Bear debate → Risk debate             │
│  └─ Alpha Zoo (Vibe-Trading) feeds analyst context       │
│  └─ L3/L5 compression reduces token usage 65-75%        │
│                                                          │
│  Portfolio Manager → PortfolioDecision (structured)      │
│  └─ Living Thesis (Vibe-Trading memory) persists state   │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│              FastAPI Backend (desk_server)                │
│                                                          │
│  /signal/{ticker}/structured  → UI JSON                  │
│  /portfolio/weights           → allocation data          │
│  /pairs/thesis                → pairs signals            │
│  /options/{ticker}            → options chain            │
│  /widgets.json                → OpenBB manifest          │
│  /apps.json                   → OpenBB layouts           │
└────────┬──────────────────────────────┬─────────────────┘
         │                              │
┌────────▼────────┐           ┌─────────▼──────────────────┐
│  Next.js Product │           │  OpenBB Terminal Pro        │
│  (primary)       │           │  (distribution channel)     │
│                  │           │                             │
│  Auth + billing  │           │  14 widgets                 │
│  Ticker deep dive│           │  Feature gating             │
│  Portfolio view  │           │  Account CTA                │
│  Landing page    │           │  Ticker sync (groups)       │
└──────────────────┘           └─────────────────────────────┘
         │                              │
         └──────────────────────────────┘
                      │
              Oasis account required
              (converts OpenBB users
               into owned users)
```

---

*Summary covers: completed builds (Tasks 6-40), Oasis Terminal PRD (16 sections), Path C strategy, reordered build sequence, Vibe-Trading integration plan, OpenBB widget architecture, report→UI field mapping, Stripe tier mapping, model routing, and UI design decisions.*
