"""Compressed Air Energy Storage (CAES) asset model."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class CAESMode(Enum):
    COMPRESSING = "compressing"     # Charging: electric → compressed air
    EXPANDING = "expanding"         # Discharging: compressed air → electric
    IDLE = "idle"
    FAULT = "fault"


@dataclass
class CAESAsset:
    """
    Compressed Air Energy Storage (CAES) system.

    Two main configurations:
    1. Diabatic CAES: Uses natural gas burners before expansion turbines
       (Huntorf, McIntosh). Heat is not recovered from compression.
    2. Adiabatic CAES (A-CAES): Stores compression heat in TES, re-uses
       on expansion (no gas combustion). Pure electrical storage.
    3. Isothermal CAES: Near-isothermal compression/expansion using liquid pistons.

    This model handles both diabatic and adiabatic configurations.
    """

    asset_id: str
    cavern_volume_m3: float             # Underground cavern or vessel volume
    max_pressure_bar: float = 70.0      # Maximum storage pressure
    min_pressure_bar: float = 46.0      # Minimum operating pressure
    compressor_power_mw: float = 100.0  # Rated compressor (charging) power
    turbine_power_mw: float = 110.0     # Rated turbine (discharge) power
    adiabatic: bool = False             # True = A-CAES (no combustion)
    fuel_heat_rate_mj_per_kwh: float = 1.5  # Supplemental heat (diabatic only)
    compression_efficiency: float = 0.80   # Isentropic efficiency of compressor
    expansion_efficiency: float = 0.85     # Isentropic efficiency of turbine

    _pressure_bar: float = field(default=0.0, init=False, repr=False)
    _mode: CAESMode = field(default=CAESMode.IDLE, init=False, repr=False)
    _total_compression_mwh: float = field(default=0.0, init=False, repr=False)
    _total_generation_mwh: float = field(default=0.0, init=False, repr=False)
    _total_fuel_mj: float = field(default=0.0, init=False, repr=False)

    # Air properties
    AIR_GAMMA: ClassVar[float] = 1.4        # Ratio of specific heats
    AIR_R_KJ_KG_K: ClassVar[float] = 0.287  # Specific gas constant (kJ/kg·K)
    AIR_DENSITY_KG_M3: ClassVar[float] = 1.225  # At standard conditions

    def __post_init__(self) -> None:
        # Initialize at min pressure
        self._pressure_bar = self.min_pressure_bar

    @property
    def pressure_bar(self) -> float:
        return self._pressure_bar

    @property
    def soc(self) -> float:
        """State of charge as fraction of usable pressure range."""
        if self.max_pressure_bar <= self.min_pressure_bar:
            return 0.0
        return max(
            0.0,
            min(
                1.0,
                (self._pressure_bar - self.min_pressure_bar)
                / (self.max_pressure_bar - self.min_pressure_bar),
            ),
        )

    @property
    def stored_air_mass_kg(self) -> float:
        """
        Mass of stored air using ideal gas law: m = P*V / (R*T).
        Assuming T = 300K (27°C).
        """
        T_K = 300.0
        # P in Pa, V in m³, R = 287 J/(kg·K)
        p_pa = self._pressure_bar * 1e5
        return p_pa * self.cavern_volume_m3 / (287.0 * T_K)

    def _stored_energy_mwh(self) -> float:
        """
        Estimate stored energy using isentropic work content:
        W = m * Cp * T * [(P2/P1)^((γ-1)/γ) - 1]
        """
        if self._pressure_bar <= self.min_pressure_bar:
            return 0.0
        T_K = 300.0
        Cp = 1.005  # kJ/(kg·K) for air
        m_above_min = (
            (self._pressure_bar - self.min_pressure_bar)
            / self._pressure_bar
            * self.stored_air_mass_kg
        )
        pressure_ratio = self._pressure_bar / self.min_pressure_bar
        work_kj = m_above_min * Cp * T_K * (
            pressure_ratio ** ((self.AIR_GAMMA - 1) / self.AIR_GAMMA) - 1
        )
        return work_kj / 3600.0 / 1000.0  # Convert kJ to MWh

    def compress(self, power_mw: float, duration_hours: float) -> float:
        """
        Compress air into the cavern using electrical power.

        Returns actual electrical energy consumed (MWh).
        """
        if self._mode == CAESMode.FAULT:
            return 0.0
        power_mw = min(power_mw, self.compressor_power_mw)
        energy_in_mwh = power_mw * duration_hours

        # Convert electrical energy to pressure rise via polytropic work
        # Simplified: use efficiency to convert electrical → pneumatic
        pneumatic_mwh = energy_in_mwh * self.compression_efficiency

        # Pressure increase: ΔP = pneumatic_energy / (V * 1e5 / 3600e6)
        # Using simplified linear: ΔP[bar] ≈ pneumatic_mwh * 3600e6 / (V * 1e5)
        dp_bar = pneumatic_mwh * 3600.0e6 / (self.cavern_volume_m3 * 1.0e5)
        new_pressure = self._pressure_bar + dp_bar
        if new_pressure >= self.max_pressure_bar:
            # Throttle compressor to avoid overpressure
            actual_dp = max(0.0, self.max_pressure_bar - self._pressure_bar)
            frac = actual_dp / dp_bar if dp_bar > 0 else 0.0
            energy_in_mwh *= frac
            self._pressure_bar = self.max_pressure_bar
        else:
            self._pressure_bar = new_pressure

        self._mode = CAESMode.COMPRESSING
        self._total_compression_mwh += energy_in_mwh
        return energy_in_mwh

    def expand(self, power_mw: float, duration_hours: float) -> float:
        """
        Generate electricity by expanding stored compressed air.

        Returns actual AC power generated (MWh). For diabatic CAES,
        adds supplemental fuel heat input.
        """
        if self._mode == CAESMode.FAULT or self.soc <= 0:
            return 0.0
        power_mw = min(power_mw, self.turbine_power_mw)

        # Energy needed from compressed air
        output_mwh = power_mw * duration_hours
        pneumatic_needed_mwh = output_mwh / self.expansion_efficiency

        # Convert pneumatic energy to pressure drop
        dp_bar = pneumatic_needed_mwh * 3600.0e6 / (self.cavern_volume_m3 * 1.0e5)
        new_pressure = self._pressure_bar - dp_bar
        if new_pressure <= self.min_pressure_bar:
            # Limited by available air
            actual_dp = max(0.0, self._pressure_bar - self.min_pressure_bar)
            frac = actual_dp / dp_bar if dp_bar > 0 else 0.0
            output_mwh *= frac
            self._pressure_bar = self.min_pressure_bar
        else:
            self._pressure_bar = new_pressure

        # Add fuel input for diabatic CAES
        if not self.adiabatic:
            self._total_fuel_mj += output_mwh * 3600.0 * self.fuel_heat_rate_mj_per_kwh

        self._mode = CAESMode.EXPANDING
        self._total_generation_mwh += output_mwh
        return output_mwh

    def idle(self) -> None:
        self._mode = CAESMode.IDLE

    @property
    def roundtrip_efficiency(self) -> float:
        """Electrical round-trip efficiency (excluding fuel input)."""
        if self._total_compression_mwh <= 0:
            return self.compression_efficiency * self.expansion_efficiency
        return self._total_generation_mwh / self._total_compression_mwh

    @property
    def available_generation_mwh(self) -> float:
        """Estimated available electrical generation from current storage level."""
        return self._stored_energy_mwh() * self.expansion_efficiency

    def reg_up_capability_mw(self) -> float:
        """Regulation-up: available turbine headroom."""
        return min(self.turbine_power_mw, self.available_generation_mwh / 0.25)

    def __repr__(self) -> str:
        return (
            f"CAESAsset(id={self.asset_id!r}, "
            f"pressure={self._pressure_bar:.1f}bar, "
            f"soc={self.soc:.1%}, mode={self._mode.value}, "
            f"adiabatic={self.adiabatic})"
        )
