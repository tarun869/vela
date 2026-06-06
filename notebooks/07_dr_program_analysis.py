"""Notebook 07: Demand response program analysis."""
import numpy as np
from datetime import datetime, timedelta, timezone

np.random.seed(7)

# --- Simulate DR event history ---
DR_PROGRAMS = {
    "CAISO_DRAM": {"price": 250, "events_per_month": 4, "duration_h": 2},
    "CAISO_CBP": {"price": 150, "events_per_month": 8, "duration_h": 1},
    "PGE_BIP": {"price": 500, "events_per_month": 2, "duration_h": 4},
}

ASSET_CAPACITY_MW = 6.0  # total enrolled MW
DELIVERY_RATE = 0.97

print("Demand Response Program Analysis")
print("=" * 60)
print(f"Enrolled Capacity: {ASSET_CAPACITY_MW} MW")
print(f"Delivery Rate:     {DELIVERY_RATE*100:.1f}%")
print()

annual_revenues = {}
for program_name, params in DR_PROGRAMS.items():
    monthly_events = params["events_per_month"]
    duration = params["duration_h"]
    price = params["price"]
    annual_events = monthly_events * 12
    annual_revenue = annual_events * duration * ASSET_CAPACITY_MW * DELIVERY_RATE * price
    annual_revenues[program_name] = annual_revenue
    print(f"{program_name}:")
    print(f"  Events/year:    {annual_events}")
    print(f"  Duration/event: {duration}h")
    print(f"  Price:          ${price}/MWh")
    print(f"  Annual Revenue: ${annual_revenue:,.0f}")
    print()

best = max(annual_revenues, key=annual_revenues.get)
print(f"Best program (revenue): {best} (${annual_revenues[best]:,.0f}/yr)")
print(f"Total (all programs):   ${sum(annual_revenues.values()):,.0f}/yr")

# --- Event response simulation ---
print("\n\nEvent Response Simulation (20 synthetic events):")
print(f"{'Event':>6} {'Duration':>9} {'Called':>8} {'Delivered':>10} {'Revenue':>10}")
print("-" * 50)
total_rev = 0
for i in range(20):
    duration = np.random.choice([1, 2, 4])
    called = ASSET_CAPACITY_MW * np.random.uniform(0.7, 1.0)
    delivery = called * np.random.uniform(0.90, 0.99)
    price = np.random.choice([150, 250, 500])
    rev = delivery * duration * price
    total_rev += rev
    print(f"{i+1:>6} {duration:>9}h {called:>8.2f} {delivery:>10.2f} ${rev:>9.2f}")
print(f"\nTotal DR Revenue (20 events): ${total_rev:,.2f}")
