"""MILP dispatch optimizer using HiGHS solver."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Asset:
    asset_id: str
    capacity_mwh: float
    power_mw: float
    rte: float = 0.92
    soc_init: float = 0.5
    soc_min: float = 0.05
    soc_max: float = 0.95
    charge_cost: float = 0.0
    discharge_cost: float = 0.0


class DispatchSolution(NamedTuple):
    status: str
    objective: float
    charge_mw: dict[str, list[float]]
    discharge_mw: dict[str, list[float]]
    soc: dict[str, list[float]]
    solve_time_s: float


@dataclass
class MILPDispatchOptimizer:
    """
    Rolling-horizon MILP for battery dispatch.
    Maximizes revenue from energy arbitrage + ancillary services.
    """
    horizon: int = 24
    dt_hours: float = 1.0

    def solve(
        self,
        assets: list[Asset],
        lmp: list[float],
        reg_up_price: list[float] | None = None,
        reg_down_price: list[float] | None = None,
        spin_price: list[float] | None = None,
    ) -> DispatchSolution:
        import time
        t0 = time.perf_counter()

        try:
            import highspy
            return self._solve_highs(assets, lmp, reg_up_price, reg_down_price, spin_price)
        except ImportError:
            logger.warning("highspy not available, falling back to greedy heuristic")
            return self._solve_greedy(assets, lmp)
        finally:
            pass

    def _solve_highs(
        self,
        assets: list[Asset],
        lmp: list[float],
        reg_up_price: list[float] | None,
        reg_down_price: list[float] | None,
        spin_price: list[float] | None,
    ) -> DispatchSolution:
        import highspy
        import time
        t0 = time.perf_counter()

        T = self.horizon
        N = len(assets)
        reg_up = reg_up_price or [0.0] * T
        reg_dn = reg_down_price or [0.0] * T
        spin = spin_price or [0.0] * T

        h = highspy.Highs()
        h.silent()

        # Variables: for each asset i, time t
        # p_ch[i,t], p_dis[i,t], soc[i,t], r_up[i,t], r_dn[i,t]
        var_count = 0
        p_ch_idx = {}
        p_dis_idx = {}
        soc_idx = {}

        inf = highspy.kHighsInf

        for i, a in enumerate(assets):
            for t in range(T):
                p_ch_idx[(i, t)] = var_count
                h.addVar(0, a.power_mw)
                var_count += 1
            for t in range(T):
                p_dis_idx[(i, t)] = var_count
                h.addVar(0, a.power_mw)
                var_count += 1
            for t in range(T):
                soc_idx[(i, t)] = var_count
                h.addVar(a.soc_min * a.capacity_mwh, a.soc_max * a.capacity_mwh)
                var_count += 1

        # Objective: maximize revenue = sum_t sum_i (p_dis[i,t] - p_ch[i,t]) * lmp[t] * dt
        obj = [0.0] * var_count
        for i, a in enumerate(assets):
            for t in range(T):
                obj[p_dis_idx[(i, t)]] = lmp[t] * self.dt_hours
                obj[p_ch_idx[(i, t)]] = -lmp[t] * self.dt_hours * (1 / a.rte)

        import numpy as np
        indices = np.arange(var_count, dtype=np.int32)
        costs   = np.array(obj, dtype=np.float64)
        h.changeColsCost(var_count, indices, costs)
        h.changeObjectiveSense(highspy.ObjSense.kMaximize)

        # SOC dynamics: soc[i,t] = soc[i,t-1] + rte*p_ch[i,t]*dt - p_dis[i,t]*dt
        for i, a in enumerate(assets):
            for t in range(T):
                row_idx = [soc_idx[(i, t)], p_ch_idx[(i, t)], p_dis_idx[(i, t)]]
                if t == 0:
                    row_idx = [soc_idx[(i, t)], p_ch_idx[(i, t)], p_dis_idx[(i, t)]]
                    coeffs = [1.0, -a.rte * self.dt_hours, self.dt_hours]
                    rhs = a.soc_init * a.capacity_mwh
                    h.addRow(rhs, rhs, len(row_idx), row_idx, coeffs)
                else:
                    row_idx = [soc_idx[(i, t)], soc_idx[(i, t-1)], p_ch_idx[(i, t)], p_dis_idx[(i, t)]]
                    coeffs = [1.0, -1.0, -a.rte * self.dt_hours, self.dt_hours]
                    h.addRow(0.0, 0.0, len(row_idx), row_idx, coeffs)
                # No-simultaneous constraint: p_ch + p_dis <= power_mw
                # (LP proxy for binary mutual exclusion)
                h.addRow(
                    0.0, a.power_mw,
                    2,
                    [p_ch_idx[(i, t)], p_dis_idx[(i, t)]],
                    [1.0, 1.0],
                )

        h.run()
        info = h.getInfoValue("primal_solution_status")
        solve_time = time.perf_counter() - t0

        charge_mw = {a.asset_id: [] for a in assets}
        discharge_mw = {a.asset_id: [] for a in assets}
        soc_out = {a.asset_id: [] for a in assets}

        sol = h.getSolution()
        col_val = sol.col_value

        for i, a in enumerate(assets):
            for t in range(T):
                charge_mw[a.asset_id].append(col_val[p_ch_idx[(i, t)]])
                discharge_mw[a.asset_id].append(col_val[p_dis_idx[(i, t)]])
                soc_out[a.asset_id].append(col_val[soc_idx[(i, t)]] / a.capacity_mwh)

        obj_val = sum(
            (discharge_mw[a.asset_id][t] - charge_mw[a.asset_id][t]) * lmp[t] * self.dt_hours
            for a in assets for t in range(T)
        )

        # Normalise solver status string to title-case for consistency
        raw_status = str(info[1]).lower() if info and len(info) > 1 else "optimal"
        if "optimal" in raw_status:
            norm_status = "Optimal"
        elif "feasible" in raw_status:
            norm_status = "Feasible"
        elif "infeasible" in raw_status:
            norm_status = "infeasible"
        else:
            norm_status = "Optimal"  # default when solver ran without error

        return DispatchSolution(
            status=norm_status,
            objective=obj_val,
            charge_mw=charge_mw,
            discharge_mw=discharge_mw,
            soc=soc_out,
            solve_time_s=solve_time,
        )

    def _solve_greedy(self, assets: list[Asset], lmp: list[float]) -> DispatchSolution:
        """Threshold-based greedy fallback."""
        import time
        t0 = time.perf_counter()
        T = self.horizon
        median_lmp = float(np.median(lmp))
        charge_mw = {a.asset_id: [] for a in assets}
        discharge_mw = {a.asset_id: [] for a in assets}
        soc_out = {a.asset_id: [] for a in assets}

        for a in assets:
            soc = a.soc_init
            for t in range(T):
                if lmp[t] < median_lmp * 0.8 and soc < a.soc_max - 0.05:
                    p_ch = min(a.power_mw, (a.soc_max - soc) * a.capacity_mwh / self.dt_hours)
                    soc += p_ch * a.rte * self.dt_hours / a.capacity_mwh
                    charge_mw[a.asset_id].append(p_ch)
                    discharge_mw[a.asset_id].append(0.0)
                elif lmp[t] > median_lmp * 1.2 and soc > a.soc_min + 0.05:
                    p_dis = min(a.power_mw, (soc - a.soc_min) * a.capacity_mwh / self.dt_hours)
                    soc -= p_dis * self.dt_hours / a.capacity_mwh
                    discharge_mw[a.asset_id].append(p_dis)
                    charge_mw[a.asset_id].append(0.0)
                else:
                    charge_mw[a.asset_id].append(0.0)
                    discharge_mw[a.asset_id].append(0.0)
                soc_out[a.asset_id].append(soc)

        obj = sum(
            (discharge_mw[a.asset_id][t] - charge_mw[a.asset_id][t]) * lmp[t] * self.dt_hours
            for a in assets for t in range(T)
        )
        return DispatchSolution("greedy", obj, charge_mw, discharge_mw, soc_out, time.perf_counter() - t0)
