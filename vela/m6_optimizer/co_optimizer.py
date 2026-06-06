"""High-level co-optimizer wrapping MILP, co-optimization, and stochastic modules."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class VPPDispatchPlan(NamedTuple):
    """Complete dispatch plan for a VPP fleet."""
    plan_id: str
    horizon: int
    assets: list[str]
    charge_mw: dict[str, list[float]]
    discharge_mw: dict[str, list[float]]
    reg_up_mw: dict[str, list[float]]
    reg_down_mw: dict[str, list[float]]
    spin_mw: dict[str, list[float]]
    soc: dict[str, list[float]]
    energy_revenue: float
    as_revenue: float
    total_revenue: float
    solver_used: str
    solve_time_s: float
    metadata: dict[str, Any]


@dataclass
class FleetAsset:
    """Fleet-level asset descriptor."""
    asset_id: str
    site_id: str
    capacity_mwh: float
    power_mw: float
    rte: float = 0.92
    soc_init: float = 0.5
    soc_min: float = 0.05
    soc_max: float = 0.95
    reg_up_capable: bool = True
    reg_down_capable: bool = True
    spin_capable: bool = True


@dataclass
class VPPCoOptimizer:
    """
    Top-level VPP co-optimizer.

    Selects the best available solver (highspy MILP, greedy, or heuristic)
    and co-optimizes energy + ancillary services for the full fleet.

    Dispatches to:
    - co_optimization.CoOptimizer for energy+AS co-opt (primary)
    - milp.MILPDispatchOptimizer for energy-only
    - stochastic.StochasticMPC for scenario-based risk management
    """
    horizon: int = 24
    dt_hours: float = 1.0
    enable_as: bool = True
    enable_stochastic: bool = False
    n_scenarios: int = 10

    def optimize(
        self,
        assets: list[FleetAsset],
        lmp: list[float],
        reg_up_price: list[float] | None = None,
        reg_down_price: list[float] | None = None,
        spin_price: list[float] | None = None,
        plan_id: str = "",
    ) -> VPPDispatchPlan:
        """
        Main optimization entry point.

        Automatically selects co-optimization if AS prices are provided,
        otherwise falls back to energy-only MILP.
        """
        t0 = time.perf_counter()
        T = self.horizon

        # Default AS prices
        rup = reg_up_price or [0.0] * T
        rdn = reg_down_price or [0.0] * T
        sp = spin_price or [0.0] * T

        has_as = self.enable_as and any(p > 1.0 for p in rup)

        if has_as:
            plan = self._run_co_optimization(assets, lmp, rup, rdn, sp, t0, plan_id)
        else:
            plan = self._run_energy_only(assets, lmp, t0, plan_id)

        logger.info(
            "VPP dispatch plan %s: revenue=$%.2f (energy=$%.2f, AS=$%.2f), solver=%s, t=%.3fs",
            plan.plan_id, plan.total_revenue, plan.energy_revenue, plan.as_revenue,
            plan.solver_used, plan.solve_time_s,
        )
        return plan

    def _run_co_optimization(
        self,
        assets: list[FleetAsset],
        lmp: list[float],
        rup: list[float],
        rdn: list[float],
        sp: list[float],
        t0: float,
        plan_id: str,
    ) -> VPPDispatchPlan:
        from .co_optimization import CoOptimizer, AssetSpec

        specs = [
            AssetSpec(
                asset_id=a.asset_id,
                capacity_mwh=a.capacity_mwh,
                power_mw=a.power_mw,
                rte=a.rte,
                soc_init=a.soc_init,
                soc_min=a.soc_min,
                soc_max=a.soc_max,
                reg_up_capability=1.0 if a.reg_up_capable else 0.0,
                reg_down_capability=1.0 if a.reg_down_capable else 0.0,
                spin_capability=1.0 if a.spin_capable else 0.0,
            )
            for a in assets
        ]

        optimizer = CoOptimizer(horizon=self.horizon, dt_hours=self.dt_hours)
        sol = optimizer.solve(specs, lmp, rup, rdn, sp)

        return VPPDispatchPlan(
            plan_id=plan_id or f"co_opt_{int(t0)}",
            horizon=self.horizon,
            assets=[a.asset_id for a in assets],
            charge_mw=sol.charge_mw,
            discharge_mw=sol.discharge_mw,
            reg_up_mw=sol.reg_up_mw,
            reg_down_mw=sol.reg_down_mw,
            spin_mw=sol.spin_mw,
            soc=sol.soc,
            energy_revenue=sol.energy_revenue,
            as_revenue=sol.reg_up_revenue + sol.reg_down_revenue + sol.spin_revenue,
            total_revenue=sol.total_revenue,
            solver_used=f"co_opt_{sol.status}",
            solve_time_s=sol.solve_time_s,
            metadata={"status": sol.status},
        )

    def _run_energy_only(
        self,
        assets: list[FleetAsset],
        lmp: list[float],
        t0: float,
        plan_id: str,
    ) -> VPPDispatchPlan:
        from .milp import MILPDispatchOptimizer, Asset

        specs = [
            Asset(
                asset_id=a.asset_id,
                capacity_mwh=a.capacity_mwh,
                power_mw=a.power_mw,
                rte=a.rte,
                soc_init=a.soc_init,
                soc_min=a.soc_min,
                soc_max=a.soc_max,
            )
            for a in assets
        ]

        optimizer = MILPDispatchOptimizer(horizon=self.horizon, dt_hours=self.dt_hours)
        sol = optimizer.solve(specs, lmp)
        T = self.horizon

        return VPPDispatchPlan(
            plan_id=plan_id or f"energy_{int(t0)}",
            horizon=self.horizon,
            assets=[a.asset_id for a in assets],
            charge_mw=sol.charge_mw,
            discharge_mw=sol.discharge_mw,
            reg_up_mw={a.asset_id: [0.0] * T for a in assets},
            reg_down_mw={a.asset_id: [0.0] * T for a in assets},
            spin_mw={a.asset_id: [0.0] * T for a in assets},
            soc=sol.soc,
            energy_revenue=sol.objective,
            as_revenue=0.0,
            total_revenue=sol.objective,
            solver_used=f"energy_{sol.status}",
            solve_time_s=sol.solve_time_s,
            metadata={"status": sol.status},
        )

    def batch_optimize(
        self,
        assets: list[FleetAsset],
        lmp_matrix: list[list[float]],   # shape: (n_days, horizon)
        reg_up_matrix: list[list[float]] | None = None,
        reg_down_matrix: list[list[float]] | None = None,
        spin_matrix: list[list[float]] | None = None,
    ) -> list[VPPDispatchPlan]:
        """
        Optimize dispatch for multiple days in sequence.

        SOC at end of each day is carried over to initialize the next.
        """
        plans = []
        n_days = len(lmp_matrix)
        current_soc = {a.asset_id: a.soc_init for a in assets}

        for d in range(n_days):
            # Update initial SOC from previous day
            updated_assets = []
            for a in assets:
                from dataclasses import replace
                updated_assets.append(FleetAsset(
                    asset_id=a.asset_id,
                    site_id=a.site_id,
                    capacity_mwh=a.capacity_mwh,
                    power_mw=a.power_mw,
                    rte=a.rte,
                    soc_init=current_soc[a.asset_id],
                    soc_min=a.soc_min,
                    soc_max=a.soc_max,
                    reg_up_capable=a.reg_up_capable,
                    reg_down_capable=a.reg_down_capable,
                    spin_capable=a.spin_capable,
                ))

            plan = self.optimize(
                assets=updated_assets,
                lmp=lmp_matrix[d],
                reg_up_price=reg_up_matrix[d] if reg_up_matrix else None,
                reg_down_price=reg_down_matrix[d] if reg_down_matrix else None,
                spin_price=spin_matrix[d] if spin_matrix else None,
                plan_id=f"day_{d}",
            )
            plans.append(plan)

            # Carry SOC forward
            for a_id, soc_traj in plan.soc.items():
                if soc_traj:
                    current_soc[a_id] = soc_traj[-1]

        return plans

    def revenue_summary(self, plans: list[VPPDispatchPlan]) -> dict[str, float]:
        """Aggregate revenue statistics across a list of plans."""
        total = sum(p.total_revenue for p in plans)
        energy = sum(p.energy_revenue for p in plans)
        as_rev = sum(p.as_revenue for p in plans)
        return {
            "total_revenue": total,
            "energy_revenue": energy,
            "as_revenue": as_rev,
            "as_fraction": as_rev / (total + 1e-6),
            "avg_daily_revenue": total / (len(plans) + 1e-6),
            "n_plans": float(len(plans)),
        }
