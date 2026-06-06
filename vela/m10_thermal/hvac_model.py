"""
HVAC Thermal Model — RC circuit model for building thermal mass.

Models a building zone as a lumped-parameter RC (Resistance-Capacitance) circuit:
  - R_wall: thermal resistance of envelope (K/W)
  - C_zone: thermal capacitance of zone air + furniture (J/K)
  - T_zone: zone temperature state (°C)
  - T_out: outdoor temperature (°C)
  - Q_hvac: HVAC heat injection/extraction (W, positive = heating)
  - Q_solar: solar heat gain (W)
  - Q_internal: internal heat gains (occupants, equipment) (W)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class RCZoneParams:
    """Physical parameters for a single-zone RC thermal model."""
    r_wall: float          # Thermal resistance envelope (K/W)
    c_zone: float          # Thermal capacitance (J/K)
    r_infiltration: float  # Infiltration resistance (K/W)
    window_area: float     # Window area (m^2)
    shgc: float = 0.4      # Solar heat gain coefficient (dimensionless)
    internal_gain_w: float = 500.0  # Baseline internal gains (W)

    def __post_init__(self) -> None:
        if self.r_wall <= 0 or self.c_zone <= 0:
            raise ValueError("r_wall and c_zone must be positive")


@dataclass
class HVACState:
    """Runtime state for the RC HVAC model."""
    t_zone: float           # Current zone temperature (°C)
    t_zone_prev: float      # Previous zone temperature (°C)
    hvac_power_w: float     # Current HVAC power (W), positive = heating
    mode: str = "idle"      # "heating", "cooling", "idle"
    cumulative_energy_j: float = 0.0


class HVACModel:
    """
    Single-zone RC thermal model for HVAC simulation and control.

    Discretised Euler forward integration:
        C * dT/dt = (T_out - T_zone) / R_eff + Q_hvac + Q_solar + Q_internal

    where R_eff = R_wall || R_infiltration (parallel combination).
    """

    def __init__(self, params: RCZoneParams, t_zone_init: float = 22.0) -> None:
        self.params = params
        self.state = HVACState(
            t_zone=t_zone_init,
            t_zone_prev=t_zone_init,
            hvac_power_w=0.0,
        )
        self._r_eff: float = self._parallel_r(params.r_wall, params.r_infiltration)

    @staticmethod
    def _parallel_r(r1: float, r2: float) -> float:
        return (r1 * r2) / (r1 + r2)

    def solar_gain(self, ghi_w_m2: float) -> float:
        """Compute solar heat gain from global horizontal irradiance."""
        return ghi_w_m2 * self.params.window_area * self.params.shgc

    def step(
        self,
        dt_s: float,
        t_outdoor: float,
        q_hvac_w: float,
        ghi_w_m2: float = 0.0,
        occupancy_factor: float = 1.0,
    ) -> float:
        """
        Advance simulation by dt_s seconds.

        Returns:
            New zone temperature (°C).
        """
        q_solar = self.solar_gain(ghi_w_m2)
        q_internal = self.params.internal_gain_w * occupancy_factor
        q_envelope = (t_outdoor - self.state.t_zone) / self._r_eff

        d_temp = (q_envelope + q_hvac_w + q_solar + q_internal) / self.params.c_zone
        new_t_zone = self.state.t_zone + d_temp * dt_s

        self.state.t_zone_prev = self.state.t_zone
        self.state.t_zone = new_t_zone
        self.state.hvac_power_w = q_hvac_w
        self.state.cumulative_energy_j += abs(q_hvac_w) * dt_s

        if q_hvac_w > 1.0:
            self.state.mode = "heating"
        elif q_hvac_w < -1.0:
            self.state.mode = "cooling"
        else:
            self.state.mode = "idle"

        return new_t_zone

    def simulate(
        self,
        dt_s: float,
        t_outdoor_series: List[float],
        q_hvac_series: List[float],
        ghi_series: Optional[List[float]] = None,
        occupancy_series: Optional[List[float]] = None,
    ) -> List[float]:
        """Run a multi-step simulation and return zone temperature profile."""
        n = len(t_outdoor_series)
        if ghi_series is None:
            ghi_series = [0.0] * n
        if occupancy_series is None:
            occupancy_series = [1.0] * n

        temps: List[float] = []
        for i in range(n):
            t = self.step(
                dt_s=dt_s,
                t_outdoor=t_outdoor_series[i],
                q_hvac_w=q_hvac_series[i],
                ghi_w_m2=ghi_series[i],
                occupancy_factor=occupancy_series[i],
            )
            temps.append(t)
        return temps

    def setpoint_tracking_power(
        self,
        t_setpoint: float,
        t_outdoor: float,
        ghi_w_m2: float = 0.0,
        occupancy_factor: float = 1.0,
        cop: float = 3.5,
    ) -> Tuple[float, float]:
        """
        Compute steady-state HVAC power needed to maintain setpoint.

        Returns:
            (q_hvac_thermal_w, q_electrical_w) — thermal and electrical power.
        """
        q_solar = self.solar_gain(ghi_w_m2)
        q_internal = self.params.internal_gain_w * occupancy_factor
        q_envelope_loss = (self.state.t_zone - t_outdoor) / self._r_eff

        # At steady state: q_hvac = envelope_loss - solar - internal
        q_hvac_thermal = q_envelope_loss - q_solar - q_internal
        q_electrical = abs(q_hvac_thermal) / cop
        return q_hvac_thermal, q_electrical

    def thermal_time_constant(self) -> float:
        """RC time constant (seconds)."""
        return self.params.c_zone * self._r_eff

    def reset(self, t_zone: float = 22.0) -> None:
        self.state = HVACState(t_zone=t_zone, t_zone_prev=t_zone, hvac_power_w=0.0)


def build_typical_office_params(floor_area_m2: float = 200.0) -> RCZoneParams:
    """
    Return typical RC parameters for an office building zone.

    Rules of thumb:
      - R_wall ~ 0.02 K/W per m^2 of envelope (well-insulated)
      - C_zone ~ 50 kJ/(K·m^2) of floor area
    """
    envelope_area = floor_area_m2 * 4.0  # Rough perimeter assumption
    r_wall = 0.02 * envelope_area          # K/W
    c_zone = 50_000.0 * floor_area_m2      # J/K
    r_infiltration = r_wall * 5.0          # Infiltration 5x less dominant
    window_area = floor_area_m2 * 0.3      # 30% window-to-wall ratio

    return RCZoneParams(
        r_wall=r_wall,
        c_zone=c_zone,
        r_infiltration=r_infiltration,
        window_area=window_area,
        shgc=0.35,
        internal_gain_w=floor_area_m2 * 10.0,  # 10 W/m^2 internal gains
    )
