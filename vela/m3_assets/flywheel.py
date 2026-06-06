"""Flywheel energy storage asset model."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class FlywheelMode(Enum):
    CHARGING = "charging"       # Motor mode: accelerating rotor
    DISCHARGING = "discharging" # Generator mode: decelerating rotor
    IDLE = "idle"               # Coasting at constant speed
    FAULT = "fault"


@dataclass
class FlywheelAsset:
    """
    Flywheel Energy Storage System (FESS).

    Uses a rotating mass (rotor) connected to a motor-generator to store
    kinetic energy. Characterized by very high power density, fast response
    (< 4ms), and high cycle life, but low energy density.

    Ideal for short-duration services:
    - Frequency regulation (primary / secondary)
    - Voltage regulation
    - Power quality (UPS replacement)
    - Rate-of-change-of-frequency (ROCOF) response

    Physics: E = ½ * J * ω²
    Where J = moment of inertia (kg·m²), ω = angular velocity (rad/s)
    """

    asset_id: str
    capacity_mwh: float             # Usable energy capacity
    power_mw: float                 # Rated power (charge and discharge)
    rotor_mass_kg: float = 1000.0   # Flywheel rotor mass
    rotor_radius_m: float = 0.5     # Rotor radius (simplified solid disk)
    max_speed_rpm: float = 50000.0  # Maximum rotor speed
    min_speed_rpm: float = 20000.0  # Minimum operating speed (SOC=0)
    standby_loss_mw: float = 0.005  # Friction + windage + magnetic drag at idle
    efficiency: float = 0.95        # Round-trip electrical efficiency (motor + inverter)
    response_time_ms: float = 4.0   # Time to rated power

    _soc: float = field(default=0.5, init=False, repr=False)
    _speed_rpm: float = field(default=0.0, init=False, repr=False)
    _mode: FlywheelMode = field(default=FlywheelMode.IDLE, init=False, repr=False)
    _current_power_mw: float = field(default=0.0, init=False, repr=False)
    _total_cycles: float = field(default=0.0, init=False, repr=False)
    _total_energy_mwh: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        # Set initial speed corresponding to initial SOC
        self._speed_rpm = self._soc_to_rpm(self._soc)

    @property
    def moment_of_inertia_kg_m2(self) -> float:
        """Moment of inertia for solid disk: J = ½ * m * r²."""
        return 0.5 * self.rotor_mass_kg * self.rotor_radius_m ** 2

    def _soc_to_rpm(self, soc: float) -> float:
        """Convert SOC [0,1] to rotor speed [min_rpm, max_rpm]."""
        # E ∝ ω² → ω ∝ √E → rpm ∝ √SOC
        rpm_range = self.max_speed_rpm - self.min_speed_rpm
        return self.min_speed_rpm + math.sqrt(max(0.0, soc)) * rpm_range

    def _rpm_to_soc(self, rpm: float) -> float:
        """Convert rotor speed to SOC using E ∝ ω²."""
        rpm_range = self.max_speed_rpm - self.min_speed_rpm
        if rpm_range <= 0:
            return 0.0
        frac = (rpm - self.min_speed_rpm) / rpm_range
        # SOC = (ω/ω_max)² = frac²
        return max(0.0, min(1.0, frac ** 2))

    def _kinetic_energy_mwh(self, rpm: float) -> float:
        """Compute kinetic energy at a given RPM in MWh."""
        omega = rpm * 2 * math.pi / 60.0  # rad/s
        ek_j = 0.5 * self.moment_of_inertia_kg_m2 * omega ** 2
        return ek_j / (3600.0 * 1e6)  # J → MWh

    @property
    def soc(self) -> float:
        return self._soc

    @property
    def speed_rpm(self) -> float:
        return self._speed_rpm

    @property
    def current_power_mw(self) -> float:
        return self._current_power_mw

    @property
    def mode(self) -> FlywheelMode:
        return self._mode

    @property
    def available_discharge_mwh(self) -> float:
        """Energy available for discharge from current SOC."""
        return max(0.0, self._soc * self.capacity_mwh)

    @property
    def available_charge_mwh(self) -> float:
        """Headroom available for charging."""
        return max(0.0, (1.0 - self._soc) * self.capacity_mwh)

    def charge(self, power_mw: float, duration_hours: float) -> float:
        """
        Accelerate the flywheel using electrical power (motor mode).

        Returns actual AC electrical energy consumed (MWh).
        """
        if self._mode == FlywheelMode.FAULT:
            return 0.0
        power_mw = min(power_mw, self.power_mw)
        energy_in_mwh = power_mw * duration_hours * self.efficiency
        # Convert to SOC change via energy stored
        delta_soc = energy_in_mwh / self.capacity_mwh
        actual_delta = min(delta_soc, 1.0 - self._soc)
        self._soc += actual_delta
        self._speed_rpm = self._soc_to_rpm(self._soc)
        self._mode = FlywheelMode.CHARGING
        actual_energy_ac = (actual_delta / delta_soc * power_mw * duration_hours) if delta_soc > 0 else 0.0
        self._total_cycles += actual_delta * 0.5
        return actual_energy_ac

    def discharge(self, power_mw: float, duration_hours: float) -> float:
        """
        Decelerate the flywheel to generate electricity (generator mode).

        Returns actual AC electrical energy delivered (MWh).
        """
        if self._mode == FlywheelMode.FAULT or self._soc <= 0:
            return 0.0
        power_mw = min(power_mw, self.power_mw)
        energy_out_mwh = power_mw * duration_hours
        energy_from_rotor = energy_out_mwh / self.efficiency
        delta_soc = energy_from_rotor / self.capacity_mwh
        actual_delta = min(delta_soc, self._soc)
        self._soc = max(0.0, self._soc - actual_delta)
        self._speed_rpm = self._soc_to_rpm(self._soc)
        self._mode = FlywheelMode.DISCHARGING
        actual_energy_ac = (actual_delta / delta_soc * power_mw * duration_hours) if delta_soc > 0 else 0.0
        self._total_energy_mwh += actual_energy_ac
        self._total_cycles += actual_delta * 0.5
        return actual_energy_ac

    def idle_step(self, duration_hours: float) -> float:
        """
        Advance time with no charge/discharge.

        Applies standby losses (friction, windage, magnetic drag).
        Returns energy lost to standby losses (MWh).
        """
        standby_energy = self.standby_loss_mw * duration_hours
        standby_soc = standby_energy / self.capacity_mwh
        self._soc = max(0.0, self._soc - standby_soc)
        self._speed_rpm = self._soc_to_rpm(self._soc)
        if self._mode != FlywheelMode.FAULT:
            self._mode = FlywheelMode.IDLE
        return standby_energy

    def reg_up_capability_mw(self) -> float:
        """Instantaneous regulation-up capability."""
        return min(self.power_mw, self.available_discharge_mwh / (15.0 / 60.0))

    def reg_down_capability_mw(self) -> float:
        """Instantaneous regulation-down capability."""
        return min(self.power_mw, self.available_charge_mwh / (15.0 / 60.0))

    def rocof_response_mw(self, rocof_hz_per_s: float) -> float:
        """
        Synthetic inertia response to rate-of-change-of-frequency.

        Power ∝ df/dt (virtual inertia response).
        H = 5s virtual inertia constant (typical for flywheel).
        """
        H = 5.0  # seconds
        f0 = 60.0  # Hz
        capacity_mva = self.power_mw
        delta_p = -2 * H * capacity_mva * rocof_hz_per_s / f0
        return max(-self.power_mw, min(self.power_mw, delta_p))

    @property
    def total_cycles(self) -> float:
        """Equivalent full charge-discharge cycles completed."""
        return self._total_cycles

    @property
    def lifetime_years_estimate(self) -> float:
        """
        Estimated lifetime based on cycle count.

        Modern flywheel systems are rated for >100,000 full cycles (~100+ years
        at 5 cycles/day).
        """
        rated_cycles = 1_000_000.0  # Very high cycle life
        if self._total_cycles >= rated_cycles:
            return 0.0
        cycles_per_year = 365.0 * 5  # 5 cycles/day typical for regulation
        return (rated_cycles - self._total_cycles) / cycles_per_year

    def __repr__(self) -> str:
        return (
            f"FlywheelAsset(id={self.asset_id!r}, "
            f"soc={self._soc:.1%}, speed={self._speed_rpm:.0f}rpm, "
            f"power={self.power_mw}MW, mode={self._mode.value})"
        )
