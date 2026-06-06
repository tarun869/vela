"""Dynamic programming for single-asset battery dispatch (exact solution)."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import NamedTuple


class DPSolution(NamedTuple):
    status: str
    total_revenue: float
    charge_mw: list[float]
    discharge_mw: list[float]
    soc_trajectory: list[float]
    value_function: np.ndarray    # V[t, soc_bin] — value at each state


@dataclass
class DPDispatchOptimizer:
    """
    Exact dynamic programming solution for single-asset battery dispatch.

    Uses backward induction over a discretized SOC state space.

    State: (t, soc_bin)
    Action: (charge_mw, discharge_mw)
    Reward: (discharge - charge) * lmp[t] * dt

    Complexity: O(T * n_soc_bins * n_actions^2)

    Advantages vs MILP:
    - Guarantees global optimum for single asset
    - Computes full value function (useful for policy analysis)
    - No solver dependency

    Limitation: curse of dimensionality for multiple assets
    """
    capacity_mwh: float = 10.0
    power_mw: float = 5.0
    rte: float = 0.92
    soc_min: float = 0.05
    soc_max: float = 0.95
    dt_hours: float = 1.0
    n_soc_bins: int = 100
    n_action_steps: int = 20    # Discretization of charge/discharge levels

    def _soc_bins(self) -> np.ndarray:
        return np.linspace(self.soc_min, self.soc_max, self.n_soc_bins)

    def _soc_to_bin(self, soc: float) -> int:
        bins = self._soc_bins()
        return int(np.argmin(np.abs(bins - soc)))

    def solve(
        self,
        lmp: list[float],
        initial_soc: float = 0.5,
        terminal_soc_weight: float = 0.0,
    ) -> DPSolution:
        """
        Solve battery dispatch via backward induction.

        Parameters
        ----------
        lmp : list[float]
            Hourly LMP prices ($/MWh)
        initial_soc : float
            Starting state of charge (fraction)
        terminal_soc_weight : float
            Value per MWh of SOC at end of horizon (e.g., cost of energy to refill)
        """
        T = len(lmp)
        bins = self._soc_bins()
        N = len(bins)

        # Action space: discretized charge/discharge levels
        charge_levels = np.linspace(0, self.power_mw, self.n_action_steps + 1)
        discharge_levels = np.linspace(0, self.power_mw, self.n_action_steps + 1)

        # Value function V[t, soc_bin]
        V = np.full((T + 1, N), -np.inf)
        policy_charge = np.zeros((T, N))
        policy_discharge = np.zeros((T, N))

        # Terminal value: value of remaining energy
        for n, soc in enumerate(bins):
            energy_remaining = soc * self.capacity_mwh
            V[T, n] = terminal_soc_weight * energy_remaining

        # Backward induction
        for t in range(T - 1, -1, -1):
            price = lmp[t]
            for n, soc in enumerate(bins):
                best_val = -np.inf
                best_ch = 0.0
                best_dis = 0.0

                for ch in charge_levels:
                    # Check charge feasibility
                    new_soc_from_charge = soc + ch * self.rte * self.dt_hours / self.capacity_mwh
                    if new_soc_from_charge > self.soc_max + 1e-6:
                        continue
                    for dis in discharge_levels:
                        if dis > 0 and ch > 0:
                            continue  # No simultaneous charge+discharge
                        new_soc = new_soc_from_charge - dis * self.dt_hours / self.capacity_mwh
                        if new_soc < self.soc_min - 1e-6 or new_soc > self.soc_max + 1e-6:
                            continue
                        if dis > 0 and soc < self.soc_min + 1e-6:
                            continue

                        new_soc_clipped = float(np.clip(new_soc, self.soc_min, self.soc_max))
                        next_n = int(np.argmin(np.abs(bins - new_soc_clipped)))

                        immediate_reward = (dis - ch / self.rte) * price * self.dt_hours
                        future_value = V[t + 1, next_n]
                        total = immediate_reward + future_value

                        if total > best_val:
                            best_val = total
                            best_ch = ch
                            best_dis = dis

                V[t, n] = best_val
                policy_charge[t, n] = best_ch
                policy_discharge[t, n] = best_dis

        # Extract optimal policy by forward simulation
        charge_traj = []
        discharge_traj = []
        soc_traj = []
        soc = float(np.clip(initial_soc, self.soc_min, self.soc_max))

        for t in range(T):
            n = self._soc_to_bin(soc)
            ch = policy_charge[t, n]
            dis = policy_discharge[t, n]
            charge_traj.append(float(ch))
            discharge_traj.append(float(dis))
            soc_traj.append(soc)
            soc = float(np.clip(
                soc + ch * self.rte * self.dt_hours / self.capacity_mwh
                - dis * self.dt_hours / self.capacity_mwh,
                self.soc_min, self.soc_max
            ))

        total_rev = sum(
            (discharge_traj[t] - charge_traj[t] / self.rte) * lmp[t] * self.dt_hours
            for t in range(T)
        )

        return DPSolution(
            status="optimal",
            total_revenue=total_rev,
            charge_mw=charge_traj,
            discharge_mw=discharge_traj,
            soc_trajectory=soc_traj,
            value_function=V,
        )

    def marginal_value_of_energy(
        self,
        lmp: list[float],
        initial_soc: float = 0.5,
    ) -> list[float]:
        """
        Compute the marginal value of stored energy (SOC) over time.

        This is the shadow price / dual variable of the SOC constraint,
        which can be used to price stored energy for dispatch decisions.
        """
        sol = self.solve(lmp, initial_soc)
        bins = self._soc_bins()
        V = sol.value_function

        # dV/d(soc) at the trajectory SOC at each timestep
        marginal_values = []
        for t in range(len(lmp)):
            n = self._soc_to_bin(sol.soc_trajectory[t])
            if n < len(bins) - 1:
                dV = (V[t, n+1] - V[t, n]) / (bins[n+1] - bins[n]) if bins[n+1] > bins[n] else 0.0
                marginal_values.append(float(dV * self.capacity_mwh))
            else:
                marginal_values.append(0.0)
        return marginal_values
