# Claude Code Implementation Brief: Portfolio Construction Extension for TradingAgents

## Objective

Extend the existing TradingAgents open-source research system into a portfolio construction system.

The goal is **not trading execution**. The system should not place trades or produce short-term buy/sell signals as the final product. Instead, it should transform agent research into:

- investable candidates
- portfolio views
- target allocations
- risk-aware weights
- overweight / underweight explanations
- weekly or monthly rebalance recommendations

Core positioning:

> TradingAgents becomes an AI investment committee + portfolio construction engine.

---

## High-Level Architecture

```text
Universe
  ↓
Screener Agent / Screener Engine
  ↓
Shortlist of portfolio candidates
  ↓
Existing TradingAgents research agents
  ↓
Portfolio Agent
  ↓
Allocation Agent
  ↓
Risk Agent
  ↓
Portfolio Memo / Rebalance Report
```

Important design principle:

```text
LLM agents generate views, explanations, and structured investment reasoning.
Deterministic Python engines calculate weights, risk, correlation, Sharpe, constraints, and turnover.
```

Do **not** let the LLM directly invent final portfolio weights.

---

## New Agents / Modules to Add

### 1. Screener Agent / Screener Engine

Purpose:

Reduce the investment universe from thousands of stocks to a manageable shortlist before running expensive TradingAgents research.

Input:

- stock universe, e.g. S&P 500 initially
- price data
- fundamental data
- sector / industry classifications
- liquidity data
- optional macro or theme inputs

Output:

- ranked candidate list
- factor scores
- diversified shortlist

Recommended MVP universe:

```text
S&P 500 only
```

Later universes:

```text
Nasdaq 100
Russell 1000
Dividend universe
AI / semiconductor universe
ETFs
International ADRs
```

Hard filters:

```text
market cap > $2B
average daily volume > 1M shares
positive revenue growth
positive free cash flow
price above 200-day moving average
debt-to-equity below threshold
exclude extreme valuation outliers
```

Factor scores, 0-100 scale:

```text
Quality:
- ROIC
- gross margin
- operating margin
- free cash flow margin
- earnings consistency
- debt level

Growth:
- revenue growth
- EPS growth
- free cash flow growth
- forward estimate growth

Value:
- P/E
- forward P/E
- EV/EBITDA
- price/free cash flow
- PEG

Momentum:
- 3-month return
- 6-month return
- 12-month return
- price vs 200-day moving average
- relative strength vs S&P 500

Risk:
- volatility
- beta
- max drawdown
- correlation with existing portfolio
- balance sheet risk
```

Default composite score:

```text
Composite =
30% Quality
25% Growth
20% Momentum
15% Value
10% Risk
```

Diversification rules:

```text
Do not simply take the top 50 overall.
Limit concentration:
- max 5 stocks per sector
- max 2-3 stocks per industry
- minimum number of sectors represented
- include low-correlation candidates
```

Example output schema:

```json
{
  "ticker": "MSFT",
  "sector": "Technology",
  "industry": "Software",
  "quality_score": 92,
  "growth_score": 78,
  "value_score": 55,
  "momentum_score": 81,
  "risk_score": 74,
  "composite_score": 79.8,
  "screening_reason": "High quality, strong momentum, durable cash flow, moderate valuation risk"
}
```

---

### 2. Portfolio Agent

Purpose:

Act as the investment committee. It reviews existing TradingAgents research outputs and converts them into structured portfolio views.

The Portfolio Agent should answer:

```text
What assets, sectors, or themes should be overweight, neutral, underweight, or avoided?
What is the thesis?
What is the confidence?
What are the key risks?
What time horizon is appropriate?
```

Input:

- research reports from existing TradingAgents agents
- factor scores from screener
- user portfolio objective
- risk profile
- benchmark
- current holdings, if available

Output:

Structured views, not final weights.

Example output schema:

