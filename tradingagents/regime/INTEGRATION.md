# Markov 2.0 — integrating the regime signal into TradingAgents

A faithful Python port of the TradingView "Markov 2.0 — Regime (corrected)"
indicator. Deterministic, token-free, and orthogonal to the existing analysts.
Research tooling only — not investment advice.

## What it gives you

```python
from tradingagents.regime import analyze, MarkovConfig

res = analyze(close_prices, MarkovConfig(mode="filter"))   # high/low optional (ATR preset)
res.regime_name   # BEAR / SIDEWAYS / BULL
res.signal        # P(bull next | regime) - P(bear next | regime)
res.edge          # signal - stationary base rate  (the real, de-biased signal)
res.ready         # FIX 1+2 gate: labels verified AND enough stride samples
res.action        # "GO LONG" / "GO SHORT" / "STAND ASIDE ..." / "WAIT ..."
res.P_stride      # honest (non-overlapping) transition matrix
res.P_overlap     # legacy (inflated) matrix, for the comparison display
```

## Three places it can plug in

### 1. Regime Analyst input (feeds the agent debate)
Wrap `analyze()` as a dataflow tool and inject its report next to the Market /
Sentiment / News / Fundamentals analysts. Render `regime`, `signal`, `edge`,
`ready`, and the stride matrix as a short markdown block the LLM agents reason
over. Because the number is computed (not generated), it grounds the bull/bear
debate instead of adding more narrative.

### 2. Portfolio gate (risk-aware weights — the Portfolio Construction Extension)
Use `res.position` (filter: -1/0/+1; standalone: scaled) to scale or veto target
weights: e.g. `weight *= max(0, res.position)` for long-only, or down-weight
names whose regime is BEAR / not `ready`. This is the "overweight / underweight"
and "risk-aware weights" surface.

### 3. desk_server endpoint (surfaces in the TradingDesk / web UI)
Add `GET /regime?ticker=&days=` to `desk_server/app.py` that pulls closes via the
existing dataflow and returns `analyze(...)` as JSON. Then render it as a
"Regime analysis" report section and a Live Monitor pipeline lane (next to
Sentiment / Fundamentals), plus a regime tag on the Watchlist row.

## The three fixes (why this is "2.0", verified in the demo)
- **FIX 1 — stride sampling.** Overlapping windows fake persistence; the demo
  shows stride stickiness ~35% vs legacy ~85% on the same data. Only the stride
  matrix is trusted, and a per-state sample count gates readiness.
- **FIX 2 — label verification.** `verify_labels` asserts mean window-return is
  BEAR < SIDEWAYS < BULL before any matrix is trusted (`res.verify_ok`).
- **FIX 3 — two modes.** `mode="filter"` gates an existing strategy;
  `mode="standalone"` sizes the position to |signal|, capped.

## Run the proof
```bash
PYTHONPATH=. python scripts/markov2_demo.py                # synthetic (offline)
PYTHONPATH=. python scripts/markov2_demo.py --ticker SPY   # real 10y via yfinance
PYTHONPATH=. python scripts/markov2_demo.py --csv SPY.csv  # your own data
```
Backtests flatter. The fixed (stride) matrix shows uglier, truer numbers — those
are the only ones worth trading.
