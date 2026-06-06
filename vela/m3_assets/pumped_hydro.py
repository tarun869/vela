"""Pumped hydroelectric storage asset model."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class PumpedHydroMode(Enum):
    PUMPING = "pumping"         # Charging: pumping water uphill
    GENERATING = "generating"  # Discharging: generating electricity
    IDLE = "idle"
    SPINNING_RESERVE = "spinning" # Synchronized but not generating
    FAULT = "fault"
    MAINTENANCE = "maintenance"


@dataclass
class PumpedHydroAsset:
    """
    Pumped Hydroelectric Storage (PHS) asset.

    Stores energy by pumping water from a lower reservoir to an upper reservoir.
    On discharge, water flows downhill through turbines to generate electricity.

    Physics:
    - Power: P = ρ * g * H * Q * η
    - Energy: E = ρ * g * H * V * η

    Where:
    - ρ = water density (1000 kg/m³)
    - g = gravitational acceleration (9.81 m/s²)
    - H = hydraulic head (m)
    - Q = flow rate (m³/s)
    - V = volume (m³)
    - η = turbine/pump efficiency

    PHS is the world's dominant form of grid-scale storage, with response
    times of 10–30 seconds (Francis turbines) to <5 minutes (Pelton turbines).
    """

    asset_id: str
    capacity_mwh: float                 # Usable energy capacity
    turbine_power_mw: float             # Rated turbine generation power
    pump_power_mw: float                # Rated pump consumption power
    hydraulic_head_m: float = 200.0     # Net hydraulic head
    upper_reservoir_volume_m3: float = 1_000_000.0  # Active storage volume
    turbine_efficiency: float = 0.90    # Francis turbine efficiency
    pump_efficiency: float = 0.87       # Pump efficiency
    penstock_loss_pct: float = 2.0      # Friction losses in penstock
    generator_efficiency: float = 0.98  # Generator electrical efficiency
    motor_efficiency: float = 0.97      # Motor electrical efficiency
    min_soc: float = 0.05              # Dead storage
    max_soc: float = 0.95

    _soc: float = field(default=0.5, init=False, repr=False)
    _mode: PumpedHydroMode = field(default=PumpedHydroMode.IDLE, init=False, repr=False)
    _current_power_mw: float = field(default=0.0, init=False, repr=False)
    _total_generated_mwh: float = field(default=0.0, init=False, repr=False)
    _total_pumped_mwh: float = field(default=0.0, init=False, repr=False)

    WATER_DENSITY: ClassVar[float] = 1000.0   # kg/m³
    GRAVITY: ClassVar[float] = 9.81           # m/s²

    @property
    def soc(self) -> float:
        """State of charge as fraction of active storage volume."""
        return self._soc

    @property
    def mode(self) -> PumpedHydroMode:
        return self._mode

    @property
    def current_power_mw(self) -> float:
        """Positive = generating, negative = pumping."""
        return self._current_power_mw

    @property
    def water_volume_m3(self) -> float:
        """Current volume of water in upper reservoir."""
        return self._soc * self.upper_reservoir_volume_m3

    @property
    def available_generation_mwh(self) -> float:
        """Electrical energy available for generation."""
        available_vol = max(0.0, (self._soc - self.min_soc) * self.upper_reservoir_volume_m3)
        return self._volume_to_energy_mwh(available_vol) * self.roundtrip_generation_efficiency

    @property
    def available_pumping_mwh(self) -> float:
        """Additional energy that can be stored by pumping."""
        available_vol = max(0.0, (self.max_soc - self._soc) * self.upper_reservoir_volume_m3)
        # Electrical energy needed to pump this volume
        mwh_stored = self._volume_to_energy_mwh(available_vol)
        return mwh_stored / self.pump_efficiency / self.motor_efficiency

    @property
    def roundtrip_generation_efficiency(self) -> float:
        """Electrical efficiency from stored water to AC output."""
        penstock = 1.0 - self.penstock_loss_pct / 100.0
        return self.turbine_efficiency * penstock * self.generator_efficiency

    @property
    def roundtrip_pumping_efficiency(self) -> float:
        """Electrical efficiency from AC input to stored potential energy."""
        return self.pump_efficiency * self.motor_efficiency

    @property
    def roundtrip_efficiency(self) -> float:
        """Overall round-trip efficiency (pump then generate)."""
        return self.roundtrip_pumping_efficiency * self.roundtrip_generation_efficiency

    def _volume_to_energy_mwh(self, volume_m3: float) -> float:
        """
        Convert water volume to potential energy in MWh.
        E = ρ * g * H * V (in Joules)
        """
        energy_j = self.WATER_DENSITY * self.GRAVITY * self.hydraulic_head_m * volume_m3
        return energy_j / (3600.0 * 1e6)  # J → MWh

    def _energy_to_volume_m3(self, energy_mwh: float) -> float:
        """Convert energy in MWh to water volume."""
        energy_j = energy_mwh * 3600.0 * 1e6
        return energy_j / (self.WATER_DENSITY * self.GRAVITY * self.hydraulic_head_m)

    def generate(self, power_mw: float, duration_hours: float) -> float:
        """
        Generate electricity by releasing water through turbines.

        Returns actual AC energy generated (MWh).
        """
        if self._mode == PumpedHydroMode.FAULT or self._soc <= self.min_soc:
            return 0.0
        power_mw = min(power_mw, self.turbine_power_mw)

        # How much water must flow to produce this power?
        # P_ac = ρ * g * H * Q * η_turbine * η_penstock * η_generator
        penstock_eff = 1.0 - self.penstock_loss_pct / 100.0
        total_eff = self.turbine_efficiency * penstock_eff * self.generator_efficiency
        # Q (m³/s) = P_ac (W) / (ρ * g * H * η)
        flow_rate_m3s = (power_mw * 1e6) / (
            self.WATER_DENSITY * self.GRAVITY * self.hydraulic_head_m * total_eff
        )
        volume_consumed_m3 = flow_rate_m3s * duration_hours * 3600.0

        # Limit to available volume
        max_volume = max(0.0, (self._soc - self.min_soc) * self.upper_reservoir_volume_m3)
        actual_vol = min(volume_consumed_m3, max_volume)
        frac = actual_vol / volume_consumed_m3 if volume_consumed_m3 > 0 else 0.0

        self._soc -= actual_vol / self.upper_reservoir_volume_m3
        self._soc = max(self.min_soc, self._soc)
        energy_mwh = power_mw * duration_hours * frac
        self._current_power_mw = power_mw * frac
        self._mode = PumpedHydroMode.GENERATING
        self._total_generated_mwh += energy_mwh
        return energy_mwh

    def pump(self, power_mw: float, duration_hours: float) -> float:
        """
        Consume electrical power to pump water to the upper reservoir.

        Returns actual electrical energy consumed (MWh).
        """
        if self._mode == PumpedHydroMode.FAULT or self._soc >= self.max_soc:
            return 0.0
        power_mw = min(power_mw, self.pump_power_mw)

        # Volume pumped: Q = P_ac * η_motor * η_pump / (ρ * g * H)
        total_eff = self.pump_efficiency * self.motor_efficiency
        flow_rate_m3s = (power_mw * 1e6 * total_eff) / (
            self.WATER_DENSITY * self.GRAVITY * self.hydraulic_head_m
        )
        volume_pumped_m3 = flow_rate_m3s * duration_hours * 3600.0

        # Limit to headroom
        max_fill = max(0.0, (self.max_soc - self._soc) * self.upper_reservoir_volume_m3)
        actual_vol = min(volume_pumped_m3, max_fill)
        frac = actual_vol / volume_pumped_m3 if volume_pumped_m3 > 0 else 0.0

        self._soc += actual_vol / self.upper_reservoir_volume_m3
        self._soc = min(self.max_soc, self._soc)
        energy_consumed = power_mw * duration_hours * frac
        self._current_power_mw = -power_mw * frac  # Negative = consuming
        self._mode = PumpedHydroMode.PUMPING
        self._total_pumped_mwh += energy_consumed
        return energy_consumed

    def enter_spinning_reserve(self) -> None:
        """
        Synchronize turbine to grid without generating.

        Spinning reserve allows <10s response to full output.
        """
        self._mode = PumpedHydroMode.SPINNING_RESERVE
        self._current_power_mw = 0.0

    def idle(self) -> None:
        self._mode = PumpedHydroMode.IDLE
        self._current_power_mw = 0.0

    def max_flow_rate_m3s(self) -> float:
        """Maximum volumetric flow rate at rated power."""
        penstock_eff = 1.0 - self.penstock_loss_pct / 100.0
        return (self.turbine_power_mw * 1e6) / (
            self.WATER_DENSITY
            * self.GRAVITY
            * self.hydraulic_head_m
            * self.turbine_efficiency
            * penstock_eff
            * self.generator_efficiency
        )

    def reg_up_capability_mw(self) -> float:
        """Regulation-up capability (online generation headroom)."""
        if self._mode == PumpedHydroMode.SPINNING_RESERVE:
            # Spinning reserve: instant response
            return min(self.turbine_power_mw, self.available_generation_mwh / 0.1667)
        return max(0.0, self.turbine_power_mw - self._current_power_mw)

    def frequency_response_mw(self, frequency_hz: float) -> float:
        """
        Governor droop response to frequency deviation.

        5% droop: 0.05 * 60 Hz = 3 Hz gives 100% power response.
        """
        droop = 0.05
        deviation = 60.0 - frequency_hz
        if abs(deviation) < 0.03:  # Deadband ± 0.03 Hz
            return 0.0
        response = (deviation / (60.0 * droop)) * self.turbine_power_mw
        return max(0.0, min(self.turbine_power_mw, response))

    def __repr__(self) -> str:
        return (
            f"PumpedHydroAsset(id={self.asset_id!r}, "
            f"soc={self._soc:.1%}, cap={self.capacity_mwh}MWh, "
            f"turbine={self.turbine_power_mw}MW, mode={self._mode.value})"
        )
