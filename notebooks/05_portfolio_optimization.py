"""Notebook 05: Multi-site portfolio optimization."""
import numpy as np
from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer

np.random.seed(42)
DAILY = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
         50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
lmp = [max(0, p + np.random.normal(0, 5)) for p in DAILY]

ASSETS = [
    Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.60),
    Asset(asset_id="bat-002", capacity_mwh=8.0, power_mw=4.0, soc_init=0.45),
    Asset(asset_id="bat-003", capacity_mwh=2.0, power_mw=1.0, soc_init=0.80),
    Asset(asset_id="bat-004", capacity_mwh=12.0, power_mw=6.0, soc_init=0.50),
]

optimizer = MILPDispatchOptimizer(horizon=24)
fleet_solution = optimizer.solve(assets=ASSETS, lmp=lmp)

print("Portfolio Optimization Results")
print("=" * 65)
print(f"Fleet:    {len(ASSETS)} assets, {sum(a.capacity_mwh for a in ASSETS):.1f} MWh total")
print(f"Status:   {fleet_solution.status}")
print(f"Revenue:  ${fleet_solution.objective:.2f}")
print(f"Solve:    {fleet_solution.solve_time_s:.3f}s")
print()

# Compare individual vs. fleet optimization
print("Individual vs. Portfolio Revenue:")
print(f"{'Asset':>12} {'Capacity':>10} {'Individual':>12} {'Portfolio':>12}")
print("-" * 50)
total_individual = 0
for asset in ASSETS:
    sol_ind = optimizer.solve(assets=[asset], lmp=lmp)
    ind_rev = sol_ind.objective if sol_ind.status in ("Optimal", "Feasible") else 0
    port_rev = sum(
        fleet_solution.discharge_mw[asset.asset_id][t] * lmp[t]
        for t in range(24)
    ) if asset.asset_id in fleet_solution.discharge_mw else 0
    total_individual += ind_rev
    print(f"{asset.asset_id:>12} {asset.capacity_mwh:>10.1f} ${ind_rev:>11.2f} ${port_rev:>11.2f}")
print(f"\nPortfolio revenue: ${fleet_solution.objective:.2f}")
print(f"Sum of individual: ${total_individual:.2f}")
diff = fleet_solution.objective - total_individual
print(f"Portfolio synergy: ${diff:+.2f} ({100*diff/total_individual:+.1f}%)" if total_individual > 0 else "")
