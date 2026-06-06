"""LP dual variable (shadow price) analysis for dispatch optimization."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import NamedTuple


class DualAnalysisResult(NamedTuple):
    soc_shadow_prices: list[float]       # $/MWh — value of stored energy over time
    power_shadow_prices: list[float]     # $/MW — value of additional power capacity
    energy_price_spread: list[float]     # Implied buy/sell spread
    optimal_charge_windows: list[int]    # Hours where charging adds most value
    optimal_discharge_windows: list[int] # Hours where discharging adds most value
    incremental_revenue_mwh: float       # Revenue per additional MWh of capacity
    incremental_revenue_mw: float        # Revenue per additional MW of power


@dataclass
class DualVariableExtractor:
    """
    Extracts and interprets LP dual variables from solved dispatch problems.

    Dual variables provide:
    - Shadow prices of constraints (value of relaxing each constraint)
    - Marginal value of energy storage capacity
    - Marginal value of power capacity
    - Economic interpretation of binding constraints

    For a battery storage LP:
    - SOC upper bound dual: cost of not charging more
    - SOC lower bound dual: cost of not discharging more
    - Power bound dual: value of additional MW rating
    """
    capacity_mwh: float = 10.0
    power_mw: float = 5.0
    rte: float = 0.92
    dt_hours: float = 1.0

    def extract_from_highs(
        self,
        h,  # highspy.Highs instance after solve
        soc_constraint_rows: list[int],
        power_constraint_rows: list[int],
    ) -> DualAnalysisResult:
        """
        Extract dual variables from a solved HiGHS LP.

        Parameters
        ----------
        h : highspy.Highs
            Solved LP instance
        soc_constraint_rows : list[int]
            Row indices of SOC dynamics constraints
        power_constraint_rows : list[int]
            Row indices of power limit constraints
        """
        sol = h.getSolution()
        row_duals = sol.row_dual

        soc_duals = [float(row_duals[r]) for r in soc_constraint_rows]
        power_duals = [float(row_duals[r]) for r in power_constraint_rows]

        return self._build_result(soc_duals, power_duals)

    def compute_analytically(
        self,
        lmp: list[float],
        charge_mw: list[float],
        discharge_mw: list[float],
        soc: list[float],
    ) -> DualAnalysisResult:
        """
        Approximate dual variables analytically from the primal solution.

        For binding constraints at the optimum, the dual variable equals
        the marginal improvement in objective from relaxing that constraint.

        Uses finite-difference approximation.
        """
        T = len(lmp)
        soc_arr = np.array(soc)
        lmp_arr = np.array(lmp)

        # SOC shadow prices: at times when SOC hits bounds, compute implicit price
        soc_shadow = np.zeros(T)
        for t in range(T):
            if abs(soc_arr[t] - 0.95) < 0.02:  # Near SOC max (charging limited)
                # Shadow price = marginal value of being able to charge more
                soc_shadow[t] = -lmp_arr[t] / self.rte  # Cost of charging
            elif abs(soc_arr[t] - 0.05) < 0.02:  # Near SOC min (discharging limited)
                soc_shadow[t] = lmp_arr[t]  # Value of being able to discharge

        # Power shadow prices: at times when power hits limits
        power_shadow = np.zeros(T)
        ch_arr = np.array(charge_mw)
        dis_arr = np.array(discharge_mw)
        for t in range(T):
            if abs(ch_arr[t] - self.power_mw) < 0.05 or abs(dis_arr[t] - self.power_mw) < 0.05:
                power_shadow[t] = abs(lmp_arr[t] - np.mean(lmp_arr))

        return self._build_result(soc_shadow.tolist(), power_shadow.tolist())

    def _build_result(
        self,
        soc_duals: list[float],
        power_duals: list[float],
    ) -> DualAnalysisResult:
        T = len(soc_duals)
        soc_arr = np.array(soc_duals)
        pwr_arr = np.array(power_duals)

        # Implied energy spread: difference between discharge and charge shadow prices
        spread = np.abs(soc_arr)

        # Optimal windows: where shadow prices are highest
        optimal_charge = sorted(range(T), key=lambda t: -max(0, -soc_arr[t]))[:6]
        optimal_discharge = sorted(range(T), key=lambda t: -max(0, soc_arr[t]))[:6]

        # Incremental revenue estimates
        incr_mwh = float(np.mean(np.abs(soc_arr)) * self.dt_hours) if T > 0 else 0.0
        incr_mw = float(np.mean(np.abs(pwr_arr)) * self.dt_hours) if T > 0 else 0.0

        return DualAnalysisResult(
            soc_shadow_prices=soc_arr.tolist(),
            power_shadow_prices=pwr_arr.tolist(),
            energy_price_spread=spread.tolist(),
            optimal_charge_windows=sorted(optimal_charge),
            optimal_discharge_windows=sorted(optimal_discharge),
            incremental_revenue_mwh=incr_mwh,
            incremental_revenue_mw=incr_mw,
        )

    def price_duration_curve(
        self,
        lmp: list[float],
        charge_mw: list[float],
        discharge_mw: list[float],
    ) -> dict[str, list[float]]:
        """
        Compute price-duration curves showing when the asset was active.

        Returns sorted LMP with corresponding dispatch activity.
        """
        T = len(lmp)
        combined = sorted(
            [(lmp[t], charge_mw[t], discharge_mw[t]) for t in range(T)],
            key=lambda x: -x[0]  # Sort by descending LMP
        )
        return {
            "lmp_sorted": [x[0] for x in combined],
            "charge_at_lmp": [x[1] for x in combined],
            "discharge_at_lmp": [x[2] for x in combined],
            "net_at_lmp": [x[2] - x[1] for x in combined],
        }
