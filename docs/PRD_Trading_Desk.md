# Oasis Trading Desk — Product Requirements Document

**Version:** 0.1 (Draft)
**Status:** In Review
**Track:** Short-Term Active Trading

---

## 1. Problem Statement

Disciplined short-term traders — people who have studied setups, developed a playbook, and understand risk management — still fail systematically. Not because their edge is wrong. Because they can't execute their own rules consistently. They overtrade when bored, hold through stops when emotional, take setups that don't qualify, and miss setups when they're distracted. They also have no systematic way to measure which of their setups actually make money.

The Trading Desk solves the execution and measurement problem. It does not pick the trader's strategy. It takes their strategy, scans for qualifying setups, calculates correct position size, enforces risk rules, and records every trade against the original thesis — so the trader finally knows what works.

The insight from SMB Capital and professional trading firms: profitable traders run a small playbook of 3–7 setups they know deeply. They don't try to trade everything. They trade their edge with discipline, every time, and they measure it rigorously. Oasis Trading Desk is the infrastructure that makes this possible for the retail active trader.

---

## 2. Target Users

### Primary Persona: The Playbook Trader
- Trades 1–5 days per week, primarily swing trades (1–10 days holding period)
- Has developed 3–7 repeatable setups through experience or study (SMB Capital, Investors Underground, etc.)
- Uses a separate account for trading (distinct from long-term investments)
- Pain: Breaks their own rules, can't consistently identify qualifying setups pre-market, no systematic trade journal, doesn't know which setups are actually profitable vs which ones feel profitable

### Secondary Persona: The Aspiring Systematic Trader
- Has trading ideas but no formal playbook
- Wants to build one through systematic tracking and measurement
- Will use the Playbook Builder to formalize setups and the Trade Journal to discover their actual edge

### Out-of-Scope User (for MVP): High-frequency traders, algorithmic traders, options-only traders, long-term investors (separate product: Portfolio Manager).

---

## 3. Core Principle: Strategy Agnostic

**The Trading Desk does not impose a strategy.** The trader brings their edge. The platform provides:
- Infrastructure to define and codify any strategy (the Playbook)
- Scanning to find stocks matching each setup
- Discipline enforcement (daily loss limits, position sizing, setup qualification)
- Measurement to show which setups actually work

A momentum trader and a mean-reversion trader use the same platform with different playbook configs. Neither is more "correct." The platform is neutral.

---

## 4. Goals & Success Metrics

### Product Goals
- Reduce rule-breaking (taking unqualified setups, ignoring stops)
- Surface qualifying setups the trader would otherwise miss
- Make the trader's actual edge measurable (win rate by setup type)
- Enforce daily loss limit — the single most important risk rule

### Success Metrics (MVP)
| Metric | Target |
|--------|--------|
| Daily active usage | ≥ 70% of trading days |
| Setups reviewed per trading day | ≥ 3 from scanner |
| Trades that match playbook setups | ≥ 85% of all trades taken |
| Daily loss limit enforced | 100% — hard block on new entries |
| Trade journal completion rate | ≥ 90% of trades logged |
| User-reported discipline improvement | ≥ 4.0/5 on "I trade my plan better" |

---

## 5. Core Features — MVP

### 5.1 Playbook Builder
The trader's strategy codified as structured rules. Each setup is a named entry in the playbook with:

```yaml
setup_name: "Earnings Gap Hold"
category: "earnings_catalyst"
holding_period: "2-5 days"
entry_trigger:
  - earnings_beat: true          # beat on EPS + Revenue
  - guidance: "raised"           # raised guidance required
  - gap_pct_min: 5               # gap up at least 5%
  - gap_holds_minutes: 30        # gap holds first 30 min of trading
entry_method: "day2_pullback"    # enter on pullback day 2, not gap day
stop_rule: "below_gap_day_low"
target_rule: "prior_resistance"
min_rr: 2.0                      # minimum 2:1 reward-to-risk
max_size_pct: 0.02               # risk max 2% of account on this setup
```

- Guided setup builder (no YAML required — form-based UI generates it)
- Template library: pre-built setup templates for common strategies (earnings gap, news catalyst, sector momentum, sympathy selloff, breakout continuation, VWAP reclaim)
- Trader can modify templates or build from scratch
- Unlimited setups per playbook

