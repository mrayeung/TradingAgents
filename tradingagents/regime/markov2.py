"""Markov 2.0 — Regime (Bull / Bear / Sideways), corrected.

Faithful Python port of the TradingView Pine v5 indicator by Roan (@RohOnChain).
The display/table/alert layer of the indicator is TradingView-specific and is not
ported; this module reproduces the *quantitative core* exactly, so a Python run
and the chart agree bar-for-bar.

State encoding (matches the Pine script): 0 = BEAR, 1 = SIDEWAYS, 2 = BULL.
States come from the `window`-bar CUMULATIVE return:
    cumret = close / close[t-window] - 1
    cumret >= +up_thr  -> BULL (2)
    cumret <= -down_thr -> BEAR (0)
    else                -> SIDEWAYS (1)

The three fixes that make this "2.0":

  FIX 1  Stride (non-overlapping) sampling. Consecutive `window`-bar labels share
         window-1 bars, which fakes persistence on the diagonal. We count
         transitions on BOTH bases -- overlapping (legacy) and stride-sampled
         (true) -- and only trust the stride matrix.

  FIX 2  Label verification. We check the encoding holds in the data
         (mean window-return BEAR < SIDEWAYS < BULL) and expose PASS/FAIL, so a
         mislabelled mapping can never pass silently.

  FIX 3  Two explicit modes. FILTER gates a long/short/flat decision by a signal
         threshold; STANDALONE sizes the position to |signal|, capped.

Research tooling only. Not investment advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

# ── State encoding ───────────────────────────────────────────────────────────
BEAR, SIDE, BULL = 0, 1, 2
STATE_NAMES = {BEAR: "BEAR", SIDE: "SIDEWAYS", BULL: "BULL"}


# ── Configuration (mirrors the Pine inputs and their defaults) ────────────────
@dataclass
class MarkovConfig:
    # Regime logic
    window: int = 20            # lookback bars for cumulative-return state
    up_pct: float = 5.0         # BULL threshold (%) in manual mode
    down_pct: float = 5.0       # BEAR threshold (%) in manual mode
    stride: int = 20            # FIX 1: sample regime every N bars (non-overlapping)
    stat_power: int = 50        # iterations for the stationary distribution

    # Threshold preset: "manual" | "auto_std" | "auto_atr"
    preset: str = "manual"
    vol_k: float = 1.0          # auto sensitivity: thr = k * basis * sqrt(window)
    vol_len: int = 100          # std-dev lookback for the auto-std basis
    atr_len: int = 14           # ATR length for the auto-atr basis

    # FIX 3: mode + sizing
    mode: str = "filter"        # "filter" | "standalone"
    sig_thresh: float = 0.10    # filter: |signal| gate
    sig_scale: float = 0.50     # standalone: position = clamp(signal/scale, -cap, cap)
    sig_cap: float = 1.0        # standalone: position cap

    # Readiness / edge gates (FIX 1 + edge-vs-base-rate)
    ready_min_samples: int = 30  # min stride samples per originating state
    edge_min: float = 0.02       # |signal - base_rate| needed to "have an edge"


# ── Result for a single (latest) bar ──────────────────────────────────────────
@dataclass
class MarkovResult:
    regime: int                       # current state (0/1/2)
    regime_name: str
    signal: float                     # P(bull next | cur) - P(bear next | cur)
    base_signal: float                # stationary bull - bear (unconditional tilt)
    edge: float                       # signal - base_signal
    edge_tag: str                     # none / weak / moderate / strong
    has_edge: bool
    verify_ok: bool                   # FIX 2 label check
    min_samples: int                  # FIX 1 reliability gauge
    ready: bool                       # verify_ok AND enough samples
    position: float                   # FIX 3 raw position (filter: -1/0/1; standalone: scaled)
    position_label: str
    tradeable: bool                   # ready AND has_edge AND position != 0
    action: str                       # human-readable recommendation
    P_stride: np.ndarray = field(repr=False)   # 3x3 true (stride) matrix
    P_overlap: np.ndarray = field(repr=False)  # 3x3 legacy (overlapping) matrix
    stationary: np.ndarray = field(repr=False) # length-3 long-run mix
    mean_return_by_state: np.ndarray = field(repr=False)
    n_labeled: int = 0
    # Forward projection from the current regime (FIX-honest stride matrix):
    horizon_bars: int = 0                                  # one matrix step = one stride
    next_distribution: np.ndarray = field(default=None, repr=False)  # P(state | cur) next step
    forecast: list = field(default_factory=list, repr=False)         # multi-step projection


# ── Threshold + state construction ────────────────────────────────────────────
def _atr_over_price(high, low, close, atr_len):
    """Wilder-style ATR / close, causal (uses only past/current bars)."""
    n = len(close)
    tr = np.full(n, np.nan)
    for t in range(1, n):
        hl = high[t] - low[t]
        hc = abs(high[t] - close[t - 1])
        lc = abs(low[t] - close[t - 1])
        tr[t] = max(hl, hc, lc)
    atr = np.full(n, np.nan)
    # simple rolling mean of TR (matches ta.atr closely enough for thresholds)
    for t in range(atr_len, n):
        atr[t] = np.nanmean(tr[t - atr_len + 1 : t + 1])
    return atr / close


def compute_states(close, cfg: MarkovConfig, high=None, low=None):
    """Return (states, cumret, up_thr, down_thr) as float arrays.

    All thresholds are causal (backward-looking), so labelling a past bar never
    uses future data -- this keeps the walk-forward backtest honest.
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    w = cfg.window

    cumret = np.full(n, np.nan)
    cumret[w:] = close[w:] / close[:-w] - 1.0

    if cfg.preset == "manual":
        up_thr = np.full(n, cfg.up_pct / 100.0)
        down_thr = np.full(n, cfg.down_pct / 100.0)
    else:
        ret1 = np.full(n, np.nan)
        ret1[1:] = close[1:] / close[:-1] - 1.0
        if cfg.preset == "auto_atr" and high is not None and low is not None:
            basis = _atr_over_price(np.asarray(high, float), np.asarray(low, float), close, cfg.atr_len)
        else:  # auto_std (or auto_atr without OHLC -> fall back to std)
            basis = np.full(n, np.nan)
            for t in range(cfg.vol_len, n):
                basis[t] = np.nanstd(ret1[t - cfg.vol_len + 1 : t + 1], ddof=0)
        band = cfg.vol_k * basis * np.sqrt(w)
        up_thr = band
        down_thr = band

    states = np.full(n, np.nan)
    for t in range(n):
        cr, ut, dt = cumret[t], up_thr[t], down_thr[t]
        if np.isnan(cr) or np.isnan(ut):
            continue
        if cr >= ut:
            states[t] = BULL
        elif cr <= -dt:
            states[t] = BEAR
        else:
            states[t] = SIDE
    return states, cumret, up_thr, down_thr


