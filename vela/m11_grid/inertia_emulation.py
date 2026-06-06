"""
Synthetic inertia emulation from grid-tied inverter resources.

Inverters can emulate the inertial response of synchronous machines by
rapidly injecting power proportional to ROCOF (virtual inertia) and
frequency deviation (virtual damping).

P_virtual = 2H * S_rated * (df/dt) / f_nominal + D * (f - f_nominal)

where H is virtual inertia constant (seconds) and D is damping coefficient.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class VirtualInertiaParams:
    resource_id: str
    s_rated_mva: float           # Rated apparent power (MVA)
    h_virtual_s: float = 4.0    # Virtual inertia constant (seconds), typical: 2–8s
    d_damping_pu: float = 20.0  # Virtual damping coefficient (pu power / pu freq)
    f_nominal_hz: float = 60.0
    p_max_pu: float = 0.20      # Max inertia response as fraction of S_rated
    rocof_filter_tc_s: float = 0.05  # Low-pass filter time constant for ROCOF


@dataclass
class InertiaEmulationState:
    p_inertia_mw: float = 0.0    # Active power for inertia response (MW)
    p_damping_mw: float = 0.0    # Active power for damping (MW)
    p_total_mw: float = 0.0      # Total synthetic inertia power (MW)
    rocof_filtered_hz_s: float = 0.0
    delta_f_hz: float = 0.0
    mode: str = "standby"        # "standby", "inertia_active", "damping_active"


class SyntheticInertiaController:
    """
    Virtual synchronous generator (VSG) / synthetic inertia controller.

    Implements virtual inertia (ROCOF-based) and virtual damping (frequency-based)
    control loops with rate limiting and capability constraints.
    """

    def __init__(self, params: VirtualInertiaParams) -> None:
        self.params = params
        self.state = InertiaEmulationState()
        self._f_prev: float = params.f_nominal_hz
        self._rocof_raw: float = 0.0
        self._rocof_filtered: float = 0.0

    def _filter_rocof(self, rocof_raw: float, dt_s: float) -> float:
        """First-order low-pass filter for noisy ROCOF measurement."""
        tc = self.params.rocof_filter_tc_s
        alpha = dt_s / (tc + dt_s)
        self._rocof_filtered += alpha * (rocof_raw - self._rocof_filtered)
        return self._rocof_filtered

    def _inertia_power(self, rocof_hz_s: float) -> float:
        """
        Virtual inertia power: P = 2H * S * (df/dt) / f_n
        Sign convention: negative ROCOF (frequency drop) → positive power injection.
        """
        p_mw = -2.0 * self.params.h_virtual_s * self.params.s_rated_mva * rocof_hz_s / self.params.f_nominal_hz
        p_max_mw = self.params.p_max_pu * self.params.s_rated_mva
        return max(-p_max_mw, min(p_max_mw, p_mw))

    def _damping_power(self, delta_f_hz: float) -> float:
        """
        Virtual damping power: P = D * (f - f_n) / f_n
        Positive frequency deviation → absorb power (brake effect).
        """
        p_mw = -self.params.d_damping_pu * self.params.s_rated_mva * delta_f_hz / self.params.f_nominal_hz
        p_max_mw = self.params.p_max_pu * self.params.s_rated_mva
        return max(-p_max_mw, min(p_max_mw, p_mw))

    def step(self, f_hz: float, dt_s: float) -> InertiaEmulationState:
        """
        Process one time step and compute synthetic inertia response.

        Returns:
            Updated InertiaEmulationState with power injection.
        """
        # Compute ROCOF
        rocof_raw = (f_hz - self._f_prev) / dt_s if dt_s > 0 else 0.0
        self._f_prev = f_hz
        rocof_filtered = self._filter_rocof(rocof_raw, dt_s)

        delta_f = f_hz - self.params.f_nominal_hz

        p_inertia = self._inertia_power(rocof_filtered)
        p_damping = self._damping_power(delta_f)
        p_total = p_inertia + p_damping

        # Mode determination
        if abs(p_total) > 0.001 * self.params.s_rated_mva:
            if abs(p_inertia) > abs(p_damping):
                mode = "inertia_active"
            else:
                mode = "damping_active"
        else:
            mode = "standby"

        self.state = InertiaEmulationState(
            p_inertia_mw=p_inertia,
            p_damping_mw=p_damping,
            p_total_mw=p_total,
            rocof_filtered_hz_s=rocof_filtered,
            delta_f_hz=delta_f,
            mode=mode,
        )
        return self.state

    def simulate(
        self,
        f_profile_hz: List[float],
        dt_s: float = 0.02,
    ) -> List[InertiaEmulationState]:
        """Run synthetic inertia simulation over frequency profile."""
        self._f_prev = f_profile_hz[0] if f_profile_hz else self.params.f_nominal_hz
        return [self.step(f, dt_s) for f in f_profile_hz]

    def nadir_improvement(
        self,
        f_profile_hz: List[float],
        dt_s: float = 0.02,
    ) -> Tuple[float, float, float]:
        """
        Estimate frequency nadir improvement from virtual inertia.

        Returns:
            (f_nadir_without_hz, f_nadir_with_hz, improvement_hz)
        """
        f_nadir_without = min(f_profile_hz)
        states = self.simulate(f_profile_hz, dt_s)

        # Approximate nadir improvement: integral of inertia power / system inertia
        total_energy_mwh = sum(abs(s.p_total_mw) * dt_s / 3600.0 for s in states)
        # Heuristic: each MW·s of support improves nadir by ~0.01 Hz per GW system
        improvement_hz = total_energy_mwh * 3600.0 * 0.01 / max(1.0, self.params.s_rated_mva / 1000.0)
        f_nadir_with = f_nadir_without + improvement_hz

        return f_nadir_without, f_nadir_with, improvement_hz

    def virtual_inertia_constant_effective(
        self, f_profile_hz: List[float], dt_s: float = 0.02
    ) -> float:
        """
        Compute effective virtual inertia constant from response.
        H_eff = P_response * f_n / (2 * S * ROCOF)
        """
        states = self.simulate(f_profile_hz, dt_s)
        h_values: List[float] = []
        for s in states:
            if abs(s.rocof_filtered_hz_s) > 0.01:
                h = abs(s.p_inertia_mw) * self.params.f_nominal_hz / (
                    2.0 * self.params.s_rated_mva * abs(s.rocof_filtered_hz_s)
                )
                h_values.append(h)
        return float(np.mean(h_values)) if h_values else self.params.h_virtual_s
