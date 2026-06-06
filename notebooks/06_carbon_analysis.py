"""Notebook 06: Carbon impact analysis of VPP dispatch."""
import numpy as np
from datetime import datetime, timedelta, timezone

np.random.seed(42)
DAYS = 30
DAILY_PATTERN = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
                 50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]

MARGINAL_RATE = [  # kg CO2/MWh by hour (higher during peak)
    320, 300, 290, 285, 288, 310,
    360, 430, 500, 490, 460, 420,
    410, 415, 430, 450, 520, 580,
    610, 640, 580, 500, 420, 370,
]

# Simulate dispatch data
charge_mwh = []
discharge_mwh = []
marginal_rates = []

for d in range(DAYS):
    for h in range(24):
        lmp = max(0, DAILY_PATTERN[h] + np.random.normal(0, 5))
        rate = MARGINAL_RATE[h] + np.random.normal(0, 30)
        # Battery charges in valley, discharges at peak
        if lmp < 30:
            c = np.random.uniform(0.5, 2.0)
            d_mwh = 0.0
        elif lmp > 80:
            c = 0.0
            d_mwh = np.random.uniform(0.5, 2.0)
        else:
            c = d_mwh = 0.0
        charge_mwh.append(c)
        discharge_mwh.append(d_mwh)
        marginal_rates.append(max(50, rate))

charge_mwh = np.array(charge_mwh)
discharge_mwh = np.array(discharge_mwh)
marginal_rates = np.array(marginal_rates)

# Carbon accounting
grid_avg_rate = 250.0  # kg CO2/MWh average grid intensity
emissions_from_charging = charge_mwh * grid_avg_rate
emissions_displaced = discharge_mwh * marginal_rates
net_avoided = emissions_displaced - emissions_from_charging

print("Carbon Impact Analysis (30-day period)")
print("=" * 55)
print(f"Total Charge:        {charge_mwh.sum():.1f} MWh")
print(f"Total Discharge:     {discharge_mwh.sum():.1f} MWh")
print(f"Charging Emissions:  {emissions_from_charging.sum()/1000:.2f} tonne CO2")
print(f"Displaced Emissions: {emissions_displaced.sum()/1000:.2f} tonne CO2")
print(f"Net Avoided:         {net_avoided.sum()/1000:.2f} tonne CO2")
print(f"Carbon Credits:      {net_avoided.sum()/1000:.2f} ACR credits")
print(f"\nAvg Marginal Rate:   {marginal_rates.mean():.1f} kg CO2/MWh")
print(f"Peak Rate:           {marginal_rates.max():.1f} kg CO2/MWh")
print(f"Valley Rate:         {marginal_rates.min():.1f} kg CO2/MWh")

# Daily breakdown
print("\nMonthly CO2 Avoided (weekly):")
for w in range(4):
    start = w * 7 * 24
    end = (w + 1) * 7 * 24
    weekly_avoided = net_avoided[start:end].sum() / 1000
    print(f"  Week {w+1}: {weekly_avoided:.3f} tonne CO2 avoided")
