"""
Wind speed and direction processing for VPP wind generation forecasting.

Implements:
  - Wind speed vertical extrapolation (power law, log law)
  - Wind turbine power curve modeling
  - Weibull distribution fitting
  - Wind ramp event detection
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np
from scipy import stats


@dataclass
class WindTurbineSpec:
    turbine_id: str
    rated_power_kw: float
    rotor_diameter_m: float
    hub_height_m: float
    cut_in_ms: float = 3.0       # Wind speed at which generation starts
    rated_ms: float = 12.0       # Wind speed at rated power
    cut_out_ms: float = 25.0     # Wind speed at which turbine shuts down


@dataclass
class WindRampEvent:
    start_idx: int
    end_idx: int
    ramp_mw: float           # Magnitude of power change (MW)
    duration_h: float
    ramp_rate_mw_h: float    # MW per hour
    ramp_type: str           # "up" or "down"


class WindModel:
    """
    Wind speed processing and power generation model.
    """

    def __init__(self, turbine: WindTurbineSpec) -> None:
        self.turbine = turbine

    def extrapolate_wind_speed(
        self,
        v_ref: float,
        h_ref: float,
        h_target: float,
        alpha: float = 1/7,
        roughness_length_m: float = 0.03,
        method: str = "power_law",
    ) -> float:
        """
        Extrapolate wind speed from measurement height to hub height.

        Methods:
          - "power_law": v(h) = v_ref * (h/h_ref)^alpha
          - "log_law": v(h) = v_ref * ln(h/z0) / ln(h_ref/z0)
        """
        if method == "power_law":
            return v_ref * (h_target / h_ref) ** alpha
        elif method == "log_law":
            if h_ref <= roughness_length_m or h_target <= roughness_length_m:
                return v_ref
            return v_ref * math.log(h_target / roughness_length_m) / math.log(h_ref / roughness_length_m)
        return v_ref

    def power_curve(self, wind_speed_ms: float) -> float:
        """
        Compute turbine output power from wind speed using IEC power curve.

        Returns:
            Power output (kW).
        """
        v = wind_speed_ms
        t = self.turbine

        if v < t.cut_in_ms or v > t.cut_out_ms:
            return 0.0
        elif v >= t.rated_ms:
            return t.rated_power_kw
        else:
            # Cubic interpolation between cut-in and rated
            frac = (v - t.cut_in_ms) / (t.rated_ms - t.cut_in_ms)
            return t.rated_power_kw * frac ** 3

    def capacity_factor(self, wind_series_ms: List[float]) -> float:
        """Compute capacity factor from a wind speed time series."""
        powers = [self.power_curve(v) for v in wind_series_ms]
        return sum(powers) / (self.turbine.rated_power_kw * len(powers)) if powers else 0.0

    def fit_weibull(self, wind_series_ms: List[float]) -> Tuple[float, float]:
        """
        Fit Weibull distribution to wind speed data.

        Returns:
            (shape_k, scale_lambda) Weibull parameters.
        """
        data = np.array([v for v in wind_series_ms if v > 0])
        if len(data) < 10:
            return 2.0, 7.0  # Default Rayleigh
        shape, loc, scale = stats.weibull_min.fit(data, floc=0)
        return float(shape), float(scale)

    def detect_ramp_events(
        self,
        power_series_kw: List[float],
        dt_h: float = 1.0,
        threshold_kw_h: float = None,
    ) -> List[WindRampEvent]:
        """
        Detect wind power ramp events.

        A ramp event is a rapid change in wind power output > threshold.

        Args:
            power_series_kw: Wind power time series (kW).
            dt_h: Time step (hours).
            threshold_kw_h: Ramp rate threshold (kW/h). Default: 20% rated/h.

        Returns:
            List of WindRampEvent objects.
        """
        threshold = threshold_kw_h or (self.turbine.rated_power_kw * 0.20)
        n = len(power_series_kw)
        arr = np.array(power_series_kw)
        ramps: List[WindRampEvent] = []

        i = 0
        while i < n - 1:
            rate = (arr[i+1] - arr[i]) / dt_h  # kW/h
            if abs(rate) >= threshold:
                # Find ramp end
                j = i + 1
                while j < n - 1 and abs((arr[j+1] - arr[j]) / dt_h) >= threshold * 0.5:
                    j += 1
                total_change = arr[j] - arr[i]
                duration = (j - i) * dt_h
                ramps.append(WindRampEvent(
                    start_idx=i, end_idx=j,
                    ramp_mw=total_change / 1000.0,
                    duration_h=duration,
                    ramp_rate_mw_h=total_change / 1000.0 / max(duration, dt_h),
                    ramp_type="up" if total_change > 0 else "down",
                ))
                i = j + 1
            else:
                i += 1

        return ramps

    def expected_annual_energy(
        self, k: float, scale: float, n_hours: int = 8760
    ) -> float:
        """
        Compute expected annual energy from Weibull wind distribution.

        Returns:
            Expected annual energy production (kWh).
        """
        # Sample Weibull distribution
        rng = np.random.default_rng(42)
        speeds = scale * rng.weibull(k, n_hours)
        powers = np.array([self.power_curve(v) for v in speeds])
        return float(powers.sum())
