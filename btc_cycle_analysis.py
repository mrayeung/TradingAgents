"""
BTC Cycle Analysis — validate peak/bottom timing against TradingView chart annotations.

Checks:
  ① Peak → Peak:   chart shows 204 bars / 1,428 days
  ② Peak → Bottom: chart shows  53 bars /   371 days
  ③ Projects next bottom from the 2025 ATH

Run:
  python btc_cycle_analysis.py
"""

import yfinance as yf
import pandas as pd
from datetime import timedelta

# ── 1. Download weekly BTC-USD ─────────────────────────────────────────────────
print("Downloading BTC-USD weekly data …")
df = yf.download("BTC-USD", start="2016-01-01", end="2026-01-01",
                 interval="1wk", auto_adjust=True, progress=False)
df = df[["Close"]].dropna()
df.index = pd.to_datetime(df.index).tz_localize(None)
print(f"  {len(df)} weekly candles  ({df.index[0].date()} → {df.index[-1].date()})\n")

# ── 2. Define known cycle turning points ──────────────────────────────────────
# Confirmed on-chain / TradingView weekly closes
PEAKS = {
    "Cycle 1 peak (2017)": "2017-12-17",
    "Cycle 2 peak (2021)": "2021-11-08",
    "Cycle 3 peak (2025)": "2025-01-20",   # ATH week ~$108k
}
BOTTOMS = {
    "Cycle 1 bottom (2018)": "2018-12-16",
    "Cycle 2 bottom (2022)": "2022-11-21",
}

def nearest_weekly_close(df: pd.DataFrame, date_str: str) -> tuple[pd.Timestamp, float]:
    """Return the actual weekly close date + price nearest to date_str."""
    target = pd.Timestamp(date_str)
    idx = df.index.get_indexer([target], method="nearest")[0]
    ts = df.index[idx]
    price = float(df["Close"].iloc[idx])
    return ts, price

print("=" * 62)
print("  CONFIRMED TURNING POINTS")
print("=" * 62)

peaks  = {}
bottoms = {}

for label, d in PEAKS.items():
    ts, price = nearest_weekly_close(df, d)
    peaks[label] = ts
    print(f"  {label:<32}  {ts.date()}  ${price:>10,.0f}")

print()
for label, d in BOTTOMS.items():
    ts, price = nearest_weekly_close(df, d)
    bottoms[label] = ts
    print(f"  {label:<32}  {ts.date()}  ${price:>10,.0f}")

# ── 3. Peak → Peak ────────────────────────────────────────────────────────────
print()
print("=" * 62)
print("  PEAK → PEAK  (chart annotation: 204 bars / 1,428 days)")
print("=" * 62)

p1 = peaks["Cycle 1 peak (2017)"]
p2 = peaks["Cycle 2 peak (2021)"]
p3 = peaks["Cycle 3 peak (2025)"]

for (label_a, a), (label_b, b) in [
    (("Cycle 1→2", p1), ("", p2)),
    (("Cycle 2→3", p2), ("", p3)),
]:
    days  = (b - a).days
    weeks = days / 7
    print(f"  {label_a}:  {a.date()} → {b.date()}")
    print(f"           {days:,} days  /  {weeks:.1f} weeks  /  {days/365.25:.2f} years")
    print(f"           Chart says: 1,428 days — delta: {days - 1428:+d} days")
    print()

# ── 4. Peak → Bottom ─────────────────────────────────────────────────────────
print("=" * 62)
print("  PEAK → BOTTOM  (chart annotation: 53 bars / 371 days)")
print("=" * 62)

combos = [
    ("Cycle 1", peaks["Cycle 1 peak (2017)"], bottoms["Cycle 1 bottom (2018)"]),
    ("Cycle 2", peaks["Cycle 2 peak (2021)"], bottoms["Cycle 2 bottom (2022)"]),
]
for label, peak, bot in combos:
    days  = (bot - peak).days
    weeks = days / 7
    price_at_peak  = float(df["Close"].reindex([peak],  method="nearest").iloc[0])
    price_at_bot   = float(df["Close"].reindex([bot],   method="nearest").iloc[0])
    drawdown = (price_at_bot - price_at_peak) / price_at_peak * 100
    print(f"  {label}:  {peak.date()} → {bot.date()}")
    print(f"           {days:,} days  /  {weeks:.1f} weeks")
    print(f"           Drawdown: {drawdown:.1f}%  (${price_at_peak:,.0f} → ${price_at_bot:,.0f})")
    print(f"           Chart says: 371 days — delta: {days - 371:+d} days")
    print()

# ── 5. Cycle 3 projection ─────────────────────────────────────────────────────
print("=" * 62)
print("  CYCLE 3 PROJECTION  (from Jan 2025 ATH)")
print("=" * 62)

p3_date = peaks["Cycle 3 peak (2025)"]
p3_price, _ = nearest_weekly_close(df, str(p3_date.date()))

avg_p2p  = ((p2 - p1).days + (p3 - p2).days) / 2
avg_p2b  = ((bottoms["Cycle 1 bottom (2018)"] - p1).days +
             (bottoms["Cycle 2 bottom (2022)"] - p2).days) / 2

proj_bottom   = p3_date + timedelta(days=avg_p2b)
proj_next_top = p3_date + timedelta(days=avg_p2p)

# Drawdown at bottom: avg of prior two cycles
_, price_b1 = nearest_weekly_close(df, str(bottoms["Cycle 1 bottom (2018)"].date()))
_, price_p1 = nearest_weekly_close(df, str(p1.date()))
_, price_b2 = nearest_weekly_close(df, str(bottoms["Cycle 2 bottom (2022)"].date()))
_, price_p2 = nearest_weekly_close(df, str(p2.date()))
_, price_p3 = nearest_weekly_close(df, str(p3_date.date()))

dd1 = price_b1 / price_p1
dd2 = price_b2 / price_p2
avg_dd = (dd1 + dd2) / 2
proj_bottom_price = price_p3 * avg_dd

print(f"  Avg peak-to-peak:   {avg_p2p:.0f} days  ({avg_p2p/7:.1f} weeks)")
print(f"  Avg peak-to-bottom: {avg_p2b:.0f} days  ({avg_p2b/7:.1f} weeks)")
print()
print(f"  Cycle 3 ATH:        {p3_date.date()}  @ ${price_p3:,.0f}")
print()
print(f"  → Projected bottom: {proj_bottom.date()}  (~${proj_bottom_price:,.0f})")
print(f"    Avg cycle drawdown from ATH: {(avg_dd-1)*100:.1f}%")
print(f"    Cycle 1 drawdown: {(dd1-1)*100:.1f}%  |  Cycle 2 drawdown: {(dd2-1)*100:.1f}%")
print()
print(f"  → Projected next peak: {proj_next_top.date()}")
print()
print(f"  Chart H&S target: $37,508  /  chart bottom date: ~14 Sep 2026")
print(f"  This model's target: ${proj_bottom_price:,.0f}  /  date: {proj_bottom.date()}")
print("=" * 62)
