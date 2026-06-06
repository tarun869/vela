"""Notebook 02: Battery dispatch optimization demo."""
import numpy as np
from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer

np.random.seed(42)
DAILY_LMP = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
lmp = [max(0, p + np.random.normal(0, 5)) for p in DAILY_LMP]

asset = Asset(
    asset_id="bat-001",
    capacity_mwh=4.0,
    power_mw=2.0,
    rte=0.92,
    soc_init=0.5,
)

optimizer = MILPDispatchOptimizer(horizon=24)
solution = optimizer.solve(assets=[asset], lmp=lmp)

print("Battery Dispatch Optimization Results")
print("=" * 60)
print(f"Status:    {solution.status}")
print(f"Revenue:   ${solution.objective:.2f}")
print(f"Solve:     {solution.solve_time_s:.3f}s")
print()
print(f"{'Hour':>4} {'LMP':>8} {'Charge':>8} {'Disch.':>8} {'SOC':>8} {'Rev':>10} {'Action':>8}")
print("-" * 58)
total_rev = 0.0
for t in range(24):
    c = solution.charge_mw["bat-001"][t]
    d = solution.discharge_mw["bat-001"][t]
    soc = solution.soc["bat-001"][t]
    rev = d * lmp[t] - c * lmp[t]
    total_rev += max(0, d * lmp[t])
    action = "CHARGE" if c > 0.01 else ("DISCH" if d > 0.01 else "IDLE")
    print(f"{t+1:>4} {lmp[t]:>8.2f} {c:>8.3f} {d:>8.3f} {soc:>8.3f} {d*lmp[t]:>10.2f} {action:>8}")

print(f"\nTotal Revenue: ${total_rev:.2f}")
total_charge = sum(solution.charge_mw["bat-001"])
total_discharge = sum(solution.discharge_mw["bat-001"])
print(f"Total Charge:    {total_charge:.3f} MWh")
print(f"Total Discharge: {total_discharge:.3f} MWh")
if total_charge > 0:
    print(f"Realized RTE:    {total_discharge/total_charge:.3f}")