### 5.2 Morning Pre-Market Dashboard
Each trading day, before market open:
- **In-Play List**: stocks with significant pre-market moves (gap up/down 3%+), with catalyst identified (earnings, news, FDA, macro)
- **Playbook Match**: for each in-play stock, which of the trader's setups (if any) it matches, with match score
- **Setup Quality Score**: 0–100 score for each matched setup — how cleanly does this stock fit the setup criteria?
- **Macro Filter**: current Markov regime (Risk-On / Risk-Off) — Risk-Off reduces recommended size by 50%
- **Earnings Calendar**: upcoming earnings for any watchlist stock

### 5.3 Setup Scorer
When a stock triggers a potential setup:
- Evaluates each entry condition in the setup config (pass / fail / partial)
- Calculates overall setup quality score (0–100)
- Score < 60: do not take the trade (display clear warning)
- Score 60–80: standard size
- Score 80–100: can size up to 1.25x (if within account risk limits)
- Shows which conditions passed and which failed — trader sees exactly why a setup qualifies or doesn't

### 5.4 Position Sizer
Risk-based sizing — not fixed share count or fixed dollar amount:

```
Account size: $50,000
Per-trade risk: 0.5% = $250 max loss per trade
Entry: $48.00 | Stop: $45.60 | Risk per share: $2.40
Shares to buy: $250 / $2.40 = 104 shares
Dollar value: $4,992 (10% of account — auto-capped at setup max)
```

- Auto-calculated from account size, stop level, and setup's max risk %
- Displayed clearly before every trade entry
- Adjusts automatically if stop moves (e.g. trailing stop)
- Cross-checks against account buying power from broker

### 5.5 Daily Loss Limit Monitor
**The most important risk feature.** Prominent, always-visible display of:
- Today's P&L (realized + unrealized)
- Daily loss limit (user-defined, e.g. -2% of account)
- Distance remaining to limit
- Hard enforcement: when limit is reached, new entry proposals are blocked and a clear stop-trading alert fires

The daily loss limit is the single most cited rule that separates profitable traders from losers. The platform enforces it with no exceptions.

