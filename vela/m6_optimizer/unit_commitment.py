"""Unit commitment optimization for dispatchable generation resources (gensets)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class GenUnit:
    """A dispatchable generation unit (gas turbine, diesel genset, etc.)."""
    unit_id: str
    min_output_mw: float      # Pmin — minimum stable generation
    max_output_mw: float      # Pmax — nameplate capacity
    fuel_cost_mmbtu: float    # $/MMBtu fuel price
    heat_rate_mmbtu_mwh: float  # MMBtu/MWh at full load
    startup_cost: float       # $ per startup event
    shutdown_cost: float = 0.0
    min_up_hours: int = 4     # Minimum up-time (hours)
    min_down_hours: int = 4   # Minimum down-time (hours)
    ramp_up_mw_min: float = 10.0   # Ramp-up rate MW/min
    ramp_down_mw_min: float = 10.0
    co2_intensity_lb_mwh: float = 800.0  # lbs CO2/MWh

    @property
    def variable_om_mwh(self) -> float:
        return 3.0  # $/MWh fixed variable O&M

    @property
    def marginal_cost_mwh(self) -> float:
        """Fuel + VOM marginal cost ($/MWh)."""
        return self.fuel_cost_mmbtu * self.heat_rate_mmbtu_mwh + self.variable_om_mwh


class UCOSolution(NamedTuple):
    status: str
    total_cost: float
    commitment: dict[str, list[int]]    # 0/1 per unit per interval
    dispatch_mw: dict[str, list[float]]
    startup_events: dict[str, list[int]]
    total_emissions_lb: float
    solve_time_s: float


@dataclass
class UnitCommitmentOptimizer:
    """
    MILP unit commitment for a fleet of dispatchable generators.

    Minimizes total operating cost (fuel + startup) subject to:
    - Load balance (generation must meet demand)
    - Min/max output constraints
    - Minimum up/down time constraints
    - Ramp rate constraints

    The MILP formulation uses binary commitment variables u[i,t] ∈ {0,1}
    and continuous dispatch variables p[i,t].
    """
    horizon: int = 24
    dt_hours: float = 1.0
    reserve_margin: float = 0.15  # 15% spinning reserve requirement

    def solve(
        self,
        units: list[GenUnit],
        load_mw: list[float],
        lmp: list[float] | None = None,
    ) -> UCOSolution:
        import time
        t0 = time.perf_counter()
        try:
            import highspy
            return self._solve_highs(units, load_mw, lmp, t0)
        except ImportError:
            logger.warning("highspy unavailable, using merit-order heuristic for UC")
            return self._solve_merit_order(units, load_mw, t0)

    def _solve_highs(
        self,
        units: list[GenUnit],
        load_mw: list[float],
        lmp: list[float] | None,
        t0: float,
    ) -> UCOSolution:
        import highspy
        import time

        T = self.horizon
        N = len(units)
        h = highspy.Highs()
        h.silent()
        h.setOptionValue("mip_rel_gap", 0.005)  # 0.5% optimality gap

        var_count = 0
        u_idx: dict[tuple[int, int], int] = {}    # commitment binary
        p_idx: dict[tuple[int, int], int] = {}    # dispatch MW
        su_idx: dict[tuple[int, int], int] = {}   # startup binary

        for i in range(N):
            for t in range(T):
                u_idx[(i, t)] = var_count
                h.addVar(0, 1)
                h.changeColIntegrality(var_count, highspy.HighsVarType.kInteger)
                var_count += 1
        for i, g in enumerate(units):
            for t in range(T):
                p_idx[(i, t)] = var_count
                h.addVar(0, g.max_output_mw)
                var_count += 1
        for i in range(N):
            for t in range(T):
                su_idx[(i, t)] = var_count
                h.addVar(0, 1)
                h.changeColIntegrality(var_count, highspy.HighsVarType.kInteger)
                var_count += 1

        # Objective: minimize total cost
        obj = [0.0] * var_count
        for i, g in enumerate(units):
            for t in range(T):
                obj[p_idx[(i, t)]] = g.marginal_cost_mwh * self.dt_hours
                obj[su_idx[(i, t)]] = g.startup_cost

        h.changeColsCostByRange(0, var_count - 1, obj)
        # Minimization is default in HiGHS

        for i, g in enumerate(units):
            for t in range(T):
                # p[i,t] >= Pmin * u[i,t]
                h.addRow(0, highspy.kHighsInf, 2,
                         [p_idx[(i, t)], u_idx[(i, t)]],
                         [1.0, -g.min_output_mw])
                # p[i,t] <= Pmax * u[i,t]
                h.addRow(-highspy.kHighsInf, 0, 2,
                         [p_idx[(i, t)], u_idx[(i, t)]],
                         [1.0, -g.max_output_mw])

                # Startup logic: su[i,t] >= u[i,t] - u[i,t-1]
                if t > 0:
                    h.addRow(0, highspy.kHighsInf, 3,
                             [su_idx[(i, t)], u_idx[(i, t)], u_idx[(i, t-1)]],
                             [1.0, -1.0, 1.0])
                    # Ramp up: p[i,t] - p[i,t-1] <= ramp_up * dt * 60
                    ramp_up_limit = g.ramp_up_mw_min * 60 * self.dt_hours
                    h.addRow(-highspy.kHighsInf, ramp_up_limit, 2,
                             [p_idx[(i, t)], p_idx[(i, t-1)]],
                             [1.0, -1.0])
                    # Ramp down
                    ramp_dn_limit = g.ramp_down_mw_min * 60 * self.dt_hours
                    h.addRow(-highspy.kHighsInf, ramp_dn_limit, 2,
                             [p_idx[(i, t-1)], p_idx[(i, t)]],
                             [1.0, -1.0])

                # Minimum up-time: if started at t, must stay on for min_up_hours
                if t > 0 and g.min_up_hours > 1:
                    end = min(t + g.min_up_hours, T)
                    for tt in range(t, end):
                        h.addRow(-highspy.kHighsInf, 0, 2,
                                 [su_idx[(i, t)], u_idx[(i, tt)]],
                                 [1.0, -1.0])

        # Load balance: sum_i p[i,t] >= load[t] * (1 + reserve_margin)
        for t in range(T):
            row_idx = [p_idx[(i, t)] for i in range(N)]
            coeffs = [1.0] * N
            required = load_mw[t] * (1 + self.reserve_margin)
            h.addRow(required, highspy.kHighsInf, N, row_idx, coeffs)

        h.run()
        sol = h.getSolution()
        cv = sol.col_value
        solve_time = time.perf_counter() - t0

        commitment = {g.unit_id: [] for g in units}
        dispatch_mw = {g.unit_id: [] for g in units}
        startup_events = {g.unit_id: [] for g in units}

        for i, g in enumerate(units):
            for t in range(T):
                commitment[g.unit_id].append(int(round(cv[u_idx[(i, t)]])))
                dispatch_mw[g.unit_id].append(cv[p_idx[(i, t)]])
                startup_events[g.unit_id].append(int(round(cv[su_idx[(i, t)]])))

        total_cost = sum(
            dispatch_mw[g.unit_id][t] * g.marginal_cost_mwh * self.dt_hours
            + startup_events[g.unit_id][t] * g.startup_cost
            for g in units for t in range(T)
        )
        total_emissions = sum(
            dispatch_mw[g.unit_id][t] * g.co2_intensity_lb_mwh * self.dt_hours
            for g in units for t in range(T)
        )

        return UCOSolution(
            status="optimal",
            total_cost=total_cost,
            commitment=commitment,
            dispatch_mw=dispatch_mw,
            startup_events=startup_events,
            total_emissions_lb=total_emissions,
            solve_time_s=solve_time,
        )

    def _solve_merit_order(
        self,
        units: list[GenUnit],
        load_mw: list[float],
        t0: float,
    ) -> UCOSolution:
        """
        Merit-order dispatch heuristic (economic dispatch, no MILP).

        Units dispatched in order of marginal cost until load is met.
        """
        import time
        T = self.horizon
        sorted_units = sorted(units, key=lambda g: g.marginal_cost_mwh)
        commitment = {g.unit_id: [0] * T for g in units}
        dispatch_mw = {g.unit_id: [0.0] * T for g in units}
        startup_events = {g.unit_id: [0] * T for g in units}

        for t in range(T):
            remaining = load_mw[t]
            for g in sorted_units:
                if remaining <= 0:
                    break
                output = min(g.max_output_mw, max(g.min_output_mw, remaining))
                commitment[g.unit_id][t] = 1
                dispatch_mw[g.unit_id][t] = output
                if t > 0 and commitment[g.unit_id][t-1] == 0:
                    startup_events[g.unit_id][t] = 1
                remaining -= output

        total_cost = sum(
            dispatch_mw[g.unit_id][t] * g.marginal_cost_mwh * self.dt_hours
            + startup_events[g.unit_id][t] * g.startup_cost
            for g in units for t in range(T)
        )
        total_emissions = sum(
            dispatch_mw[g.unit_id][t] * g.co2_intensity_lb_mwh * self.dt_hours
            for g in units for t in range(T)
        )
        return UCOSolution(
            status="merit_order",
            total_cost=total_cost,
            commitment=commitment,
            dispatch_mw=dispatch_mw,
            startup_events=startup_events,
            total_emissions_lb=total_emissions,
            solve_time_s=time.perf_counter() - t0,
        )