# ── Transition counting (FIX 1: both bases) ───────────────────────────────────
def transition_counts(states, stride: int):
    """Return (counts_overlap, counts_stride) as 3x3 int arrays.

    overlap: every consecutive labelled pair (autocorrelated -> inflated diagonal).
    stride : sample the label only once every `stride` bars (statistically honest).
    """
    counts_over = np.zeros((3, 3), dtype=int)
    counts_str = np.zeros((3, 3), dtype=int)

    prev = None
    prev_samp = None
    last_samp_bar = None

    for t, s in enumerate(states):
        if np.isnan(s):
            prev = None  # break the overlapping chain across gaps
            continue
        s = int(s)

        # Legacy overlapping: consecutive labelled bars
        if prev is not None:
            counts_over[prev, s] += 1
        prev = s

        # Stride: sample only every >= stride bars
        if last_samp_bar is None or (t - last_samp_bar) >= stride:
            if prev_samp is not None:
                counts_str[prev_samp, s] += 1
            prev_samp = s
            last_samp_bar = t

    return counts_over, counts_str


def normalise(counts) -> np.ndarray:
    """Rows -> probabilities; an empty row falls back to uniform (1/3 each)."""
    counts = np.asarray(counts, dtype=float)
    P = np.zeros((3, 3))
    for r in range(3):
        rs = counts[r].sum()
        P[r] = counts[r] / rs if rs > 0 else np.array([1 / 3, 1 / 3, 1 / 3])
    return P