### 5.6 Active Trade Monitor
For each open position:
- Entry price, current price, P&L in $ and %
- Stop level (highlighted red if price approaches within 1%)
- Target level (highlighted green if price approaches within 1%)
- Time in trade (flags if holding longer than setup's defined holding period)
- Setup type this trade was entered against
- R:R realized so far (live)

### 5.7 Trade Journal (Auto-Populated)
Every trade logged automatically with:
- Date, symbol, setup type matched
- Entry price, stop price, target price
- Exit price, exit reason (target hit / stop hit / manual exit / time exit)
- P&L in $ and R multiples (1R = 1× initial risk)
- Setup quality score at time of entry
- Notes field (trader adds context)

### 5.8 Performance Analytics by Setup
The trader sees, for each setup in their playbook:
- Total trades taken
- Win rate %
- Average winner (in R)
- Average loser (in R)
- Expectancy per trade: (win rate × avg winner) − (loss rate × avg loser)
- Positive expectancy = the setup has edge. Negative = remove from playbook.

This is the core measurement loop. Over time, the trader discovers which setups are actually profitable vs which ones feel good but lose money.

---

## 6. User Stories

**As a short-term trader, I want to:**
- Start each trading day with a pre-built list of in-play stocks that match my specific setups — not a generic scanner
- Know exactly how big to size each trade based on my stop level, so I risk the same dollar amount every time regardless of stock price
- Be blocked from placing new trades the moment I hit my daily loss limit — I cannot trust myself to stop
- See immediately whether a setup qualifies (score ≥ 60) or doesn't, with the specific conditions that failed
- Log every trade with one tap after exit, without having to retype entry/exit prices (auto-populated from broker)
- See my win rate by setup type so I know which setups to keep and which to drop

**As a trader building a playbook, I additionally want to:**
- Start from a template (e.g. earnings gap hold) and customize it to my rules
- Paper trade a new setup for 30 days before risking real money on it
- Compare two versions of the same setup (e.g. "gap holds 15 min" vs "gap holds 30 min") to see which performs better

---

## 7. Playbook Setup Library (Templates Provided)

| Setup | Category | Typical Hold | Primary Signal |
|-------|----------|--------------|----------------|
| Earnings Gap Hold | Earnings catalyst | 2–5 days | Beat + raised guidance + gap up 5%+ |
| News Catalyst Momentum | Event-driven | Same day to 3 days | Pre-market gap on positive news + volume 2x |
| Sympathy Selloff Reversal | Dislocation | 2–10 days | Peer miss → quality stock sold off without reason |
| Sector Rotation Momentum | Macro-driven | 1–4 weeks | Sector ETF breaks to 3-month high + leading stock in sector |
| VWAP Reclaim | Technical | Same day | Intraday: price reclaims VWAP on volume after flush |
| Breakout Continuation | Technical | 3–10 days | Multi-day consolidation breaks out on volume |
| Guidance Miss Fade | Earnings catalyst | 1–3 days | Revenue beat but guidance cut → dead-cat bounce short |
| Index Rebalancing Dip | Event-driven | 1–5 days | Stock removed from index → mechanical selling → reversal |

User can use, modify, or ignore any template. Can build entirely custom setups.

---

## 8. Out of Scope (MVP)

- Algorithmic / automated execution without human confirmation
- High-frequency or intraday scalping (< 1 minute holds) — latency requirements too high
- Options strategies as primary (calls/puts for leverage on setups) — Phase 2
- Social features / sharing plays
- Long-term portfolio management — separate product (Portfolio Manager)
- Backtesting engine — Phase 2 (manual paper trading is MVP substitute)
- Multi-leg options (spreads, straddles) — Phase 2
- Futures / forex / crypto — Phase 2

---

## 9. Technical Requirements

### Broker Connectors (MVP)
| Broker | Priority | Notes |
|--------|----------|-------|
| Alpaca | P0 | Best for active traders — free, API-first, paper trading built-in |
| Schwab | P1 | For traders who keep both LT and ST at same broker |
| IBKR | P2 | Pro traders needing direct market access |

### Data Sources
- Level 2 / quotes: Alpaca data feed (free tier sufficient for swing trading)
- Pre-market scanner: yfinance + Finnhub for gap detection
- News catalyst: Finnhub + Google News RSS (already in codebase)
- Earnings data: Alpha Vantage / Finnhub (already in codebase)
- VWAP / intraday levels: Alpaca data stream

### Intelligence Agents (ST Track)
- In-Play Scanner Agent (pre-market gap + catalyst detection)
- Playbook Matcher Agent (maps in-play stocks to user's setup definitions)
- Setup Scorer Agent (evaluates each entry condition, outputs 0–100 score)
- Position Sizer Agent (risk-based sizing: account size × risk% ÷ stop distance)
- Daily Limit Monitor (real-time P&L check against limit, hard block)
- Trade Journal Agent (auto-logs from broker fill data)
- Performance Analyst Agent (win rate, expectancy by setup type)

### Shared with Portfolio Manager
- Markov 2.0 regime detection (macro filter on position size)
- TradingMemoryLog (tagged `track: short_term`)
- Human Approval Gate
- Broker Connector Layer
- Feedback Reflector

### Playbook Config Format
- User-facing: form-based setup builder
- Stored as: `playbook.yaml` per user (version-controlled)
- Runtime: agents read playbook config to qualify and score setups

---

## 10. Key Interface Screens

1. **Morning Dashboard** — macro regime badge, in-play stock list with playbook match indicators, earnings calendar
2. **Setup Detail** — full setup qualification scorecard for a specific stock, entry/stop/target/size pre-calculated
3. **Trade Entry** — confirm card with all parameters pre-filled; one-tap approve
4. **Active Trades** — live positions with P&L, stop/target distance, time-in-trade
5. **Daily P&L Gauge** — always-visible daily loss progress; hard block UI when limit reached
6. **Trade Journal** — sortable/filterable log of all trades with P&L in R multiples
7. **Playbook Analytics** — win rate and expectancy per setup, charts over time
8. **Playbook Builder** — form-based editor for defining and editing setups

---

## 11. Phase 2 (Post-MVP)

- Backtesting engine (run playbook setups against historical data)
- Paper trading mode (full simulation before going live)
- Options plays as setup overlay (buying calls/puts on qualifying setups)
- Intraday scanner (Level 2 + tape reading signals)
- Pattern recognition (AI flags additional setup qualifications from chart patterns)
- Mobile app (morning scanner and trade approval on phone)
- Community benchmarks (anonymous aggregate: "traders running this setup average 58% win rate")
