"""Solar PV asset model with irradiance-to-power conversion."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import ClassVar


class SolarMode(Enum):
    MPPT = "mppt"           # Maximum power point tracking
    CURTAILED = "curtailed"
    OFFLINE = "offline"
    FAULT = "fault"


@dataclass
class SolarDegradation:
    """
    PV panel degradation model.

    Industry standard: ~0.5–0.7% per year linear degradation.
    """
    years_installed: float = 0.0
    degradation_rate_per_year: float = 0.007  # 0.7% per year

    @property
    def power_factor(self) -> float:
        """Remaining power output fraction."""
        return max(0.80, 1.0 - self.degradation_rate_per_year * self.years_installed)


@dataclass
class SolarAsset:
    """
    Solar photovoltaic (PV) generation asset.

    Models the DC-AC conversion from solar irradiance to AC power output
    using the PVWatts simplified model with temperature correction.
    """

    asset_id: str
    capacity_kwp: float                 # Nameplate DC capacity (kWp)
    inverter_efficiency: float = 0.96   # DC-AC inverter efficiency
    system_losses: float = 0.14         # Aggregate system losses (soiling, wiring, etc.)
    tilt_deg: float = 20.0              # Panel tilt angle in degrees
    azimuth_deg: float = 180.0          # Panel azimuth (180=south)
    latitude: float = 37.0              # Site latitude (degrees)
    temperature_coefficient: float = -0.004  # Power temp coefficient (%/°C)
    stc_temperature_c: float = 25.0     # Standard test condition temperature
    noct_c: float = 45.0                # Nominal operating cell temperature
    degradation: SolarDegradation = field(default_factory=SolarDegradation)

    _current_power_kw: float = field(default=0.0, init=False, repr=False)
    _mode: SolarMode = field(default=SolarMode.OFFLINE, init=False, repr=False)
    _curtailment_limit_kw: float | None = field(default=None, init=False, repr=False)
    _total_energy_kwh: float = field(default=0.0, init=False, repr=False)

    # Standard test conditions
    STC_IRRADIANCE: ClassVar[float] = 1000.0    # W/m²
    STC_TEMPERATURE: ClassVar[float] = 25.0      # °C

    @property
    def capacity_mwp(self) -> float:
        return self.capacity_kwp / 1000.0

    @property
    def current_power_kw(self) -> float:
        return self._current_power_kw

    @property
    def current_power_mw(self) -> float:
        return self._current_power_kw / 1000.0

    @property
    def mode(self) -> SolarMode:
        return self._mode

    def compute_cell_temperature(
        self, ambient_temp_c: float, irradiance_wm2: float
    ) -> float:
        """
        Estimate PV cell temperature using the NOCT model.

        T_cell = T_ambient + (NOCT - 20) * G / 800
        """
        return ambient_temp_c + (self.noct_c - 20.0) * irradiance_wm2 / 800.0

    def compute_dc_power_kw(
        self, irradiance_wm2: float, ambient_temp_c: float
    ) -> float:
        """
        Compute DC power output using PVWatts simplified model.

        P_dc = P_nameplate * (G / G_stc) * [1 + γ * (T_cell - T_stc)]

        Where γ is the temperature power coefficient.
        """
        if irradiance_wm2 <= 0:
            return 0.0
        cell_temp = self.compute_cell_temperature(ambient_temp_c, irradiance_wm2)
        temp_correction = 1.0 + self.temperature_coefficient * (
            cell_temp - self.STC_TEMPERATURE
        )
        irradiance_fraction = irradiance_wm2 / self.STC_IRRADIANCE
        p_dc = (
            self.capacity_kwp
            * irradiance_fraction
            * temp_correction
            * self.degradation.power_factor
        )
        return max(0.0, p_dc)

    def compute_ac_power_kw(
        self, irradiance_wm2: float, ambient_temp_c: float
    ) -> float:
        """
        Compute AC power output including inverter efficiency and system losses.
        """
        p_dc = self.compute_dc_power_kw(irradiance_wm2, ambient_temp_c)
        p_ac = p_dc * self.inverter_efficiency * (1.0 - self.system_losses)
        # Clamp at inverter rating (typically 10–20% clipping)
        return min(p_ac, self.capacity_kwp * self.inverter_efficiency)

    def update(
        self,
        irradiance_wm2: float,
        ambient_temp_c: float,
        duration_hours: float = 0.25,
    ) -> float:
        """
        Update asset state for a new irradiance/temperature reading.

        Returns the AC power output in kW.
        """
        p_ac = self.compute_ac_power_kw(irradiance_wm2, ambient_temp_c)

        if p_ac <= 0.001:
            self._mode = SolarMode.OFFLINE
            self._current_power_kw = 0.0
        elif self._curtailment_limit_kw is not None and p_ac > self._curtailment_limit_kw:
            self._mode = SolarMode.CURTAILED
            self._current_power_kw = self._curtailment_limit_kw
        else:
            self._mode = SolarMode.MPPT
            self._current_power_kw = p_ac

        self._total_energy_kwh += self._current_power_kw * duration_hours
        return self._current_power_kw

    def curtail(self, limit_kw: float) -> None:
        """Apply a curtailment limit (from grid operator or optimizer)."""
        self._curtailment_limit_kw = max(0.0, limit_kw)
        self._mode = SolarMode.CURTAILED

    def uncurtail(self) -> None:
        """Remove curtailment limit and return to MPPT."""
        self._curtailment_limit_kw = None
        self._mode = SolarMode.MPPT

    @staticmethod
    def compute_solar_position(
        latitude_deg: float, day_of_year: int, hour_utc: float
    ) -> tuple[float, float]:
        """
        Compute solar elevation and azimuth using approximate formula.

        Returns (elevation_deg, azimuth_deg).
        """
        lat = math.radians(latitude_deg)
        # Solar declination
        declination = math.radians(
            23.45 * math.sin(math.radians(360.0 / 365.0 * (day_of_year - 81)))
        )
        # Hour angle (solar noon = 0)
        hour_angle = math.radians((hour_utc - 12.0) * 15.0)
        # Solar elevation
        sin_elev = (
            math.sin(lat) * math.sin(declination)
            + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)
        )
        elevation = math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))
        # Solar azimuth
        cos_az = (
            (math.sin(declination) - math.sin(lat) * sin_elev)
            / (math.cos(lat) * math.cos(math.asin(sin_elev)) + 1e-9)
        )
        azimuth = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
        if hour_angle > 0:
            azimuth = 360.0 - azimuth
        return elevation, azimuth

    @staticmethod
    def clear_sky_irradiance(
        elevation_deg: float,
        altitude_m: float = 0.0,
    ) -> float:
        """
        Simple clear-sky global horizontal irradiance estimate.

        Uses simplified Bird clear-sky model.
        Returns irradiance in W/m².
        """
        if elevation_deg <= 0:
            return 0.0
        # Air mass (Kasten formula)
        z = 90.0 - elevation_deg
        cos_z = math.cos(math.radians(z))
        air_mass = 1.0 / (cos_z + 0.50572 * (96.07995 - z) ** -1.6364)
        # Altitude correction
        pressure_ratio = math.exp(-altitude_m / 8500.0)
        am = air_mass * pressure_ratio
        # Simplified transmittance
        transmittance = 0.7 ** (am ** 0.678)
        return 1367.0 * transmittance * math.sin(math.radians(elevation_deg))

    @property
    def total_energy_mwh(self) -> float:
        return self._total_energy_kwh / 1000.0

    def capacity_factor_ltm(self) -> float:
        """Long-term average capacity factor (generation / nameplate potential)."""
        if self._total_energy_kwh <= 0:
            return 0.0
        # Rough: compare to theoretical max at 1000 W/m² all day
        return 0.0  # Would need time-series to compute meaningfully

    def __repr__(self) -> str:
        return (
            f"SolarAsset(id={self.asset_id!r}, "
            f"cap={self.capacity_kwp}kWp, "
            f"power={self._current_power_kw:.1f}kW, mode={self._mode.value})"
        )