```json
{
  "portfolio_view_date": "YYYY-MM-DD",
  "benchmark": "SPY",
  "sector_views": {
    "Technology": {
      "view": "overweight",
      "confidence": 0.72,
      "reason": "Strong earnings momentum and AI capex cycle, but valuation risk remains elevated"
    },
    "Utilities": {
      "view": "underweight",
      "confidence": 0.61,
      "reason": "Defensive value, but weaker relative momentum"
    }
  },
  "asset_views": [
    {
      "ticker": "MSFT",
      "view": "overweight",
      "expected_return_estimate": 0.11,
      "confidence": 0.74,
      "risk_level": "medium",
      "time_horizon": "12-36 months",
      "primary_thesis": "Durable enterprise software franchise with AI monetization upside",
      "main_risks": ["valuation compression", "slower AI revenue conversion"]
    }
  ]
}
```

Important:

The Portfolio Agent can suggest directional tilts such as:

```text
Technology +3% tactical overweight
Energy neutral
Utilities -2% underweight
```

But it should not directly produce final security-level weights.

---

### 3. Allocation Agent

Purpose:

Translate Portfolio Agent views into target portfolio weights using a deterministic allocation engine.

The Allocation Agent should coordinate the math, but the math should live in Python functions.

Input:

- Portfolio Agent asset views
- expected returns
- confidence scores
- current portfolio weights
- covariance matrix
- volatility
- correlation matrix
- risk-free rate
- benchmark weights
- portfolio constraints

Output:

- target weights
- overweight / underweight vs benchmark
- expected portfolio return
- expected volatility
- Sharpe ratio
- sector exposure
- turnover
- constraint violations, if any

Core calculation concepts:

```text
Expected return = derived from agent view + confidence + factor score
Risk = volatility + covariance + correlation
Objective = maximize risk-adjusted return, usually Sharpe
Constraints = position caps, sector caps, turnover caps, diversification minimums
```

Supported allocation methods for MVP:

1. Score-weighted allocation
2. Volatility-adjusted score weighting
3. Constrained max-Sharpe allocation
4. Risk parity, optional but recommended

Example output schema:

```json
{
  "allocation_date": "YYYY-MM-DD",
  "method": "constrained_max_sharpe",
  "target_weights": {
    "MSFT": 0.045,
    "NVDA": 0.040,
    "COST": 0.035
  },
  "sector_exposure": {
    "Technology": 0.28,
    "Healthcare": 0.15,
    "Financials": 0.12
  },
  "expected_portfolio_return": 0.105,
  "expected_volatility": 0.135,
  "portfolio_sharpe": 0.48,
  "estimated_turnover": 0.08,
  "notes": [
    "Technology overweight capped due to high intra-sector correlation",
    "NVDA weight reduced because of volatility and correlation cluster risk"
  ]
}
```

---

### 4. Risk Agent / Risk Engine

Purpose:

Review the proposed allocation before final output.

Input:

- target weights
- covariance matrix
- correlation matrix
- volatility
- beta
- sector exposure
- factor exposure
- drawdown estimates
- current portfolio weights

Checks:

```text
max single stock weight
max sector weight
max industry weight
correlation cluster risk
portfolio volatility
estimated drawdown
turnover
liquidity
cash level
benchmark deviation
```

Example output schema:

```json
{
  "risk_review_date": "YYYY-MM-DD",
  "approved": true,
  "risk_score": 0.62,
  "warnings": [
    "Technology exposure is near the 30% sector cap",
    "Top 5 holdings represent 23% of portfolio",
    "AI semiconductor cluster has high average correlation of 0.78"
  ],
  "required_adjustments": [],
  "recommended_adjustments": [
    {
      "action": "reduce",
      "ticker": "NVDA",
      "amount": 0.005,
      "reason": "High volatility and high correlation with other AI holdings"
    }
  ]
}
```

---

### 5. Portfolio Memo Agent

Purpose:

Generate a human-readable investment committee memo.

Input:

- Portfolio Agent views
- Allocation Agent target weights
- Risk Agent review
- current vs target weights
- changes since last rebalance

Output:

