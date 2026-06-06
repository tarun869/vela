"""Notebook 04: Settlement reconciliation analysis."""
import numpy as np
from datetime import datetime, timedelta, timezone
from vela.m9_settlement.settlement_engine import SettlementEngine

np.random.seed(0)
engine = SettlementEngine(market="CAISO")
settlement_date = datetime(2024, 7, 15, tzinfo=timezone.utc)

DAILY_LMP = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
lmp = [max(0, p + np.random.normal(0, 4)) for p in DAILY_LMP]

# Perfect delivery
scheduled = [1.5] * 24
metered_perfect = [1.5 + np.random.normal(0, 0.02) for _ in range(24)]
# With 5% underdelivery
metered_under = [max(0, 1.5 * 0.95 + np.random.normal(0, 0.03)) for _ in range(24)]

stmt_perfect = engine.calculate("bat-001", settlement_date, scheduled, metered_perfect, lmp)
stmt_under = engine.calculate("bat-001", settlement_date, scheduled, metered_under, lmp)

print("Settlement Reconciliation Analysis")
print("=" * 60)

for label, stmt in [("Perfect Delivery", stmt_perfect), ("5% Underdelivery", stmt_under)]:
    net = stmt.total_revenue - stmt.total_imbalance_charge
    print(f"\n{label}:")
    print(f"  Energy Delivered:  {stmt.total_energy_mwh:.3f} MWh")
    print(f"  Gross Revenue:     ${stmt.total_revenue:.2f}")
    print(f"  Imbalance Charge:  ${stmt.total_imbalance_charge:.2f}")
    print(f"  Net Revenue:       ${net:.2f}")
    print(f"  Revenue/MWh:       ${net/stmt.total_energy_mwh:.2f}" if stmt.total_energy_mwh > 0 else "")

print(f"\nRevenue penalty from 5% underdelivery: ${stmt_perfect.total_revenue - stmt_under.total_revenue:.2f}")

print("\nHourly Breakdown (first 6 hours):")
print(f"{'Hour':>4} {'LMP':>8} {'Sched':>8} {'Metered':>8} {'Imbal':>8} {'Revenue':>10}")
print("-" * 52)
for i, interval in enumerate(stmt_perfect.intervals[:6]):
    imbal = interval.metered_mwh - interval.scheduled_mwh
    print(f"{i+1:>4} {interval.lmp:>8.2f} {interval.scheduled_mwh:>8.3f} {interval.metered_mwh:>8.3f} {imbal:>8.3f} {interval.revenue:>10.4f}")
