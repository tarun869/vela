"""
Carbon-aware dispatch optimization.

Modifies VPP dispatch to minimize carbon emissions while satisfying
revenue and reliability constraints, using time-varying emission factors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import linprog


@dataclass
class CarbonDispatchParams:
    n_periods: int
    dispatch_max_kw: float
    dispatch_min_kw: float
    ramp_rate_kw_h: float
    energy_capacity_kwh: float
    initial_soc_kwh: float
    dt_h: float = 1.0
    carbon_price_per_tonne: float = 50.0    # $/tonne CO2


@dataclass
class CarbonDispatchResult:
    dispatch_kw: List[float]
    soc_kwh: List[float]
    revenue_usd: float
    carbon_cost_usd: float
    net_revenue_usd: float
    total_co2_kg: float
    carbon_intensity_kg_mwh: float


class CarbonAwareDispatchOptimizer:
    """
    LP-based dispatch optimizer that co-optimizes revenue and carbon cost.

    Objective: max (revenue - lambda * carbon_cost)
    where lambda is the carbon price weighting factor.
    """

    def __init__(self, params: CarbonDispatchParams) -> None:
        self.params = params

    def optimize(
        self,
        prices_usd_kwh: List[float],
        emission_factors_kg_kwh: List[float],
        carbon_weight: float = 1.0,
    ) -> CarbonDispatchResult:
        """
        Optimize dispatch considering both energy revenue and carbon cost.

        Args:
            prices_usd_kwh: Hourly energy prices ($/kWh).
            emission_factors_kg_kwh: Hourly marginal emission rates (kg CO2/kWh).
            carbon_weight: Weight on carbon cost vs. revenue (0=pure revenue, 1=balanced).

        Returns:
            CarbonDispatchResult with optimal dispatch schedule.
        """
        p = self.params
        T = p.n_periods
        dt = p.dt_h

        prices = np.array(prices_usd_kwh[:T])
        efs = np.array(emission_factors_kg_kwh[:T])  # kg CO2/kWh

        # Carbon cost in $/kWh
        carbon_cost_per_kwh = efs * p.carbon_price_per_tonne / 1000.0  # kg -> tonne

        # Net value = price - carbon_weight * carbon_cost
        net_value = prices - carbon_weight * carbon_cost_per_kwh

        # Variables: dispatch[0..T-1], soc[0..T] (T+1 SOC variables)
        n_vars = T + T + 1  # dispatch + soc
        dispatch_idx = slice(0, T)
        soc_idx = slice(T, 2*T + 1)

        # Objective: maximize net_value @ dispatch => minimize -net_value @ dispatch
        c = np.zeros(n_vars)
        c[dispatch_idx] = -net_value * dt  # $/step

        # Inequality constraints
        A_ub_list = []
        b_ub_list = []

        # SOC dynamics: soc[t+1] = soc[t] - dispatch[t] * dt
        # => soc[t+1] - soc[t] + dispatch[t]*dt = 0
        # => soc[t+1] - soc[t] + dispatch[t]*dt <= 0 AND >= 0
        A_eq = np.zeros((T, n_vars))
        b_eq = np.zeros(T)
        for t in range(T):
            A_eq[t, T + t + 1] = 1.0   # soc[t+1]
            A_eq[t, T + t] = -1.0       # -soc[t]
            A_eq[t, t] = dt              # + dispatch[t]*dt
            # For charging: dispatch > 0 means discharging (positive = export)

        # Ramp constraints: |dispatch[t] - dispatch[t-1]| <= ramp_rate
        for t in range(1, T):
            row_up = np.zeros(n_vars)
            row_up[t] = 1.0
            row_up[t-1] = -1.0
            A_ub_list.append(row_up)
            b_ub_list.append(p.ramp_rate_kw_h * dt)

            row_dn = np.zeros(n_vars)
            row_dn[t] = -1.0
            row_dn[t-1] = 1.0
            A_ub_list.append(row_dn)
            b_ub_list.append(p.ramp_rate_kw_h * dt)

        A_ub = np.array(A_ub_list) if A_ub_list else np.zeros((0, n_vars))
        b_ub = np.array(b_ub_list) if b_ub_list else np.zeros(0)

        # Variable bounds
        bounds = (
            [(p.dispatch_min_kw, p.dispatch_max_kw)] * T +  # dispatch
            [(0.0, p.energy_capacity_kwh)] * (T + 1)         # soc
        )

        # Initial/final SOC constraints via A_eq augmentation
        A_eq_full = np.vstack([
            A_eq,
            np.eye(1, n_vars, T),          # soc[0] = initial_soc
        ])
        b_eq_full = np.concatenate([b_eq, [p.initial_soc_kwh]])

        result = linprog(
            c, A_ub=A_ub if len(A_ub) > 0 else None,
            b_ub=b_ub if len(b_ub) > 0 else None,
            A_eq=A_eq_full, b_eq=b_eq_full,
            bounds=bounds, method="highs"
        )

        if result.success:
            dispatch = result.x[:T].tolist()
            soc = result.x[T:2*T+1].tolist()
        else:
            dispatch = [0.0] * T
            soc = [p.initial_soc_kwh] * (T + 1)

        revenue = float(sum(d * p * dt for d, p in zip(dispatch, prices)))
        carbon_kg = float(sum(d * ef * dt for d, ef in zip(dispatch, efs)))
        carbon_cost = carbon_kg / 1000.0 * p.carbon_price_per_tonne

        total_energy_kwh = sum(abs(d) * dt for d in dispatch)
        carbon_intensity = carbon_kg / (total_energy_kwh / 1000.0) if total_energy_kwh > 0 else 0.0

        return CarbonDispatchResult(
            dispatch_kw=dispatch,
            soc_kwh=soc,
            revenue_usd=revenue,
            carbon_cost_usd=carbon_cost,
            net_revenue_usd=revenue - carbon_cost,
            total_co2_kg=carbon_kg,
            carbon_intensity_kg_mwh=carbon_intensity,
        )

    def clean_shift_opportunity(
        self,
        prices: List[float],
        emission_factors: List[float],
        threshold_pct: float = 0.20,
    ) -> List[Tuple[int, int, float]]:
        """
        Identify load shifting opportunities: move consumption from high-carbon
        to low-carbon periods.

        Returns:
            List of (from_period, to_period, savings_kg) tuples.
        """
        efs = np.array(emission_factors)
        ef_median = float(np.median(efs))
        opportunities: List[Tuple[int, int, float]] = []

        for from_t in range(len(efs)):
            if efs[from_t] > ef_median * (1 + threshold_pct):
                # Find best shift-to period
                to_t = int(np.argmin(efs))
                savings_kg = (efs[from_t] - efs[to_t]) * self.params.dispatch_max_kw * self.params.dt_h
                if savings_kg > 0:
                    opportunities.append((from_t, to_t, float(savings_kg)))

        return sorted(opportunities, key=lambda x: x[2], reverse=True)
