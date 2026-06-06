"""
Reactive power / voltage support for grid-connected inverter resources.

Implements volt-VAR droop control, Q injection/absorption, and
PQ capability curve enforcement per IEEE 1547-2018.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class VoltVARParams:
    """Inverter volt-VAR control parameters (IEEE 1547 Category B defaults)."""
    resource_id: str
    s_rated_kva: float          # Apparent power rating (kVA)
    v_deadband_pu: Tuple[float, float] = (0.95, 1.05)  # (v_low, v_high) in pu
    v_range_pu: Tuple[float, float] = (0.88, 1.10)     # Full VAR output range
    q_max_pu: float = 0.44      # Max reactive power as fraction of S_rated
    pf_min: float = 0.85        # Minimum power factor (IEEE 1547)
    response_time_s: float = 10.0  # Time to full response
    volt_watt_enabled: bool = True  # Enable volt-watt (P curtailment at high V)


@dataclass
class VoltageState:
    v_pu: float = 1.0            # Terminal voltage (per unit)
    p_kw: float = 0.0            # Active power output (kW)
    q_kvar: float = 0.0          # Reactive power output (kVAR), + = capacitive
    s_kva: float = 0.0           # Apparent power (kVA)
    pf: float = 1.0              # Power factor
    mode: str = "normal"         # "normal", "volt_var", "volt_watt", "limited"


class VoltVARController:
    """
    Volt-VAR droop controller for grid-following inverter.

    Reactive power setpoint = -k * (V - V_ref) when outside dead band.
    """

    def __init__(self, params: VoltVARParams) -> None:
        self.params = params
        self.state = VoltageState()
        self._q_setpoint_kvar: float = 0.0

    def _volt_var_curve(self, v_pu: float) -> float:
        """
        Piecewise linear volt-VAR droop curve.
        Returns Q setpoint in kVAR (positive = capacitive injection).
        """
        v_low, v_high = self.params.v_deadband_pu
        v_min, v_max = self.params.v_range_pu
        q_max_kvar = self.params.q_max_pu * self.params.s_rated_kva

        if v_pu >= v_high:
            # Over-voltage: absorb reactive power
            slope = -q_max_kvar / (v_max - v_high)
            return max(-q_max_kvar, slope * (v_pu - v_high))
        elif v_pu <= v_low:
            # Under-voltage: inject reactive power
            slope = q_max_kvar / (v_low - v_min)
            return min(q_max_kvar, slope * (v_low - v_pu))
        else:
            return 0.0

    def _volt_watt_curtailment(self, v_pu: float, p_available_kw: float) -> float:
        """
        Volt-watt active power curtailment at high voltage.
        Linear ramp from p_available at v=1.06 to 0 at v=1.10.
        """
        if not self.params.volt_watt_enabled:
            return p_available_kw
        v_start = 1.06
        v_end = self.params.v_range_pu[1]
        if v_pu <= v_start:
            return p_available_kw
        elif v_pu >= v_end:
            return 0.0
        else:
            fraction = (v_end - v_pu) / (v_end - v_start)
            return p_available_kw * fraction

    def dispatch(self, v_pu: float, p_requested_kw: float) -> VoltageState:
        """
        Compute inverter P and Q dispatch given terminal voltage and P request.

        Returns updated VoltageState.
        """
        p_max = self.params.s_rated_kva  # Max P in kW (unity PF)
        q_max = self.params.q_max_pu * self.params.s_rated_kva

        # Volt-watt curtailment
        p_kw = min(p_requested_kw, self._volt_watt_curtailment(v_pu, p_requested_kw))
        p_kw = max(0.0, min(p_kw, p_max))

        # Volt-VAR Q setpoint
        q_kvar = self._volt_var_curve(v_pu)

        # Enforce PQ capability circle: P^2 + Q^2 <= S_rated^2
        s_available = math.sqrt(max(0.0, self.params.s_rated_kva**2 - p_kw**2))
        q_kvar = max(-s_available, min(s_available, q_kvar))
        q_kvar = max(-q_max, min(q_max, q_kvar))

        s_kva = math.sqrt(p_kw**2 + q_kvar**2)
        pf = p_kw / s_kva if s_kva > 0.01 else 1.0

        if q_kvar != 0.0:
            mode = "volt_var"
        elif p_kw < p_requested_kw:
            mode = "volt_watt"
        else:
            mode = "normal"

        self.state = VoltageState(
            v_pu=v_pu, p_kw=p_kw, q_kvar=q_kvar,
            s_kva=s_kva, pf=pf, mode=mode
        )
        return self.state

    def q_capability_at_p(self, p_kw: float) -> Tuple[float, float]:
        """
        Q capability envelope at given P output.

        Returns:
            (q_min_kvar, q_max_kvar) — absorption and injection limits.
        """
        q_limit = math.sqrt(max(0.0, self.params.s_rated_kva**2 - p_kw**2))
        q_pf_limit = p_kw * math.tan(math.acos(self.params.pf_min))
        q_bound = min(q_limit, q_pf_limit, self.params.q_max_pu * self.params.s_rated_kva)
        return -q_bound, q_bound


class VoltageSupportAggregator:
    """
    Aggregates volt-VAR response from a fleet of inverters.
    Coordinates Q dispatch to minimize voltage deviations across nodes.
    """

    def __init__(self, controllers: List[VoltVARController]) -> None:
        self.controllers = controllers

    def fleet_dispatch(
        self,
        v_pu_per_node: List[float],
        p_requested_kw_per_node: List[float],
    ) -> List[VoltageState]:
        """Dispatch all inverters and return per-node states."""
        assert len(v_pu_per_node) == len(self.controllers)
        return [
            ctrl.dispatch(v_pu_per_node[i], p_requested_kw_per_node[i])
            for i, ctrl in enumerate(self.controllers)
        ]

    def total_q_kvar(self) -> float:
        return sum(c.state.q_kvar for c in self.controllers)

    def total_p_kw(self) -> float:
        return sum(c.state.p_kw for c in self.controllers)

    def voltage_violations(self, v_pu_list: List[float], v_min: float = 0.95, v_max: float = 1.05) -> int:
        return sum(1 for v in v_pu_list if v < v_min or v > v_max)
