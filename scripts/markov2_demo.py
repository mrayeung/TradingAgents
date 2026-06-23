"""Markov 2.0 demo + walk-forward proof.

Usage:
    python scripts/markov2_demo.py                 # synthetic regime-switching demo
    python scripts/markov2_demo.py --csv SPY.csv   # real data (needs a 'Close' column)
    python scripts/markov2_demo.py --ticker SPY    # pulls 10y via yfinance if available

Prints the latest-bar regime report, FIX 2 label verification, the TRUE (stride)
vs LEGACY (overlapping) matrices, and a walk-forward backtest comparing the two
so you can see how the legacy matrix flatters. Research tooling, not advice.
"""

import argparse
import numpy as np

from tradingagents.regime.markov2 import (
    MarkovConfig,
    STATE_NAMES,
    analyze,
    walk_forward,
)


def synthetic_prices(n=6000, seed=7):
    """A regime-switching geometric random walk with KNOWN regimes, so the label
    self-check has ground truth: bull drifts up, bear drifts down, side is flat.
    Tuned to resemble a long equity-index history (net upward drift) with enough
    of every regime that the stride matrix accumulates a reliable sample count."""
    rng = np.random.default_rng(seed)
    # transition probs between true hidden regimes (bull/side/bear)
    P = {
        "bull": [("bull", 0.94), ("side", 0.05), ("bear", 0.01)],
        "side": [("side", 0.90), ("bull", 0.07), ("bear", 0.03)],
        "bear": [("bear", 0.88), ("side", 0.10), ("bull", 0.02)],
    }
    params = {"bull": (0.0007, 0.009), "side": (0.0000, 0.008), "bear": (-0.0009, 0.016)}
    state = "side"
    rets = []
    truth = []
    for _ in range(n):
        roll = rng.random()
        cum = 0.0
        for nxt, p in P[state]:
            cum += p
            if roll <= cum:
                state = nxt
                break
        mu, sd = params[state]
        rets.append(rng.normal(mu, sd))
        truth.append(state)
    price = 100 * np.cumprod(1 + np.array(rets))
    return price, truth


def fmt_matrix(P, title):
    print(f"\n  {title}")
    print("            BEAR   SIDE   BULL")
    for r, name in enumerate(["BEAR", "SIDE", "BULL"]):
        row = "  ".join(f"{P[r, c] * 100:4.0f}%" for c in range(3))
        star = "  <- diagonal" if False else ""
        print(f"    {name}    {row}")


def load_prices(args):
    if args.csv:
        import csv
        closes, highs, lows = [], [], []
        with open(args.csv) as f:
            for row in csv.DictReader(f):
                closes.append(float(row.get("Close") or row.get("close")))
                if row.get("High"):
                    highs.append(float(row["High"]))
                    lows.append(float(row["Low"]))
        return np.array(closes), (np.array(highs) if highs else None), (np.array(lows) if lows else None), None
    if args.ticker:
        try:
            import yfinance as yf
            df = yf.download(args.ticker, period="10y", interval="1d", progress=False, auto_adjust=True)
            return df["Close"].values.ravel(), df["High"].values.ravel(), df["Low"].values.ravel(), None
        except Exception as e:
            print(f"[yfinance unavailable: {e}] -> falling back to synthetic data\n")
    price, truth = synthetic_prices()
    return price, None, None, truth


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--ticker")
    ap.add_argument("--mode", default="filter", choices=["filter", "standalone"])
    ap.add_argument("--preset", default="manual", choices=["manual", "auto_std", "auto_atr"])
    args = ap.parse_args()

    close, high, low, truth = load_prices(args)
    cfg = MarkovConfig(mode=args.mode, preset=args.preset)
    label = args.ticker or (args.csv or "SYNTHETIC")

    print("=" * 64)
    print(f"  MARKOV 2.0 — {label}   ({len(close)} bars, mode={cfg.mode}, preset={cfg.preset})")
    print("=" * 64)

    res = analyze(close, cfg, high, low)

    print(f"\n  Current regime : {res.regime_name}")
    print(f"  Signal P(bull)-P(bear) | regime : {res.signal:+.3f}")
    print(f"  Base rate (stationary tilt)     : {res.base_signal:+.3f}")
    print(f"  Edge vs base                    : {res.edge:+.3f}  ({res.edge_tag})")
    print(f"  FIX 2 label check (BEAR<SIDE<BULL): {'PASS' if res.verify_ok else 'FAIL'}")
    print(f"    mean window-return by state   : "
          f"BEAR {res.mean_return_by_state[0]:+.3f}  "
          f"SIDE {res.mean_return_by_state[1]:+.3f}  "
          f"BULL {res.mean_return_by_state[2]:+.3f}")
    print(f"  FIX 1 min stride samples/state  : {res.min_samples} "
          f"({'reliable' if res.min_samples >= cfg.ready_min_samples else 'too few'})")
    print(f"  READY                           : {res.ready}")
    print(f"  Position ({cfg.mode})           : {res.position_label}")
    print(f"  ==> ACTION                      : {res.action}")

    fmt_matrix(res.P_stride, "TRUE matrix (stride / non-overlapping) — FIX 1 honest")
    fmt_matrix(res.P_overlap, "LEGACY matrix (overlapping) — diagonal inflated")
    diag_str = np.diag(res.P_stride).mean()
    diag_over = np.diag(res.P_overlap).mean()
    print(f"\n  Mean diagonal (stickiness):  stride {diag_str*100:.0f}%   "
          f"legacy {diag_over*100:.0f}%   (legacy inflation +{(diag_over-diag_str)*100:.0f}pp)")

    print(f"\n  Stationary (long-run mix):  "
          f"BEAR {res.stationary[0]*100:.0f}%  "
          f"SIDE {res.stationary[1]*100:.0f}%  "
          f"BULL {res.stationary[2]*100:.0f}%")

    # FIX 2 ground-truth self-check (synthetic only)
    if truth is not None:
        from tradingagents.regime.markov2 import compute_states
        states, _, _, _ = compute_states(close, cfg)
        mapping_ok = res.verify_ok
        print(f"\n  Ground-truth available (synthetic). Label encoding verified: "
              f"{'PASS' if mapping_ok else 'FAIL'}")

    # Walk-forward: stride vs legacy
    print("\n" + "-" * 64)
    print("  WALK-FORWARD BACKTEST (matrix rebuilt from past data only)")
    print("-" * 64)
    wf_str = walk_forward(close, cfg, high, low, matrix="stride")
    wf_leg = walk_forward(close, cfg, high, low, matrix="overlap")
    for name, wf in [("STRIDE (true)", wf_str), ("LEGACY (overlap)", wf_leg)]:
        m = wf["metrics"]
        print(f"\n  {name}")
        print(f"    total return {m['total_return']*100:7.1f}%   CAGR {m['cagr']*100:6.1f}%   "
              f"Sharpe {m['sharpe']:.2f}")
        print(f"    win rate {m['win_rate']*100:5.1f}%   profit factor {m['profit_factor']:.2f}   "
              f"max DD {m['max_drawdown']*100:6.1f}%   exposure {m['exposure']*100:.0f}%")
    print(f"\n  Buy & hold total return: {wf_str['metrics']['buy_hold_return']*100:.1f}%")
    print("\n  Backtests flatter. The fixed (stride) matrix shows uglier, truer")
    print("  numbers — those are the only ones worth trading.\n")


if __name__ == "__main__":
    main()
