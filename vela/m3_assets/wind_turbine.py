"""Wind turbine asset model with power curve and wake effects."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class TurbineMode(Enum):
    PRODUCING = "producing"
    CURTAILED = "curtailed"
    PARKED = "parked"       # Wind below cut-in or above cut-out
    FAULT = "fault"
    MAINTENANCE = "maintenance"


@dataclass
class WindTurbineAsset:
    """
    Wind turbine generation asset with IEC 61400-12 compliant power curve.

    The power curve maps wind speed to output power, with cut-in, rated, and
    cut-out speed thresholds. Wake effects can be approximated by derating.
    """

    asset_id: str
    rotor_diameter_m: float             # Rotor diameter in meters
    hub_height_m: float                 # Hub height in meters
    rated_power_kw: float               # Rated (nameplate) power
    cut_in_speed_ms: float = 3.0        # Cut-in wind speed (m/s)
    rated_speed_ms: float = 12.0        # Speed at which rated power is reached
    cut_out_speed_ms: float = 25.0      # Cut-out speed (storm shutdown)
    re_cut_in_speed_ms: float = 20.0    # Re-cut-in speed after cut-out
    air_density_ref: float = 1.225      # Reference air density (kg/m³, sea level)
    # Power curve table: list of (wind_speed_ms, power_kw) tuples
    # If empty, uses Betz-limit approximation
    power_curve: list[tuple[float, float]] = field(default_factory=list)
    wake_derating: float = 1.0          # Wake effect multiplier (0.0–1.0)

    _current_power_kw: float = field(default=0.0, init=False, repr=False)
    _current_wind_speed_ms: float = field(default=0.0, init=False, repr=False)
    _mode: TurbineMode = field(default=TurbineMode.PARKED, init=False, repr=False)
    _curtailment_limit_kw: float | None = field(default=None, init=False, repr=False)
    _total_energy_kwh: float = field(default=0.0, init=False, repr=False)
    _above_cutout: bool = field(default=False, init=False, repr=False)

    # Betz limit constant (theoretical maximum extraction fraction)
    BETZ_LIMIT: ClassVar[float] = 16.0 / 27.0

    @property
    def rotor_area_m2(self) -> float:
        return math.pi * (self.rotor_diameter_m / 2.0) ** 2

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
    def mode(self) -> TurbineMode:
        return self._mode

    def _lookup_power_curve(self, wind_speed_ms: float) -> float:
        """Interpolate the power curve at the given wind speed."""
        if not self.power_curve:
            return self._betz_power_kw(wind_speed_ms)

        # Sort curve by wind speed
        curve = sorted(self.power_curve, key=lambda x: x[0])
        if wind_speed_ms <= curve[0][0]:
            return 0.0
        if wind_speed_ms >= curve[-1][0]:
            return curve[-1][1]

        # Linear interpolation
        for i in range(1, len(curve)):
            v0, p0 = curve[i - 1]
            v1, p1 = curve[i]
            if v0 <= wind_speed_ms <= v1:
                frac = (wind_speed_ms - v0) / (v1 - v0)
                return p0 + frac * (p1 - p0)
        return 0.0

    def _betz_power_kw(self, wind_speed_ms: float, air_density: float = 1.225) -> float:
        """
        Compute theoretical power output using Betz limit approximation.

        P = ½ * ρ * A * Cp * v³

        With a mechanical/electrical efficiency factor of ~0.45 (below Betz limit).
        """
        cp = 0.45  # Typical real-world power coefficient
        p_watts = 0.5 * air_density * self.rotor_area_m2 * cp * wind_speed_ms ** 3
        return min(self.rated_power_kw, p_watts / 1000.0)

    def _correct_air_density(self, wind_speed_ms: float, air_density: float) -> float:
        """Correct wind speed to equivalent speed at reference density."""
        if air_density <= 0 or self.air_density_ref <= 0:
            return wind_speed_ms
        # v_equiv = v_actual * (ρ_actual / ρ_ref)^(1/3)
        return wind_speed_ms * (air_density / self.air_density_ref) ** (1.0 / 3.0)

    @staticmethod
    def estimate_hub_wind_speed(
        reference_speed_ms: float,
        reference_height_m: float,
        hub_height_m: float,
        roughness_length_m: float = 0.03,
    ) -> float:
        """
        Extrapolate wind speed to hub height using the log-law wind profile.

        v_hub / v_ref = ln(z_hub / z_0) / ln(z_ref / z_0)
        """
        if reference_height_m <= roughness_length_m or hub_height_m <= roughness_length_m:
            return reference_speed_ms
        ratio = math.log(hub_height_m / roughness_length_m) / math.log(
            reference_height_m / roughness_length_m
        )
        return reference_speed_ms * ratio

    def update(
        self,
        wind_speed_ms: float,
        air_density: float = 1.225,
        duration_hours: float = 0.25,
    ) -> float:
        """
        Update turbine state for a given wind speed measurement.

        wind_speed_ms should be at hub height. Returns AC power output in kW.
        """
        self._current_wind_speed_ms = wind_speed_ms

        # Hysteresis for cut-out (re-cut-in at lower speed)
        if self._above_cutout:
            if wind_speed_ms <= self.re_cut_in_speed_ms:
                self._above_cutout = False
        if wind_speed_ms >= self.cut_out_speed_ms:
            self._above_cutout = True

        if self._above_cutout or wind_speed_ms < self.cut_in_speed_ms:
            self._current_power_kw = 0.0
            self._mode = TurbineMode.PARKED
        elif self._mode == TurbineMode.FAULT or self._mode == TurbineMode.MAINTENANCE:
            self._current_power_kw = 0.0
        else:
            # Air density correction
            corrected_speed = self._correct_air_density(wind_speed_ms, air_density)
            power_kw = self._lookup_power_curve(corrected_speed)
            power_kw *= self.wake_derating  # Apply wake losses

            if self._curtailment_limit_kw is not None and power_kw > self._curtailment_limit_kw:
                self._mode = TurbineMode.CURTAILED
                self._current_power_kw = self._curtailment_limit_kw
            else:
                self._mode = TurbineMode.PRODUCING
                self._current_power_kw = min(power_kw, self.rated_power_kw)

        self._total_energy_kwh += self._current_power_kw * duration_hours
        return self._current_power_kw

    def curtail(self, limit_kw: float) -> None:
        """Apply a power curtailment limit."""
        self._curtailment_limit_kw = max(0.0, limit_kw)

    def uncurtail(self) -> None:
        """Remove curtailment."""
        self._curtailment_limit_kw = None

    def set_fault(self) -> None:
        self._mode = TurbineMode.FAULT
        self._current_power_kw = 0.0

    def clear_fault(self) -> None:
        if self._mode == TurbineMode.FAULT:
            self._mode = TurbineMode.PARKED

    @property
    def total_energy_mwh(self) -> float:
        return self._total_energy_kwh / 1000.0

    def capacity_factor(self, period_hours: float) -> float:
        """Compute capacity factor over the given period."""
        if period_hours <= 0 or self.rated_power_kw <= 0:
            return 0.0
        max_energy = self.rated_power_kw * period_hours
        return self._total_energy_kwh / max_energy

    def available_curtailment_mw(self) -> float:
        """How much power could be curtailed if needed (for ancillary services)."""
        return max(0.0, self._current_power_kw / 1000.0)

    @classmethod
    def create_iec_class_iiia(
        cls, asset_id: str, rotor_diameter_m: float, hub_height_m: float
    ) -> "WindTurbineAsset":
        """
        Create a turbine with a representative IEC Class III-A power curve.

        Class III-A: 7.5 m/s average wind speed, low-wind optimized.
        """
        rated_kw = 0.5 * 1.225 * math.pi * (rotor_diameter_m / 2) ** 2 * 0.45 * 11.0 ** 3 / 1000.0
        # Simplified IEC III-A curve
        curve = [
            (0, 0), (1, 0), (2, 0), (3, 0),
            (4, rated_kw * 0.014), (5, rated_kw * 0.05),
            (6, rated_kw * 0.11), (7, rated_kw * 0.21),
            (8, rated_kw * 0.35), (9, rated_kw * 0.54),
            (10, rated_kw * 0.72), (11, rated_kw * 0.89),
            (12, rated_kw * 0.97), (13, rated_kw * 1.0),
            (14, rated_kw * 1.0), (25, rated_kw * 1.0),
        ]
        return cls(
            asset_id=asset_id,
            rotor_diameter_m=rotor_diameter_m,
            hub_height_m=hub_height_m,
            rated_power_kw=rated_kw,
            cut_in_speed_ms=3.0,
            rated_speed_ms=13.0,
            cut_out_speed_ms=25.0,
            power_curve=curve,
        )

    def __repr__(self) -> str:
        return (
            f"WindTurbineAsset(id={self.asset_id!r}, "
            f"rated={self.rated_power_kw:.0f}kW, "
            f"wind={self._current_wind_speed_ms:.1f}m/s, "
            f"power={self._current_power_kw:.1f}kW, mode={self._mode.value})"
        )
