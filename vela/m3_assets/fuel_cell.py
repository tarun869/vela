"""Fuel cell / hydrogen storage asset model."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class FuelCellMode(Enum):
    GENERATING = "generating"
    IDLE = "idle"
    FAULT = "fault"
    STARTING = "starting"
    STOPPING = "stopping"


class ElectrolyzerMode(Enum):
    PRODUCING_H2 = "producing_h2"
    IDLE = "idle"
    FAULT = "fault"


@dataclass
class HydrogenTank:
    """Compressed hydrogen storage tank."""
    capacity_kg: float          # Total storage capacity in kg H2
    pressure_max_bar: float = 700.0
    pressure_min_bar: float = 5.0
    _mass_kg: float = field(default=0.0, init=False, repr=False)

    @property
    def mass_kg(self) -> float:
        return self._mass_kg

    @property
    def soc(self) -> float:
        return self._mass_kg / self.capacity_kg

    @property
    def pressure_bar(self) -> float:
        """Estimate pressure from fill level (simplified ideal gas)."""
        fill_frac = self._mass_kg / self.capacity_kg
        return self.pressure_min_bar + fill_frac * (self.pressure_max_bar - self.pressure_min_bar)

    def fill(self, mass_kg: float) -> float:
        """Fill the tank. Returns actual mass added."""
        headroom = self.capacity_kg - self._mass_kg
        actual = min(mass_kg, headroom)
        self._mass_kg += actual
        return actual

    def withdraw(self, mass_kg: float) -> float:
        """Withdraw from the tank. Returns actual mass withdrawn."""
        actual = min(mass_kg, self._mass_kg)
        self._mass_kg -= actual
        return actual


@dataclass
class FuelCellAsset:
    """
    PEM (Proton Exchange Membrane) fuel cell system with hydrogen storage.

    Generates electricity by electrochemically oxidizing hydrogen gas.
    The system includes a stack, balance-of-plant, and hydrogen storage tank.
    Optionally paired with an electrolyzer for long-duration energy storage.
    """

    asset_id: str
    rated_power_kw: float               # Rated electrical output (AC)
    tank: HydrogenTank = field(default_factory=lambda: HydrogenTank(capacity_kg=100.0))
    electrical_efficiency: float = 0.60  # LHV-based (H2 LHV = 33.33 kWh/kg)
    startup_time_min: float = 5.0        # Cold start time in minutes
    min_load_pct: float = 10.0           # Minimum stable load (% of rated)
    ramp_rate_kw_per_min: float = 20.0   # Output ramp rate
    heat_recovery: bool = False          # Whether CHP (combined heat + power) is used
    # Electrolyzer component (for power-to-hydrogen)
    electrolyzer_power_kw: float = 0.0  # Electrolyzer rated input power
    electrolyzer_efficiency: float = 0.65  # LHV efficiency

    _current_power_kw: float = field(default=0.0, init=False, repr=False)
    _mode: FuelCellMode = field(default=FuelCellMode.IDLE, init=False, repr=False)
    _electrolyzer_mode: ElectrolyzerMode = field(
        default=ElectrolyzerMode.IDLE, init=False, repr=False
    )
    _electrolyzer_power_kw: float = field(default=0.0, init=False, repr=False)
    _total_energy_kwh: float = field(default=0.0, init=False, repr=False)
    _total_h2_consumed_kg: float = field(default=0.0, init=False, repr=False)

    H2_LHV_KWH_PER_KG: ClassVar[float] = 33.33  # Lower heating value of H2

    @property
    def rated_power_mw(self) -> float:
        return self.rated_power_kw / 1000.0

    @property
    def current_power_kw(self) -> float:
        return self._current_power_kw

    @property
    def current_power_mw(self) -> float:
        return self._current_power_kw / 1000.0

    @property
    def mode(self) -> FuelCellMode:
        return self._mode

    @property
    def min_load_kw(self) -> float:
        return self.rated_power_kw * self.min_load_pct / 100.0

    def h2_consumption_rate_kg_per_hour(self, power_kw: float) -> float:
        """
        Compute hydrogen consumption rate at a given output power.

        At efficiency η: H2_rate = P_output / (η * LHV)
        """
        if power_kw <= 0:
            return 0.0
        # Efficiency is not constant: partial load penalty modeled as:
        # η_actual = η_rated * (0.7 + 0.3 * load_fraction)
        load_fraction = power_kw / self.rated_power_kw
        eta_actual = self.electrical_efficiency * (0.7 + 0.3 * load_fraction)
        return power_kw / (eta_actual * self.H2_LHV_KWH_PER_KG)

    def generate(self, power_kw: float, duration_hours: float) -> float:
        """
        Generate electrical power for a given duration.

        Returns actual AC power output in kW. Automatically draws from H2 tank.
        """
        if self._mode == FuelCellMode.FAULT:
            return 0.0
        power_kw = max(self.min_load_kw, min(power_kw, self.rated_power_kw))

        # Check hydrogen availability
        h2_needed_kg = self.h2_consumption_rate_kg_per_hour(power_kw) * duration_hours
        h2_available = self.tank.mass_kg
        if h2_available < h2_needed_kg:
            # Derate to available hydrogen
            if h2_available <= 0:
                self._current_power_kw = 0.0
                self._mode = FuelCellMode.IDLE
                return 0.0
            # Find max power given available H2 (iterative convergence)
            power_kw = self._solve_max_power_from_h2(h2_available, duration_hours)

        h2_consumed = self.h2_consumption_rate_kg_per_hour(power_kw) * duration_hours
        self.tank.withdraw(h2_consumed)
        self._current_power_kw = power_kw
        self._mode = FuelCellMode.GENERATING
        self._total_energy_kwh += power_kw * duration_hours
        self._total_h2_consumed_kg += h2_consumed
        return power_kw

    def _solve_max_power_from_h2(
        self, h2_kg: float, duration_hours: float
    ) -> float:
        """Binary search for max sustainable power given H2 availability."""
        lo, hi = self.min_load_kw, self.rated_power_kw
        for _ in range(20):
            mid = (lo + hi) / 2.0
            needed = self.h2_consumption_rate_kg_per_hour(mid) * duration_hours
            if needed <= h2_kg:
                lo = mid
            else:
                hi = mid
        return lo

    def electrolyze(self, input_power_kw: float, duration_hours: float) -> float:
        """
        Run the electrolyzer to produce hydrogen from excess electricity.

        Returns kg of H2 produced. Stores H2 in the tank.
        """
        if self.electrolyzer_power_kw <= 0:
            return 0.0
        input_power_kw = min(input_power_kw, self.electrolyzer_power_kw)
        # H2 production: m_H2 = (P_in * η * t) / LHV
        h2_produced = (
            input_power_kw * self.electrolyzer_efficiency * duration_hours
        ) / self.H2_LHV_KWH_PER_KG
        actual_stored = self.tank.fill(h2_produced)
        self._electrolyzer_power_kw = input_power_kw
        self._electrolyzer_mode = ElectrolyzerMode.PRODUCING_H2
        return actual_stored

    def stop_electrolyzer(self) -> None:
        self._electrolyzer_power_kw = 0.0
        self._electrolyzer_mode = ElectrolyzerMode.IDLE

    def idle(self) -> None:
        self._current_power_kw = 0.0
        self._mode = FuelCellMode.IDLE

    @property
    def stored_energy_mwh(self) -> float:
        """Energy equivalent of stored hydrogen at rated efficiency."""
        return self.tank.mass_kg * self.H2_LHV_KWH_PER_KG * self.electrical_efficiency / 1000.0

    @property
    def roundtrip_efficiency(self) -> float:
        """
        System round-trip efficiency (electrolysis → storage → generation).

        η_rt = η_electrolyzer * η_fuelcell
        """
        return self.electrolyzer_efficiency * self.electrical_efficiency

    def reg_up_capability_kw(self) -> float:
        """Available regulation-up: ramp headroom above current output."""
        return max(0.0, min(
            self.rated_power_kw - self._current_power_kw,
            self.ramp_rate_kw_per_min * 10,  # 10-minute response
        ))

    def __repr__(self) -> str:
        return (
            f"FuelCellAsset(id={self.asset_id!r}, "
            f"power={self._current_power_kw:.1f}kW, "
            f"h2_soc={self.tank.soc:.1%}, mode={self._mode.value})"
        )
