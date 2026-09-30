# Oasis Portfolio Manager — Product Requirements Document

**Version:** 0.1 (Draft)
**Status:** In Review
**Track:** Long-Term Portfolio Management

---

## 1. Problem Statement

Sophisticated retail investors — people who understand valuation, follow macroeconomics, and think in multi-year horizons — have no tool that matches how they actually think. Robo-advisors are too passive and opaque. Bloomberg/FactSet are built for institutions. Spreadsheets are manual and disconnected from brokers. Financial advisors are expensive and misaligned.

These investors need an AI co-pilot that applies institutional-quality frameworks (macro cycle analysis, sector rotation, CFP monitoring standards, CFA valuation) to their real portfolio — across multiple accounts, multiple brokers, and potentially multiple jurisdictions — and brings them discipline they can't maintain alone.

The goal is not to automate their decisions. It is to surface the right information at the right time, evaluate opportunities systematically, and present clear proposals for human approval.

---

## 2. Target Users

### Primary Persona: The Sophisticated Long-Term Investor
- Manages $100K–$2M+ across 2–4 accounts
- Understands fundamentals, follows macro, thinks in years not months
- Beats the market some years, underperforms others — lacks a repeatable system
- Has accounts at 1–2 brokers; may have cross-border complexity (US + Canada, US + UK)
- Has an IRA or tax-advantaged account alongside a taxable account
- Pain: Makes emotional decisions, overtrades during volatility, doesn't systematically harvest tax losses, has no formal rebalancing discipline

### Secondary Persona: The Cross-Border Professional
- HNW individual with accounts in 2+ countries (common: US/Canada, US/UK, US/Singapore)
- Has RRSP/TFSA alongside IRA/401k
- Pain: Portfolio fragmented across jurisdictions, tax implications poorly understood, no tool handles cross-border account type complexity

### Out-of-Scope User (for MVP): Day traders, options-only traders, crypto-only investors, institutional asset managers.

---

## 3. Goals & Success Metrics

### Product Goals
- Reduce emotional, undisciplined trading decisions
- Surface dislocation opportunities the user would otherwise miss
- Prevent tax mistakes (wash sales, suboptimal lot selection, missed TLH)
- Improve long-term risk-adjusted returns vs benchmark

### Success Metrics (MVP)
| Metric | Target |
|--------|--------|
| Portfolio connections per user | ≥ 2 accounts |
| Weekly active users | ≥ 60% of signups |
| Proposals reviewed per month | ≥ 3 per user |
| Proposals approved (conversion) | ≥ 40% |
| Tax savings identified per year | ≥ $500 per taxable account user |
| User-reported clarity improvement | ≥ 4.2/5 on "I understand my portfolio" |

---

## 4. Core Features — MVP

### 4.1 Portfolio Construction
- Import positions from any connected broker (Schwab, Alpaca, IBKR, Wealthica read-only)
- Manual position entry for unsupported brokers
- Set Investment Policy Statement (IPS) via guided onboarding:
  - Risk tolerance (conservative / balanced / aggressive)
  - Investment horizon
  - Benchmark (default: SPY)
  - Passive core % vs active satellite %
  - Constraints (max position size, sector caps, ESG exclusions)
  - Account type per account (tax-advantaged / taxable / retirement)
  - Jurisdiction per account (US / Canada / UK / other)

### 4.2 Macro Cycle Monitor
- Daily FRED data ingestion: yield curve, ISM PMI, unemployment trend, LEI, consumer confidence, HY credit spreads, CPI, industrial production
- Macro Agent classifies current cycle phase: Early Recovery / Mid Cycle / Late Cycle / Recession
- Outputs confidence score and key driver (e.g. "yield_curve_flattening")
- Triggers sector rotation matrix update when cycle phase changes
- Monthly deep re-run; immediate re-run on threshold-crossing data events (FOMC, CPI surprise)

### 4.3 Sector Rotation Overlay
- 11 GICS sector targets (OW / NW / UW) derived from current cycle phase
- Compares current sector allocation vs targets
- Flags sectors drifted > 3% from target weight
- Generates rebalancing proposals when drift exceeds threshold

### 4.4 Dislocation Scanner
- Monitors holdings and watchlist for -5%+ single-day drops
- Classifies cause: event-based (sympathy selloff, macro data miss, index rebalancing, short attack) or earnings-based (beat, in-line, miss, guidance change)
- Runs 5-Gate qualification: WHY → VALUATION → TECHNICAL → MACRO → POSITION
- Long-term vs short-term lens classifier routes proposal to correct account (IRA for LT, taxable for ST/tax-aware)
- Sector fit check: is this sector OW or UW in current cycle? Adjusts tranche size accordingly
- Tranche entry system: T1 (25%) / T2 (35%) / T3 (40%) at -5% / -10% / -15% from signal price

### 4.5 Proposal Center (Human-in-the-Loop Gate)
- All AI recommendations surface as structured Proposal Cards before any action
- Each card shows: action, symbol, account, reasoning, gate scores, sector fit, tranche, tax impact, estimated execution price
- User can: Approve / Reject / Modify (change size, account, or timing)
- Approved proposals route to broker executor (if connected) or generate manual instructions
- Rejected proposals logged with reason for system learning

