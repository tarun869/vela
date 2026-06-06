"""Co-optimization of energy arbitrage and ancillary services using LP/MILP."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class CoOptSolution(NamedTuple):
    status: str
    total_revenue: float
    energy_revenue: float
    reg_up_revenue: float
    reg_down_revenue: float
    spin_revenue: float
    charge_mw: dict[str, list[float]]
    discharge_mw: dict[str, list[float]]
    reg_up_mw: dict[str, list[float]]
    reg_down_mw: dict[str, list[float]]
    spin_mw: dict[str, list[float]]
    soc: dict[str, list[float]]
    solve_time_s: float


@dataclass
class AssetSpec:
    """Battery storage asset specification for co-optimization."""
    asset_id: str
    capacity_mwh: float
    power_mw: float
    rte: float = 0.92
    soc_init: float = 0.5
    soc_min: float = 0.05
    soc_max: float = 0.95
    # Capability fractions for AS products (0-1)
    reg_up_capability: float = 1.0
    reg_down_capability: float = 1.0
    spin_capability: float = 1.0
    # Minimum reserved headroom (fraction of power_mw)
    min_soc_for_discharge: float = 0.1


@dataclass
class CoOptimizer:
    """
    Co-optimizer for simultaneous energy + ancillary services dispatch.

    Ancillary services require capacity reservation:
    - Regulation Up:  requires available discharge headroom
    - Regulation Down: requires available charge headroom
    - Spinning reserve: requires discharge headroom (must respond in 10 min)

    The key coupling constraint is that AS reservation consumes headroom
    that cannot be used for energy arbitrage in the same interval.

    Formulation: LP (continuous variables only)
        max  sum_t sum_i [
            p_dis[i,t] * lmp[t] * dt
            - p_ch[i,t] * lmp[t] * dt / rte
            + r_up[i,t] * ru_price[t] * dt
            + r_dn[i,t] * rd_price[t] * dt
            + r_sp[i,t] * sp_price[t] * dt
        ]

        s.t.
            SOC dynamics
            SOC bounds
            Power balance: p_ch + p_dis + r_up + r_sp <= power_mw (simplified)
            AS capability: r_up <= cap_up * power_mw
    """
    horizon: int = 24
    dt_hours: float = 1.0
    min_as_mw: float = 0.1  # Minimum MW to offer into AS market

    def solve(
        self,
        assets: list[AssetSpec],
        lmp: list[float],
        reg_up_price: list[float],
        reg_down_price: list[float],
        spin_price: list[float],
    ) -> CoOptSolution:
        import time
        t0 = time.perf_counter()
        try:
            import highspy
            return self._solve_highs(assets, lmp, reg_up_price, reg_down_price, spin_price, t0)
        except ImportError:
            logger.warning("highspy not available, using numpy LP fallback")
            return self._solve_numpy_lp(assets, lmp, reg_up_price, reg_down_price, spin_price, t0)

    def _solve_highs(
        self,
        assets: list[AssetSpec],
        lmp: list[float],
        reg_up_price: list[float],
        reg_down_price: list[float],
        spin_price: list[float],
        t0: float,
    ) -> CoOptSolution:
        import highspy
        import time

        T = self.horizon
        h = highspy.Highs()
        h.silent()

        var_count = 0
        p_ch_idx: dict[tuple[int, int], int] = {}
        p_dis_idx: dict[tuple[int, int], int] = {}
        soc_idx: dict[tuple[int, int], int] = {}
        r_up_idx: dict[tuple[int, int], int] = {}
        r_dn_idx: dict[tuple[int, int], int] = {}
        r_sp_idx: dict[tuple[int, int], int] = {}

        for i, a in enumerate(assets):
            for t in range(T):
                p_ch_idx[(i, t)] = var_count; h.addVar(0, a.power_mw); var_count += 1
            for t in range(T):
                p_dis_idx[(i, t)] = var_count; h.addVar(0, a.power_mw); var_count += 1
            for t in range(T):
                soc_idx[(i, t)] = var_count
                h.addVar(a.soc_min * a.capacity_mwh, a.soc_max * a.capacity_mwh)
                var_count += 1
            for t in range(T):
                r_up_idx[(i, t)] = var_count
                h.addVar(0, a.reg_up_capability * a.power_mw)
                var_count += 1
            for t in range(T):
                r_dn_idx[(i, t)] = var_count
                h.addVar(0, a.reg_down_capability * a.power_mw)
                var_count += 1
            for t in range(T):
                r_sp_idx[(i, t)] = var_count
                h.addVar(0, a.spin_capability * a.power_mw)
                var_count += 1

        # Objective
        obj = [0.0] * var_count
        for i, a in enumerate(assets):
            for t in range(T):
                obj[p_dis_idx[(i, t)]] = lmp[t] * self.dt_hours
                obj[p_ch_idx[(i, t)]] = -lmp[t] * self.dt_hours / a.rte
                obj[r_up_idx[(i, t)]] = reg_up_price[t] * self.dt_hours
                obj[r_dn_idx[(i, t)]] = reg_down_price[t] * self.dt_hours
                obj[r_sp_idx[(i, t)]] = spin_price[t] * self.dt_hours

        h.changeColsCostByRange(0, var_count - 1, obj)
        h.changeObjectiveSense(highspy.ObjSense.kMaximize)

        for i, a in enumerate(assets):
            for t in range(T):
                # SOC dynamics
                if t == 0:
                    row_idx = [soc_idx[(i, t)], p_ch_idx[(i, t)], p_dis_idx[(i, t)]]
                    coeffs = [1.0, -a.rte * self.dt_hours, self.dt_hours]
                    rhs = a.soc_init * a.capacity_mwh
                    h.addRow(rhs, rhs, len(row_idx), row_idx, coeffs)
                else:
                    row_idx = [soc_idx[(i, t)], soc_idx[(i, t-1)], p_ch_idx[(i, t)], p_dis_idx[(i, t)]]
                    coeffs = [1.0, -1.0, -a.rte * self.dt_hours, self.dt_hours]
                    h.addRow(0.0, 0.0, len(row_idx), row_idx, coeffs)

                # Power coupling: discharge + reg_up + spin <= power_mw
                row_dis = [p_dis_idx[(i, t)], r_up_idx[(i, t)], r_sp_idx[(i, t)]]
                h.addRow(0, a.power_mw, len(row_dis), row_dis, [1.0, 1.0, 1.0])

                # Charge coupling: charge + reg_down <= power_mw
                row_ch = [p_ch_idx[(i, t)], r_dn_idx[(i, t)]]
                h.addRow(0, a.power_mw, len(row_ch), row_ch, [1.0, 1.0])

                # SOC headroom for reg_up + spin (need SOC above minimum)
                # r_up + r_sp <= (soc - soc_min) * cap / dt
                row_soc_up = [r_up_idx[(i, t)], r_sp_idx[(i, t)], soc_idx[(i, t)]]
                h.addRow(
                    -highspy.kHighsInf,
                    -a.soc_min * a.capacity_mwh / self.dt_hours,
                    len(row_soc_up),
                    row_soc_up,
                    [1.0, 1.0, -1.0 / self.dt_hours],
                )

        h.run()
        sol = h.getSolution()
        cv = sol.col_value
        solve_time = time.perf_counter() - t0

        charge_mw, discharge_mw = {a.asset_id: [] for a in assets}, {a.asset_id: [] for a in assets}
        r_up_out, r_dn_out, r_sp_out = {a.asset_id: [] for a in assets}, {a.asset_id: [] for a in assets}, {a.asset_id: [] for a in assets}
        soc_out = {a.asset_id: [] for a in assets}

        for i, a in enumerate(assets):
            for t in range(T):
                charge_mw[a.asset_id].append(cv[p_ch_idx[(i, t)]])
                discharge_mw[a.asset_id].append(cv[p_dis_idx[(i, t)]])
                soc_out[a.asset_id].append(cv[soc_idx[(i, t)]] / a.capacity_mwh)
                r_up_out[a.asset_id].append(cv[r_up_idx[(i, t)]])
                r_dn_out[a.asset_id].append(cv[r_dn_idx[(i, t)]])
                r_sp_out[a.asset_id].append(cv[r_sp_idx[(i, t)]])

        energy_rev = sum(
            (discharge_mw[a.asset_id][t] - charge_mw[a.asset_id][t] / a.rte) * lmp[t] * self.dt_hours
            for a in assets for t in range(T)
        )
        ru_rev = sum(r_up_out[a.asset_id][t] * reg_up_price[t] * self.dt_hours for a in assets for t in range(T))
        rd_rev = sum(r_dn_out[a.asset_id][t] * reg_down_price[t] * self.dt_hours for a in assets for t in range(T))
        sp_rev = sum(r_sp_out[a.asset_id][t] * spin_price[t] * self.dt_hours for a in assets for t in range(T))

        return CoOptSolution(
            status="optimal",
            total_revenue=energy_rev + ru_rev + rd_rev + sp_rev,
            energy_revenue=energy_rev,
            reg_up_revenue=ru_rev,
            reg_down_revenue=rd_rev,
            spin_revenue=sp_rev,
            charge_mw=charge_mw,
            discharge_mw=discharge_mw,
            reg_up_mw=r_up_out,
            reg_down_mw=r_dn_out,
            spin_mw=r_sp_out,
            soc=soc_out,
            solve_time_s=solve_time,
        )

    def _solve_numpy_lp(
        self,
        assets: list[AssetSpec],
        lmp: list[float],
        reg_up_price: list[float],
        reg_down_price: list[float],
        spin_price: list[float],
        t0: float,
    ) -> CoOptSolution:
        """Greedy heuristic fallback when highspy unavailable."""
        import time
        T = self.horizon
        median_lmp = float(np.median(lmp))
        charge_mw = {a.asset_id: [0.0] * T for a in assets}
        discharge_mw = {a.asset_id: [0.0] * T for a in assets}
        r_up = {a.asset_id: [0.0] * T for a in assets}
        r_dn = {a.asset_id: [0.0] * T for a in assets}
        r_sp = {a.asset_id: [0.0] * T for a in assets}
        soc_out = {a.asset_id: [0.0] * T for a in assets}

        for a in assets:
            soc = a.soc_init
            for t in range(T):
                as_value = reg_up_price[t] + spin_price[t]
                if as_value > 5.0 and soc > a.soc_min + 0.1:
                    # Reserve capacity for AS
                    as_mw = min(a.power_mw * 0.3, (soc - a.soc_min) * a.capacity_mwh)
                    r_up[a.asset_id][t] = as_mw * 0.6
                    r_sp[a.asset_id][t] = as_mw * 0.4
                    remaining_mw = a.power_mw - as_mw
                    if lmp[t] > median_lmp * 1.2 and soc > a.soc_min + 0.05:
                        p_dis = min(remaining_mw, (soc - a.soc_min) * a.capacity_mwh)
                        discharge_mw[a.asset_id][t] = p_dis
                        soc -= p_dis * self.dt_hours / a.capacity_mwh
                elif lmp[t] < median_lmp * 0.8 and soc < a.soc_max - 0.05:
                    p_ch = min(a.power_mw, (a.soc_max - soc) * a.capacity_mwh)
                    charge_mw[a.asset_id][t] = p_ch
                    r_dn[a.asset_id][t] = min(a.power_mw - p_ch, a.power_mw * 0.2)
                    soc += p_ch * a.rte * self.dt_hours / a.capacity_mwh
                soc = float(np.clip(soc, a.soc_min, a.soc_max))
                soc_out[a.asset_id][t] = soc

        energy_rev = sum(
            (discharge_mw[a.asset_id][t] - charge_mw[a.asset_id][t]) * lmp[t] * self.dt_hours
            for a in assets for t in range(T)
        )
        ru_rev = sum(r_up[a.asset_id][t] * reg_up_price[t] * self.dt_hours for a in assets for t in range(T))
        rd_rev = sum(r_dn[a.asset_id][t] * reg_down_price[t] * self.dt_hours for a in assets for t in range(T))
        sp_rev = sum(r_sp[a.asset_id][t] * spin_price[t] * self.dt_hours for a in assets for t in range(T))

        return CoOptSolution(
            status="greedy",
            total_revenue=energy_rev + ru_rev + rd_rev + sp_rev,
            energy_revenue=energy_rev,
            reg_up_revenue=ru_rev,
            reg_down_revenue=rd_rev,
            spin_revenue=sp_rev,
            charge_mw=charge_mw,
            discharge_mw=discharge_mw,
            reg_up_mw=r_up,
            reg_down_mw=r_dn,
            spin_mw=r_sp,
            soc=soc_out,
            solve_time_s=time.perf_counter() - t0,
        )