- executive summary
- key overweight / underweight decisions
- top holdings rationale
- risk summary
- rebalance recommendations
- what changed since last review

Example sections:

```text
1. Portfolio Summary
2. Current Regime View
3. Overweight Areas
4. Underweight Areas
5. New Additions
6. Reductions / Removals
7. Risk Review
8. Rebalance Actions
9. Watchlist
```

---

## Weight Construction Framework

Use a three-layer weighting model:

```text
Final Weight = Base Allocation + Tactical Tilt, adjusted by risk and correlation
```

### 1. Base Allocation

Stable anchor allocation. Does not change frequently.

Example:

```text
Technology: 25%
Healthcare: 15%
Financials: 12%
Industrials: 10%
Consumer: 10%
Energy: 8%
Defensive: 10%
Cash / Bonds / ETFs: 10%
```

### 2. Tactical Tilt

Dynamic overweight / underweight driven by Portfolio Agent views.

Formula concept:

```python
tilt = normalized_signal_score - average_signal_score
adjusted_weight = base_weight + aggressiveness * tilt
```

Recommended aggressiveness:

```text
Conservative: 0.10-0.20
Balanced: 0.20-0.35
Aggressive: 0.35-0.50
```

### 3. Risk and Correlation Adjustment

Use volatility and covariance to avoid overconcentration.

Core concepts:

```python
portfolio_return = weights @ expected_returns
portfolio_vol = sqrt(weights.T @ covariance_matrix @ weights)
sharpe = (portfolio_return - risk_free_rate) / portfolio_vol
```

Correlation matters because multiple stocks can appear different but behave like the same risk exposure.

Example:

```text
NVDA, AMD, AVGO, MSFT, META may all score well.
But if they have high correlation, the allocation engine should cap the cluster.
```

---

## Rebalancing Framework

The system should support weekly and monthly updates.

Key principle:

```text
Do not rebuild the whole portfolio from scratch every rebalance.
Move gradually from current weights toward target weights.
```

Smoothing formula:

```python
new_weight = old_weight + alpha * (target_weight - old_weight)
```

Recommended alpha:

```text
Weekly rebalance: 0.20-0.40
Monthly rebalance: 0.40-0.70
Quarterly rebalance: 0.70-1.00
```

Add rebalance threshold:

```python
if abs(target_weight - old_weight) < 0.02:
    skip_trade_or_change = True
```

Turnover constraint:

```text
Max weekly turnover: 5-10%
Max monthly turnover: 10-20%
```

Signal update frequency:

```text
Momentum: weekly
Volatility/correlation: weekly
Macro: monthly
Fundamentals: quarterly
Deep agent research: monthly or quarterly, unless event-driven
```

---

## Suggested Code Structure

Add a new package/module:

```text
portfolio_construction/
  __init__.py
  schemas.py
  screener.py
  factor_scoring.py
  portfolio_agent.py
  allocation_agent.py
  optimizer.py
  risk_model.py
  rebalance.py
  memo_agent.py
  data_interfaces.py
  config.py
```

### schemas.py

Define Pydantic models for:

```text
StockCandidate
FactorScores
ResearchReportInput
PortfolioView
AssetView
SectorView
AllocationRequest
AllocationResult
RiskReview
RebalancePlan
PortfolioMemo
```

### screener.py

Responsibilities:

```text
load universe
apply hard filters
calculate factor scores
rank candidates
apply diversification constraints
return shortlist
```

### factor_scoring.py

Responsibilities:

```text
normalize metrics
score quality, growth, value, momentum, and risk
calculate composite score
```

### portfolio_agent.py

Responsibilities:

```text
consume TradingAgents research reports
produce structured PortfolioView JSON
summarize overweight / underweight logic
estimate expected return and confidence
```

### allocation_agent.py

Responsibilities:

```text
prepare allocation request
call optimizer functions
apply smoothing and turnover constraints
return allocation result
```

### optimizer.py

Responsibilities:

```text
score-weighted allocation
volatility-adjusted allocation
risk parity allocation
constrained max-Sharpe optimization
normalization
sector cap enforcement
position cap enforcement
```

