"""
DC Power Flow — simplified linear power flow for distribution and transmission planning.

Solves the DC power flow equations:
    P = B * theta

where B is the susceptance matrix and theta is the vector of voltage angles.
Includes branch flow calculation and overload detection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class Bus:
    bus_id: int
    bus_type: str       # "slack", "pv", "pq"
    p_gen_mw: float = 0.0
    p_load_mw: float = 0.0
    v_pu: float = 1.0
    angle_rad: float = 0.0


@dataclass
class Branch:
    from_bus: int
    to_bus: int
    reactance_pu: float    # Per-unit reactance on system base
    susceptance_pu: float = 0.0  # Computed from reactance
    rating_mw: float = 100.0    # Thermal rating (MVA)

    def __post_init__(self) -> None:
        if self.reactance_pu <= 0:
            raise ValueError("Reactance must be positive")
        self.susceptance_pu = 1.0 / self.reactance_pu


@dataclass
class PowerFlowResult:
    converged: bool
    bus_angles_rad: Dict[int, float]
    branch_flows_mw: Dict[Tuple[int, int], float]
    overloaded_branches: List[Tuple[int, int]]
    total_generation_mw: float
    total_load_mw: float
    losses_mw: float  # DC approximation: always 0; placeholder for AC extension


class DCPowerFlow:
    """
    DC power flow solver using sparse B-matrix and numpy linear algebra.

    Assumptions (standard DC approximation):
      - Flat voltage profile (V = 1.0 pu everywhere)
      - Small angle differences (sin(θ) ≈ θ)
      - Resistances negligible (X >> R)
    """

    def __init__(self, buses: List[Bus], branches: List[Branch], s_base_mva: float = 100.0) -> None:
        self.buses = {b.bus_id: b for b in buses}
        self.branches = branches
        self.s_base = s_base_mva
        self._slack_bus = next(b.bus_id for b in buses if b.bus_type == "slack")
        self._bus_ids = sorted(self.buses.keys())
        self._n = len(self._bus_ids)
        self._idx = {bid: i for i, bid in enumerate(self._bus_ids)}

    def _build_b_matrix(self) -> np.ndarray:
        """Build the nodal susceptance matrix B (n x n)."""
        B = np.zeros((self._n, self._n))
        for br in self.branches:
            i = self._idx[br.from_bus]
            j = self._idx[br.to_bus]
            b = br.susceptance_pu
            B[i, i] += b
            B[j, j] += b
            B[i, j] -= b
            B[j, i] -= b
        return B

    def _net_injections(self) -> np.ndarray:
        """Build vector of net power injections (generation - load) in pu."""
        P = np.zeros(self._n)
        for bus_id, bus in self.buses.items():
            i = self._idx[bus_id]
            P[i] = (bus.p_gen_mw - bus.p_load_mw) / self.s_base
        return P

    def solve(self) -> PowerFlowResult:
        """
        Solve DC power flow and return result.
        """
        B = self._build_b_matrix()
        P = self._net_injections()

        slack_idx = self._idx[self._slack_bus]

        # Remove slack bus row/col for reduced system
        mask = [i for i in range(self._n) if i != slack_idx]
        B_red = B[np.ix_(mask, mask)]
        P_red = P[mask]

        try:
            theta_red = np.linalg.solve(B_red, P_red)
        except np.linalg.LinAlgError:
            return PowerFlowResult(
                converged=False,
                bus_angles_rad={bid: 0.0 for bid in self._bus_ids},
                branch_flows_mw={},
                overloaded_branches=[],
                total_generation_mw=0.0,
                total_load_mw=0.0,
                losses_mw=0.0,
            )

        # Reconstruct full theta
        theta = np.zeros(self._n)
        for ii, idx in enumerate(mask):
            theta[idx] = theta_red[ii]

        bus_angles = {self._bus_ids[i]: theta[i] for i in range(self._n)}
        for bus in self.buses.values():
            bus.angle_rad = bus_angles[bus.bus_id]

        # Compute branch flows
        branch_flows: Dict[Tuple[int, int], float] = {}
        overloaded: List[Tuple[int, int]] = []

        for br in self.branches:
            i = self._idx[br.from_bus]
            j = self._idx[br.to_bus]
            flow_pu = br.susceptance_pu * (theta[i] - theta[j])
            flow_mw = flow_pu * self.s_base
            branch_flows[(br.from_bus, br.to_bus)] = flow_mw
            if abs(flow_mw) > br.rating_mw:
                overloaded.append((br.from_bus, br.to_bus))

        total_gen = sum(b.p_gen_mw for b in self.buses.values())
        total_load = sum(b.p_load_mw for b in self.buses.values())

        return PowerFlowResult(
            converged=True,
            bus_angles_rad=bus_angles,
            branch_flows_mw=branch_flows,
            overloaded_branches=overloaded,
            total_generation_mw=total_gen,
            total_load_mw=total_load,
            losses_mw=0.0,
        )

    def ptdf(self, branch_idx: int) -> np.ndarray:
        """
        Compute Power Transfer Distribution Factor (PTDF) row for a branch.

        PTDF[i] = sensitivity of branch flow to 1 MW injection at bus i.
        """
        B = self._build_b_matrix()
        slack_idx = self._idx[self._slack_bus]
        mask = [i for i in range(self._n) if i != slack_idx]
        B_red = B[np.ix_(mask, mask)]
        B_red_inv = np.linalg.pinv(B_red)

        br = self.branches[branch_idx]
        i = self._idx[br.from_bus]
        j = self._idx[br.to_bus]

        ptdf = np.zeros(self._n)
        for k in range(self._n):
            if k == slack_idx:
                continue
            k_red = mask.index(k)
            ptdf_ij = br.susceptance_pu * (
                B_red_inv[mask.index(i) if i != slack_idx else 0, k_red]
                - B_red_inv[mask.index(j) if j != slack_idx else 0, k_red]
            )
            ptdf[k] = ptdf_ij / self.s_base

        return ptdf

    def update_generation(self, gen_dispatch: Dict[int, float]) -> None:
        """Update generation dispatch before re-solving."""
        for bus_id, p_mw in gen_dispatch.items():
            if bus_id in self.buses:
                self.buses[bus_id].p_gen_mw = p_mw
