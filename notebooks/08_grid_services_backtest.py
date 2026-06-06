"""Notebook 08: Grid services backtesting over historical data."""
import numpy as np
from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer

np.random.seed(99)
DAYS = 7
DAILY_LMP = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
DAILY_REG_UP = [12, 11, 10, 9, 9, 11, 15, 22, 25, 23, 20, 18,
                17, 18, 19, 21, 26, 35, 40, 42, 33, 24, 18, 14]

asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
optimizer = MILPDispatchOptimizer(horizon=24)

print("Grid Services Backtest (7 days)")
print("=" * 60)
print(f"{'Day':>4} {'LMP Rev':>10} {'+Reg Rev':>10} {'Uplift':>8} {'Uplift%':>8}")
print("-" * 45)

total_energy_rev = 0.0
total_co_rev = 0.0

for d in range(DAYS):
    lmp = [max(0, DAILY_LMP[h] + np.random.normal(0, 6)) for h in range(24)]
    reg_up = [max(0, DAILY_REG_UP[h] + np.random.normal(0, 2)) for h in range(24)]

    sol_e = optimizer.solve(assets=[asset], lmp=lmp)
    sol_co = optimizer.solve(assets=[asset], lmp=lmp, reg_up_price=reg_up)

    rev_e = sol_e.objective if sol_e.status in ("Optimal", "Feasible") else 0
    rev_co = sol_co.objective if sol_co.status in ("Optimal", "Feasible") else 0
    uplift = rev_co - rev_e
    pct = 100 * uplift / rev_e if rev_e > 0 else 0

    total_energy_rev += rev_e
    total_co_rev += rev_co
    print(f"{d+1:>4} ${rev_e:>9.2f} ${rev_co:>9.2f} ${uplift:>7.2f} {pct:>7.1f}%")

print("-" * 45)
total_uplift = total_co_rev - total_energy_rev
pct_total = 100 * total_uplift / total_energy_rev if total_energy_rev > 0 else 0
print(f"{'TOT':>4} ${total_energy_rev:>9.2f} ${total_co_rev:>9.2f} ${total_uplift:>7.2f} {pct_total:>7.1f}%")
print(f"\nConclusion: Adding regulation increases revenue by {pct_total:.1f}% ({DAYS}-day backtest)")