### risk_model.py

Responsibilities:

```text
calculate returns
calculate volatility
calculate covariance matrix
calculate correlation matrix
calculate portfolio volatility
calculate Sharpe ratio
calculate drawdown estimate
identify correlation clusters
```

### rebalance.py

Responsibilities:

```text
compare current vs target weights
apply alpha smoothing
apply minimum change threshold
calculate turnover
generate rebalance actions
```

### memo_agent.py

Responsibilities:

```text
generate portfolio memo
explain overweight / underweight decisions
explain risk and constraints
summarize changes since last rebalance
```

---

## MVP Build Order

### Phase 1: Deterministic Screener + Allocation Engine

Build first without heavy LLM changes.

1. Universe loader
2. Hard filters
3. Factor scoring
4. Composite ranking
5. Diversified shortlist
6. Volatility and correlation calculation
7. Score-weighted allocation
8. Basic constraints
9. Portfolio output JSON

### Phase 2: Portfolio Agent

1. Feed top 50-75 candidates into existing TradingAgents research flow
2. Convert research outputs into structured PortfolioView
3. Add sector and asset-level views
4. Add confidence scores and expected return estimates

### Phase 3: Allocation Agent + Risk Agent

1. Add max-Sharpe optimizer
2. Add risk parity option
3. Add sector caps
4. Add correlation cluster reduction
5. Add turnover limits
6. Add weekly/monthly smoothing

### Phase 4: Portfolio Memo Agent

1. Generate human-readable memo
2. Explain target weights
3. Explain overweight / underweight areas
4. Explain risks and changes since last rebalance

---

## Default MVP Constraints

```json
{
  "max_single_stock_weight": 0.05,
  "max_sector_weight": 0.30,
  "max_industry_weight": 0.15,
  "min_number_of_holdings": 20,
  "max_number_of_holdings": 35,
  "max_weekly_turnover": 0.10,
  "max_monthly_turnover": 0.20,
  "rebalance_threshold": 0.02,
  "weekly_alpha": 0.30,
  "monthly_alpha": 0.60,
  "risk_free_rate": 0.04
}
```

---

## Example End-to-End Flow

```python
universe = load_universe("sp500")

screened = screener.run(
    universe=universe,
    filters=default_filters,
    scoring_profile="balanced"
)

shortlist = screener.apply_diversification(
    candidates=screened,
    max_per_sector=5,
    max_per_industry=3,
    target_count=75
)

research_reports = tradingagents.run_research(shortlist)

portfolio_view = portfolio_agent.generate_view(
    research_reports=research_reports,
    objective="balanced_growth",
    benchmark="SPY"
)

risk_inputs = risk_model.calculate(
    tickers=portfolio_view.tickers,
    lookback_days=252
)

allocation = allocation_agent.allocate(
    portfolio_view=portfolio_view,
    risk_inputs=risk_inputs,
    current_weights=current_portfolio,
    constraints=default_constraints,
    method="constrained_max_sharpe"
)

risk_review = risk_agent.review(allocation)

memo = memo_agent.generate(
    portfolio_view=portfolio_view,
    allocation=allocation,
    risk_review=risk_review
)
```

---

## Claude Code Instruction

Please implement this as a modular extension to the existing TradingAgents codebase.

Priorities:

1. Do not break the existing agent research workflow.
2. Add the portfolio construction modules as a separate package.
3. Use Pydantic schemas for all agent and engine outputs.
4. Keep deterministic portfolio math separate from LLM reasoning.
5. Add unit tests for screener, scoring, optimizer, risk model, and rebalance logic.
6. Use mock data first if live market/fundamental data interfaces are not already available.
7. Provide example scripts showing:
   - run screener
   - generate shortlist
   - run portfolio view
   - generate target allocation
   - create portfolio memo

The first working milestone should be:

```text
Given a stock universe and mock factor data, produce a diversified shortlist and target portfolio weights with risk metrics.
```

Then integrate with existing TradingAgents research outputs.