def stationary(P, power: int) -> np.ndarray:
    """First row of P^power (rows converge to the stationary distribution)."""
    return np.linalg.matrix_power(P, power)[0]


def verify_labels(states, cumret):
    """FIX 2: mean window-return per state and the BEAR < SIDE < BULL check."""
    means = np.full(3, np.nan)
    for s in range(3):
        mask = states == s
        vals = cumret[mask]
        vals = vals[~np.isnan(vals)]
        if len(vals):
            means[s] = vals.mean()
    ok = (
        not np.any(np.isnan(means))
        and means[BEAR] < means[SIDE] < means[BULL]
    )
    return ok, means


def _edge_tag(ae: float) -> str:
    if ae >= 0.10:
        return "strong"
    if ae >= 0.05:
        return "moderate"
    if ae >= 0.02:
        return "weak"
    return "none"


def _position(signal: float, cfg: MarkovConfig) -> float:
    if cfg.mode == "filter":
        if signal > cfg.sig_thresh:
            return 1.0
        if signal < -cfg.sig_thresh:
            return -1.0
        return 0.0
    # standalone
    return float(np.clip(signal / cfg.sig_scale, -cfg.sig_cap, cfg.sig_cap))


# ── Public: analyse the latest bar ────────────────────────────────────────────
def analyze(close, cfg: Optional[MarkovConfig] = None, high=None, low=None) -> MarkovResult:
    """Run the full Markov 2.0 pipeline over `close` and report the latest bar.

    Mirrors the Pine `barstate.islast` block: build both matrices, verify labels,
    compute signal/edge/readiness, derive the position and ACTION.
    """
    cfg = cfg or MarkovConfig()
    close = np.asarray(close, dtype=float)
    states, cumret, up_thr, down_thr = compute_states(close, cfg, high, low)

    counts_over, counts_str = transition_counts(states, cfg.stride)
    P_over = normalise(counts_over)
    P_str = normalise(counts_str)
    stat = stationary(P_str, cfg.stat_power)

    verify_ok, means = verify_labels(states, cumret)

    # FIX 1 reliability: fewest stride samples across the three originating states
    samp_per_state = counts_str.sum(axis=1)
    min_samples = int(samp_per_state.min())
    ready = bool(verify_ok and min_samples >= cfg.ready_min_samples)

    # current regime (default SIDEWAYS if the latest bar is unlabelled)
    last_valid = states[~np.isnan(states)]
    cur = int(last_valid[-1]) if len(last_valid) else SIDE

    signal = P_str[cur, BULL] - P_str[cur, BEAR]
    base_signal = stat[BULL] - stat[BEAR]
    edge = signal - base_signal
    ae = abs(edge)
    tag = _edge_tag(ae)
    has_edge = ae >= cfg.edge_min

    # Forward projection from the current regime over 1..3 matrix steps (strides).
    # The signal lives at ~1 stride and decays toward the base rate (stationary)
    # as the horizon grows -- long-horizon forecasts carry no edge.
    next_dist = P_str[cur].copy()
    forecast = []
    for k in (1, 2, 3):
        dist = np.linalg.matrix_power(P_str, k)[cur]
        sig_k = float(dist[BULL] - dist[BEAR])
        forecast.append(
            {
                "steps": k,
                "bars": k * cfg.stride,
                "p_bear": float(dist[BEAR]),
                "p_side": float(dist[SIDE]),
                "p_bull": float(dist[BULL]),
                "signal": sig_k,
                "edge": float(sig_k - base_signal),
            }
        )

    pos = _position(signal, cfg)
    if cfg.mode == "filter":
        pos_label = "LONG" if pos > 0 else "SHORT" if pos < 0 else "FLAT"
    else:
        pos_label = f"{pos:+.2f}"

    tradeable = bool(ready and has_edge and pos != 0)
    if not ready:
        action = "WAIT (data not ready)"
    elif not has_edge:
        action = "STAND ASIDE (no edge)"
    elif pos == 0:
        action = "STAND ASIDE (weak signal)"
    elif cfg.mode == "filter":
        action = "GO LONG" if pos > 0 else "GO SHORT"
    else:
        action = f"SIZE {pos:+.2f} {'long' if pos > 0 else 'short'}"

    return MarkovResult(
        regime=cur,
        regime_name=STATE_NAMES[cur],
        signal=float(signal),
        base_signal=float(base_signal),
        edge=float(edge),
        edge_tag=tag,
        has_edge=has_edge,
        verify_ok=bool(verify_ok),
        min_samples=min_samples,
        ready=ready,
        position=float(pos),
        position_label=pos_label,
        tradeable=tradeable,
        action=action,
        P_stride=P_str,
        P_overlap=P_over,
        stationary=stat,
        mean_return_by_state=means,
        n_labeled=int(np.sum(~np.isnan(states))),
        horizon_bars=cfg.stride,
        next_distribution=next_dist,
        forecast=forecast,
    )


