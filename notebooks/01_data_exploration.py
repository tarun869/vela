"""Notebook 01: Exploratory data analysis of LMP prices."""
# Run as: python notebooks/01_data_exploration.py
# Or open in Jupyter: jupytext --to notebook notebooks/01_data_exploration.py

import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone

# --- Generate synthetic CAISO LMP data ---
np.random.seed(42)
DAILY_PATTERN = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
                 50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
DAYS = 30

prices = []
timestamps = []
base = datetime.now(timezone.utc) - timedelta(days=DAYS)
for d in range(DAYS):
    for h in range(24):
        ts = base + timedelta(days=d, hours=h)
        p = max(0, DAILY_PATTERN[h] + np.random.normal(0, 8))
        prices.append(p)
        timestamps.append(ts)

prices = np.array(prices)
print(f"LMP Statistics ({DAYS} days, {len(prices)} hours):")
print(f"  Mean:   ${prices.mean():.2f}/MWh")
print(f"  Median: ${np.median(prices):.2f}/MWh")
print(f"  Std:    ${prices.std():.2f}/MWh")
print(f"  Min:    ${prices.min():.2f}/MWh")
print(f"  Max:    ${prices.max():.2f}/MWh")
print(f"  P10:    ${np.percentile(prices, 10):.2f}/MWh")
print(f"  P90:    ${np.percentile(prices, 90):.2f}/MWh")
print(f"  Negative hours: {(prices < 0).sum()}")

# --- Hourly averages ---
hourly_avg = [np.mean([prices[h + d * 24] for d in range(DAYS)]) for h in range(24)]
print("\nHourly Average LMP ($/ MWh):")
for h, avg in enumerate(hourly_avg):
    bar = "#" * int(avg / 5)
    print(f"  HE{h+1:02d}: {avg:6.2f} {bar}")

# --- Peak vs off-peak ---
peak_mask = np.array([8 <= ts.hour < 22 for ts in timestamps])
peak_prices = prices[peak_mask]
off_peak_prices = prices[~peak_mask]
print(f"\nPeak (HE8-22):    mean=${peak_prices.mean():.2f}, std=${peak_prices.std():.2f}")
print(f"Off-peak (HE0-8): mean=${off_peak_prices.mean():.2f}, std=${off_peak_prices.std():.2f}")
print(f"Peak premium:     ${peak_prices.mean() - off_peak_prices.mean():.2f}/MWh")

# --- Arbitrage spread analysis ---
spreads = []
for d in range(DAYS):
    day_prices = prices[d * 24 : (d + 1) * 24]
    spread = day_prices.max() - day_prices.min()
    spreads.append(spread)
spreads = np.array(spreads)
print(f"\nDaily Price Spread:")
print(f"  Mean: ${spreads.mean():.2f}/MWh")
print(f"  P25:  ${np.percentile(spreads, 25):.2f}/MWh")
print(f"  P75:  ${np.percentile(spreads, 75):.2f}/MWh")
print(f"  Max:  ${spreads.max():.2f}/MWh")
