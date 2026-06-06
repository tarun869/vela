"""Diesel/natural gas generator set asset model."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class GensetFuelType(Enum):
    DIESEL = "diesel"
    NATURAL_GAS = "natural_gas"
    DUAL_FUEL = "dual_fuel"
    BIOGAS = "biogas"


class GensetMode(Enum):
    RUNNING = "running"
    IDLE = "idle"
    STANDBY = "standby"     # Ready to start within seconds
    OFF = "off"
    FAULT = "fault"
    STARTING = "starting"
    COOLING_DOWN = "cooling_down"


@dataclass
class GensetEmissions:
    """Generator emissions model per EPA Tier 4 Final standards."""
    nox_g_per_kwh: float = 0.40         # NOx emissions
    pm_g_per_kwh: float = 0.02          # Particulate matter
    co2_g_per_kwh: float = 750.0        # CO2 (diesel ~750 g/kWh)
    co_g_per_kwh: float = 2.5           # Carbon monoxide

    def compute(self, energy_kwh: float) -> dict[str, float]:
        return {
            "nox_kg": self.nox_g_per_kwh * energy_kwh / 1000.0,
            "pm_kg": self.pm_g_per_kwh * energy_kwh / 1000.0,
            "co2_kg": self.co2_g_per_kwh * energy_kwh / 1000.0,
            "co_kg": self.co_g_per_kwh * energy_kwh / 1000.0,
        }


@dataclass
class GensetAsset:
    """
    Diesel or natural gas generator set (genset).

    Models steady-state operation including fuel consumption, heat rate,
    ramp rates, startup/shutdown costs, and emissions.
    """

    asset_id: str
    rated_power_kw: float               # Nameplate power output
    fuel_type: GensetFuelType = GensetFuelType.DIESEL
    min_load_pct: float = 30.0          # Minimum stable load (% of rated)
    ramp_rate_kw_per_min: float = 50.0  # Output ramp rate
    startup_time_min: float = 0.5       # Time to reach min load from standby
    cooldown_time_min: float = 5.0      # Post-shutdown cooldown
    startup_cost_usd: float = 15.0      # Cost per start event
    maintenance_cost_usd_per_kwh: float = 0.008  # O&M cost
    emissions: GensetEmissions = field(default_factory=GensetEmissions)

    # Fuel properties
    _fuel_lhv_kwh_per_liter: ClassVar[dict[str, float]] = {
        "diesel": 9.90,
        "natural_gas": 9.91,  # per liter-equivalent
        "dual_fuel": 9.50,
        "biogas": 5.90,
    }

    # Heat rate at full load (kJ/kWh — lower is better)
    heat_rate_full_kj_per_kwh: float = 10_500.0    # ~11,000 Btu/kWh diesel
    heat_rate_half_kj_per_kwh: float = 12_500.0    # Penalty at 50% load

    _current_power_kw: float = field(default=0.0, init=False, repr=False)
    _mode: GensetMode = field(default=GensetMode.OFF, init=False, repr=False)
    _total_energy_kwh: float = field(default=0.0, init=False, repr=False)
    _total_fuel_liters: float = field(default=0.0, init=False, repr=False)
    _start_count: int = field(default=0, init=False, repr=False)

    @property
    def rated_power_mw(self) -> float:
        return self.rated_power_kw / 1000.0

    @property
    def current_power_kw(self) -> float:
        return self._current_power_kw

    @property
    def mode(self) -> GensetMode:
        return self._mode

    @property
    def min_load_kw(self) -> float:
        return self.rated_power_kw * self.min_load_pct / 100.0

    def heat_rate_kj_per_kwh(self, load_fraction: float) -> float:
        """
        Part-load heat rate using linear interpolation between half and full load.

        Gensets are less efficient at partial load (wet-stacking risk below 30%).
        """
        load_fraction = max(0.3, min(1.0, load_fraction))
        # At 50% load: use half-load heat rate
        if load_fraction <= 0.5:
            t = (load_fraction - 0.3) / 0.2
            return self.heat_rate_half_kj_per_kwh * (1 + (1 - t) * 0.1)
        else:
            t = (load_fraction - 0.5) / 0.5
            return (
                self.heat_rate_half_kj_per_kwh
                + t * (self.heat_rate_full_kj_per_kwh - self.heat_rate_half_kj_per_kwh)
            )

    def fuel_consumption_liters_per_hour(self, power_kw: float) -> float:
        """
        Compute fuel consumption at given output power.

        fuel_rate = power_kw * heat_rate_kj_per_kwh / LHV_kj_per_liter
        """
        if power_kw <= 0:
            return 0.0
        load_fraction = power_kw / self.rated_power_kw
        hr = self.heat_rate_kj_per_kwh(load_fraction)
        lhv = self._fuel_lhv_kwh_per_liter.get(self.fuel_type.value, 9.9) * 3600  # kJ/L
        return power_kw * hr / lhv

    def start(self) -> bool:
        """Start the genset (assumes standby mode or off)."""
        if self._mode in (GensetMode.OFF, GensetMode.STANDBY, GensetMode.COOLING_DOWN):
            self._mode = GensetMode.STARTING
            self._start_count += 1
            return True
        return False

    def stop(self) -> bool:
        """Stop the genset and enter cooldown."""
        if self._mode == GensetMode.RUNNING:
            self._current_power_kw = 0.0
            self._mode = GensetMode.COOLING_DOWN
            return True
        return False

    def dispatch(self, power_kw: float, duration_hours: float) -> float:
        """
        Dispatch the genset at a target power for a given duration.

        Returns actual energy generated in kWh.
        """
        if self._mode not in (GensetMode.RUNNING, GensetMode.STARTING):
            return 0.0
        if self._mode == GensetMode.STARTING:
            self._mode = GensetMode.RUNNING

        power_kw = max(self.min_load_kw, min(power_kw, self.rated_power_kw))

        # Apply ramp rate constraint
        max_step = self.ramp_rate_kw_per_min * duration_hours * 60
        if power_kw > self._current_power_kw:
            power_kw = min(power_kw, self._current_power_kw + max_step)
        elif power_kw < self._current_power_kw:
            power_kw = max(power_kw, self._current_power_kw - max_step)

        self._current_power_kw = power_kw
        energy_kwh = power_kw * duration_hours
        self._total_energy_kwh += energy_kwh
        self._total_fuel_liters += (
            self.fuel_consumption_liters_per_hour(power_kw) * duration_hours
        )
        return energy_kwh

    def operating_cost_usd(self, power_kw: float, duration_hours: float) -> float:
        """Compute variable operating cost for a dispatch period."""
        fuel_cost_per_liter = 1.20 if self.fuel_type == GensetFuelType.DIESEL else 0.35
        fuel_cost = self.fuel_consumption_liters_per_hour(power_kw) * duration_hours * fuel_cost_per_liter
        maintenance_cost = power_kw * duration_hours * self.maintenance_cost_usd_per_kwh
        return fuel_cost + maintenance_cost

    def marginal_cost_usd_per_kwh(self, power_kw: float) -> float:
        """Compute marginal fuel + O&M cost at a given output."""
        if power_kw <= 0:
            return 0.0
        fuel_rate_l_per_h = self.fuel_consumption_liters_per_hour(power_kw)
        fuel_cost_per_liter = 1.20 if self.fuel_type == GensetFuelType.DIESEL else 0.35
        fuel_cost_per_kwh = fuel_rate_l_per_h * fuel_cost_per_liter / power_kw
        return fuel_cost_per_kwh + self.maintenance_cost_usd_per_kwh

    @property
    def total_runtime_hours(self) -> float:
        if self.rated_power_kw > 0:
            return self._total_energy_kwh / (self.rated_power_kw * 0.75)
        return 0.0

    @property
    def start_count(self) -> int:
        return self._start_count

    def reg_up_capability_kw(self) -> float:
        """Regulation-up headroom (ramp up within 10 minutes)."""
        return min(
            self.rated_power_kw - self._current_power_kw,
            self.ramp_rate_kw_per_min * 10,
        )

    def reg_down_capability_kw(self) -> float:
        """Regulation-down headroom (ramp down within 10 minutes)."""
        return min(
            self._current_power_kw - self.min_load_kw,
            self.ramp_rate_kw_per_min * 10,
        )

    def __repr__(self) -> str:
        return (
            f"GensetAsset(id={self.asset_id!r}, "
            f"fuel={self.fuel_type.value}, "
            f"power={self._current_power_kw:.1f}kW/{self.rated_power_kw}kW, "
            f"mode={self._mode.value})"
        )