# ── Public: walk-forward backtest ("proof, not promises") ─────────────────────
def walk_forward(
    close,
    cfg: Optional[MarkovConfig] = None,
    high=None,
    low=None,
    min_history: int = 252,
    matrix: str = "stride",
):
    """Walk-forward backtest that NEVER tests on data the matrix has learned from.

    At each bar t (>= min_history) the transition matrix is rebuilt from states
    up to and including t only, the position is decided from the current regime,
    and the P&L is booked on the *next* bar's return. Set ``matrix="overlap"`` to
    reproduce the inflated legacy result for the before/after comparison.

    Returns a dict of arrays + summary metrics (total return, CAGR, Sharpe, win
    rate, profit factor, max drawdown) plus a buy & hold baseline.
    """
    cfg = cfg or MarkovConfig()
    close = np.asarray(close, dtype=float)
    n = len(close)
    states, cumret, _, _ = compute_states(close, cfg, high, low)
    ret = np.full(n, np.nan)
    ret[1:] = close[1:] / close[:-1] - 1.0

    positions = np.zeros(n)
    strat_ret = np.zeros(n)

    for t in range(min_history, n - 1):
        sub = states[: t + 1]
        counts_over, counts_str = transition_counts(sub, cfg.stride)
        counts = counts_str if matrix == "stride" else counts_over
        P = normalise(counts)
        stat = stationary(P, cfg.stat_power)

        verify_ok, _ = verify_labels(sub, cumret[: t + 1])
        min_samp = int(counts_str.sum(axis=1).min())
        ready = verify_ok and min_samp >= cfg.ready_min_samples

        s = sub[~np.isnan(sub)]
        cur = int(s[-1]) if len(s) else SIDE
        signal = P[cur, BULL] - P[cur, BEAR]
        edge = signal - (stat[BULL] - stat[BEAR])
        pos = _position(signal, cfg)
        tradeable = ready and abs(edge) >= cfg.edge_min and pos != 0
        pos = pos if tradeable else 0.0

        positions[t] = pos
        strat_ret[t + 1] = pos * ret[t + 1]

    active = positions != 0
    eq = np.cumprod(1.0 + np.nan_to_num(strat_ret))
    bh = np.cumprod(1.0 + np.nan_to_num(np.where(np.arange(n) >= min_history, np.nan_to_num(ret), 0.0)))

    r = strat_ret[min_history + 1 :]
    r = r[~np.isnan(r)]
    act_r = strat_ret[active]
    wins = act_r[act_r > 0].sum()
    losses = -act_r[act_r < 0].sum()
    years = max((n - min_history) / 252.0, 1e-9)
    dd = eq / np.maximum.accumulate(eq) - 1.0

    metrics = {
        "matrix": matrix,
        "mode": cfg.mode,
        "bars_tested": int(n - min_history - 1),
        "bars_in_market": int(active.sum()),
        "exposure": float(active.mean()),
        "total_return": float(eq[-1] - 1.0),
        "cagr": float(eq[-1] ** (1 / years) - 1.0),
        "sharpe": float(np.mean(r) / np.std(r) * np.sqrt(252)) if np.std(r) > 0 else 0.0,
        "win_rate": float((act_r > 0).mean()) if active.sum() else 0.0,
        "profit_factor": float(wins / losses) if losses > 0 else float("inf"),
        "max_drawdown": float(dd.min()),
        "buy_hold_return": float(bh[-1] - 1.0),
    }
    return {
        "metrics": metrics,
        "equity": eq,
        "buy_hold": bh,
        "positions": positions,
        "strategy_returns": strat_ret,
        "states": states,
    }