### 4.6 Tax Intelligence
- Per-trade tax gate before any proposal is generated:
  - Wash sale checker (30-day window, cross-account including IRA)
  - LTCG vs STCG classifier (365-day threshold)
  - Optimal lot selection (highest cost basis first for taxable losses)
  - Tax-loss harvesting scanner (positions with unrealized losses near year-end)
- Jurisdiction-aware: US (IRS rules), Canada (CRA superficial loss), UK (HMRC bed-and-breakfast)
- Tax impact displayed on every proposal card

### 4.7 Portfolio Monitoring (CFP Charter)
- Daily: IPS breach check (any position > max size, cash below minimum, any stop-loss trigger)
- Weekly: sector drift report, covered call roll alerts, CSP expiry alerts
- Monthly: rebalancing proposals, performance vs benchmark
- Quarterly: full portfolio review report (IPS compliance, attribution, top contributors/detractors)
- 3-level alert system: Watch (informational) / Review (action recommended) / Act (time-sensitive)

### 4.8 Performance & Attribution
- Portfolio return vs benchmark (daily, monthly, YTD, since inception)
- Attribution by: sector, account, strategy (passive core vs active satellite)
- Win rate on dislocation buys by type (event-based vs earnings-based)
- Tax-adjusted return (after estimated tax drag)

---

## 5. User Stories

**As a long-term investor, I want to:**
- See exactly where I am in the economic cycle and which sectors I should overweight right now
- Know immediately when a stock I own or watch drops significantly so I can evaluate whether to buy more
- Get a clear recommendation that says "buy X in your IRA, not your taxable account, because of the tax treatment" — not just "buy X"
- Be told before I trade if a sale would trigger a wash sale or short-term capital gains
- See my portfolio's sector allocation vs my target and get told when to rebalance
- Understand why my portfolio outperformed or underperformed the S&P 500 this quarter

**As a cross-border investor, I additionally want to:**
- See my US and Canadian accounts in a single unified view, in my base currency
- Get proposals that respect the different tax rules in each country
- Know which account to hold which assets in (US dividend stocks in RRSP, not TFSA, etc.)

---

## 6. Out of Scope (MVP)

- Fully autonomous trading (no execution without human approval — ever)
- Social features / copy trading
- Crypto (beyond manual entry)
- Options as a primary strategy (options overlay for CSP/CC is in scope as a secondary feature)
- Financial planning (retirement projections, Monte Carlo simulation) — Phase 2
- Short-term trading / intraday features — separate product (Trading Desk)
- News feed / research reading interface — agents summarize, not raw feed

---

## 7. Technical Requirements

### Broker Connectors (MVP)
| Broker | Type | API |
|--------|------|-----|
| Schwab | Read + Execute | schwab-py (OAuth 2.0) |
| Alpaca | Read + Execute | alpaca-py |
| IBKR | Read + Execute | IBKR MCP / ib_insync |
| Wealthica | Read-only | Wealthica API (Canadian aggregator) |
| Manual | Read-only | User input |

### Data Sources
- Market data: yfinance (prices, sector ETFs)
- Macro: FRED API (already in codebase)
- Fundamentals: Alpha Vantage, SEC EDGAR (already in codebase)
- News: Finnhub, Google News RSS (already in codebase)
- Sentiment: Reddit, Stocktwits (already in codebase)

### Intelligence Engine
- LangGraph StateGraph (existing Oasis Terminal architecture)
- 15 agents including: Macro Agent, Sector RS Monitor, Fundamentals, Technical, News, Sentiment, Bull/Bear, Risk (Agg/Con/Neutral), Portfolio Manager (Black-Litterman), Tax Gate, Dislocation Classifier, 5-Gate Qualifier, Lens Classifier, Reflector
- Markov 2.0 regime detection (existing)
- FastAPI backend (existing desk_server on port 8765)
- Per-user IPS config: `investment_policy.yaml`

### Security & Privacy
- API tokens stored in user-specific `.env` or secrets manager — never committed
- Per-user portfolio state isolated (no cross-user data access)
- All broker credentials encrypted at rest
- Human approval required for every execution — no autonomous trading

---

## 8. Key Interface Screens

1. **Dashboard** — macro cycle indicator, portfolio health score, sector allocation vs target, 3 most recent alerts
2. **Portfolio** — all positions across all accounts, grouped by account, with weight, P&L, lot detail, and sector
3. **Opportunity Center** — ranked list of dislocation alerts and proposals awaiting review
4. **Proposal Review** — structured card for each recommendation; approve / reject / modify
5. **Tax Center** — TLH opportunities, wash sale calendar, LTCG tracker, year-end tax estimate
6. **Performance** — portfolio vs benchmark, attribution breakdown, active satellite vs passive core

---

## 9. Phase 2 (Post-MVP)

- Retirement projections and Monte Carlo simulation
- Options strategy builder (structured covered call and CSP programs)
- Real estate monitoring (REIT allocation, property value tracking)
- Life insurance integration (term vs whole analysis)
- Cross-border tax optimization (FBAR, treaty benefits, form 8938)
- Mobile companion app (alerts and proposal approval on phone)
- Advisor mode (financial advisor manages multiple client portfolios)
