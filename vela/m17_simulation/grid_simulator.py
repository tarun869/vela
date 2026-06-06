"""
Grid frequency and voltage simulation for VPP testing.

Generates synthetic grid frequency and voltage profiles for testing
VPP grid services including frequency regulation and volt-VAR response.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np
from numpy.random import default_rng


@dataclass
class GridSimParams:
    f_nominal_hz: float = 60.0
    v_nominal_pu: float = 1.0
    system_inertia_s: float = 5.0       # System inertia constant (s)
    system_damping: float = 0.5         # Damping factor
    load_freq_response_pu: float = 0.02 # Load damping (pu/pu)
    f_noise_std: float = 0.005          # Random frequency noise (Hz)
    v_noise_std: float = 0.003          # Random voltage noise (pu)


class GridSimulator:
    """
    Simplified single-bus power system simulator.

    Simulates swing equation:
    2H * df/dt = P_mech - P_elec - D * (f - f0)
    """

    def __init__(self, params: GridSimParams, seed: int = 42) -> None:
        self.params = params
        self.rng = default_rng(seed)
        self._f = params.f_nominal_hz
        self._v = params.v_nominal_pu

    def simulate_disturbance(
        self,
        disturbance_mw: float,
        system_size_mw: float,
        duration_s: float = 60.0,
        dt_s: float = 0.1,
        vpp_response_fn=None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Simulate frequency following a generation loss event.

        Returns:
            (time_s, frequency_hz, voltage_pu) arrays.
        """
        n_steps = int(duration_s / dt_s)
        p = self.params
        times = np.arange(n_steps) * dt_s
        freqs = np.zeros(n_steps)
        voltages = np.zeros(n_steps)

        f = p.f_nominal_hz
        df_dt = 0.0
        power_imbalance = -disturbance_mw / system_size_mw  # pu

        for t in range(n_steps):
            # VPP response
            p_vpp = 0.0
            if vpp_response_fn is not None:
                p_vpp = vpp_response_fn(f, df_dt) / system_size_mw

            # Swing equation: 2H * df/dt = P_imbalance - D * delta_f + P_vpp
            delta_f = f - p.f_nominal_hz
            d2f = (power_imbalance - p.load_freq_response_pu * delta_f + p_vpp) / (2 * p.system_inertia_s / p.f_nominal_hz)
            df_dt = d2f
            f += df_dt * dt_s + self.rng.normal(0, p.f_noise_std)

            # Simple voltage model: V slightly correlated with freq
            v = p.v_nominal_pu - 0.05 * (1 - f / p.f_nominal_hz) + self.rng.normal(0, p.v_noise_std)

            freqs[t] = f
            voltages[t] = max(0.8, min(1.2, v))

        return times, freqs, voltages

    def generate_normal_operation(
        self,
        n_hours: int = 24,
        dt_s: float = 1.0,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Generate normal-operation frequency and voltage profiles.

        Returns:
            (frequency_hz, voltage_pu) arrays of length n_hours * 3600 / dt_s.
        """
        n_steps = int(n_hours * 3600 / dt_s)
        p = self.params

        # Random walk with mean reversion
        freqs = np.zeros(n_steps)
        voltages = np.zeros(n_steps)
        f = p.f_nominal_hz
        v = p.v_nominal_pu

        for t in range(n_steps):
            f += (-1.0 * (f - p.f_nominal_hz) * dt_s / 60.0
                  + self.rng.normal(0, p.f_noise_std))
            v += (-0.5 * (v - p.v_nominal_pu) * dt_s / 60.0
                  + self.rng.normal(0, p.v_noise_std))
            freqs[t] = f
            voltages[t] = max(0.85, min(1.1, v))

        return freqs, voltages
