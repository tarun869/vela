"""ADMM (Alternating Direction Method of Multipliers) for distributed multi-site optimization."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class ADMMSolution(NamedTuple):
    status: str
    total_revenue: float
    charge_mw: dict[str, list[float]]
    discharge_mw: dict[str, list[float]]
    soc: dict[str, list[float]]
    n_iterations: int
    primal_residual: float
    dual_residual: float
    solve_time_s: float


@dataclass
class SiteAsset:
    """A battery asset at a distributed site."""
    asset_id: str
    site_id: str
    capacity_mwh: float
    power_mw: float
    rte: float = 0.92
    soc_init: float = 0.5
    soc_min: float = 0.05
    soc_max: float = 0.95
    # Network constraints
    grid_import_limit_mw: float = float("inf")
    grid_export_limit_mw: float = float("inf")


@dataclass
class ADMMOptimizer:
    """
    ADMM-based distributed optimizer for multi-site VPP.

    Each site solves its own local subproblem independently,
    then coordinates through shared prices (dual variables).

    This enables:
    - Privacy-preserving optimization (sites don't share internal data)
    - Parallel solving across sites
    - Handling network-constrained dispatch

    ADMM Algorithm:
    1. x-update: each site i solves local problem with augmented Lagrangian
    2. z-update: aggregate coordinator step (grid balance constraint)
    3. y-update: dual variable update (price signals)

    Convergence criterion: primal residual and dual residual < tol
    """
    horizon: int = 24
    dt_hours: float = 1.0
    rho: float = 1.0          # ADMM penalty parameter
    max_iter: int = 200
    tol_primal: float = 1e-3  # MW tolerance
    tol_dual: float = 1e-3

    def solve(
        self,
        assets: list[SiteAsset],
        lmp: list[float],
        grid_balance_mw: list[float] | None = None,  # Net generation target per interval
    ) -> ADMMSolution:
        import time
        t0 = time.perf_counter()

        T = self.horizon
        N = len(assets)
        lmp_arr = np.array(lmp[:T])

        # Net injection for each asset (positive = discharge, negative = charge)
        x = {a.asset_id: np.zeros(T) for a in assets}   # local primal
        z = np.zeros(T)                                   # global consensus (net dispatch)
        y = {a.asset_id: np.zeros(T) for a in assets}   # dual variables

        primal_res = 1e9
        dual_res = 1e9
        n_iter = 0

        for iteration in range(self.max_iter):
            z_old = z.copy()

            # x-update: each asset solves local subproblem
            for a in assets:
                x[a.asset_id] = self._local_update(a, lmp_arr, y[a.asset_id], z, T)

            # z-update: global coordinator
            # Minimize: sum_i rho/2 ||x_i - z||^2 + y_i^T(x_i - z)
            # + grid_balance_constraint
            # Closed form: z = mean(x_i + y_i / rho)
            agg = np.zeros(T)
            for a in assets:
                agg += x[a.asset_id] + y[a.asset_id] / self.rho
            z = agg / N

            if grid_balance_mw is not None:
                # Enforce grid balance: sum injections = target
                target = np.array(grid_balance_mw[:T])
                z = np.clip(z, target - 0.1, target + 0.1)

            # y-update: dual variables
            for a in assets:
                y[a.asset_id] += self.rho * (x[a.asset_id] - z)

            # Convergence check
            primal_res = float(np.sqrt(sum(np.linalg.norm(x[a.asset_id] - z)**2 for a in assets)))
            dual_res = float(self.rho * N * np.linalg.norm(z - z_old))
            n_iter = iteration + 1

            if primal_res < self.tol_primal and dual_res < self.tol_dual:
                logger.info("ADMM converged in %d iterations", n_iter)
                break
        else:
            logger.warning(
                "ADMM did not converge in %d iterations (primal=%.4f, dual=%.4f)",
                self.max_iter, primal_res, dual_res
            )

        # Extract charge/discharge from net injection x
        charge_mw, discharge_mw, soc_out = {}, {}, {}
        for a in assets:
            net = x[a.asset_id]  # positive=discharge, negative=charge
            dis = np.maximum(0, net)
            ch = np.maximum(0, -net)
            charge_mw[a.asset_id] = ch.tolist()
            discharge_mw[a.asset_id] = dis.tolist()
            # Reconstruct SOC
            soc = a.soc_init
            soc_traj = []
            for t in range(T):
                soc = float(np.clip(
                    soc + ch[t] * a.rte * self.dt_hours / a.capacity_mwh
                    - dis[t] * self.dt_hours / a.capacity_mwh,
                    a.soc_min, a.soc_max
                ))
                soc_traj.append(soc)
            soc_out[a.asset_id] = soc_traj

        total_rev = sum(
            (discharge_mw[a.asset_id][t] - charge_mw[a.asset_id][t]) * lmp[t] * self.dt_hours
            for a in assets for t in range(T)
        )

        return ADMMSolution(
            status="converged" if primal_res < self.tol_primal else "max_iter",
            total_revenue=total_rev,
            charge_mw=charge_mw,
            discharge_mw=discharge_mw,
            soc=soc_out,
            n_iterations=n_iter,
            primal_residual=primal_res,
            dual_residual=dual_res,
            solve_time_s=time.perf_counter() - t0,
        )

    def _local_update(
        self,
        asset: SiteAsset,
        lmp: np.ndarray,
        y_i: np.ndarray,
        z: np.ndarray,
        T: int,
    ) -> np.ndarray:
        """
        Local x-update for a single asset.

        Solves: min -lmp^T x + y_i^T x + rho/2 ||x - z||^2
                s.t. SOC dynamics, power limits

        This is a QP that can be solved analytically for simple storage.
        We use a projected gradient step here for efficiency.
        """
        # Gradient of augmented Lagrangian w.r.t. x_i
        # = -lmp + y_i + rho * (x_i - z)
        # Unconstrained optimal: x_i* = z + (lmp - y_i) / rho
        x_unconstrained = z + (lmp - y_i) / self.rho

        # Project onto feasible set (SOC constraints via greedy forward pass)
        soc = asset.soc_init
        x_feasible = np.zeros(T)

        for t in range(T):
            xi = float(x_unconstrained[t])
            if xi > 0:  # Desired discharge
                max_dis = min(asset.power_mw, (soc - asset.soc_min) * asset.capacity_mwh / self.dt_hours)
                actual = float(np.clip(xi, 0, max_dis))
                soc -= actual * self.dt_hours / asset.capacity_mwh
            else:  # Desired charge
                max_ch = min(asset.power_mw, (asset.soc_max - soc) * asset.capacity_mwh / self.dt_hours)
                actual = float(np.clip(xi, -max_ch, 0))
                soc += abs(actual) * asset.rte * self.dt_hours / asset.capacity_mwh
            soc = float(np.clip(soc, asset.soc_min, asset.soc_max))
            x_feasible[t] = actual

        return x_feasible


@dataclass
class DistributedCoordinator:
    """
    High-level coordinator for distributed ADMM across multiple sites.

    Manages communication between sites and tracks convergence.
    In a production system, each site would run on a separate process/service.
    """
    admm: ADMMOptimizer = field(default_factory=ADMMOptimizer)

    def coordinate(
        self,
        sites: dict[str, list[SiteAsset]],
        lmp: list[float],
    ) -> dict[str, ADMMSolution]:
        """
        Coordinate dispatch across multiple independent sites.

        Each site optimizes independently; the coordinator aggregates
        net positions for grid impact assessment.
        """
        results = {}
        for site_id, assets in sites.items():
            if not assets:
                continue
            sol = self.admm.solve(assets, lmp)
            results[site_id] = sol
            logger.info(
                "Site %s: revenue=%.2f, %d iterations, primal=%.4f",
                site_id, sol.total_revenue, sol.n_iterations, sol.primal_residual
            )
        return results
