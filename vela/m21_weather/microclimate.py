"""
Microclimate correction for VPP site-specific weather adjustments.

Corrects NWP grid-level forecasts for local terrain, urban heat island,
and coastal effects that affect solar and wind generation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class SiteCharacteristics:
    site_id: str
    latitude: float
    longitude: float
    altitude_m: float
    terrain_type: str        # "flat", "coastal", "urban", "mountain", "valley"
    surface_roughness: float # z0 in meters (0.001=water, 0.03=grass, 0.5=suburbs)
    urban_heat_island_c: float = 0.0   # UHI temperature offset (°C)
    horizon_angle_deg: float = 0.0     # Terrain-induced horizon obstruction
    local_albedo: float = 0.2          # Local surface reflectance


class MicroclimatCorrector:
    """
    Applies site-specific corrections to NWP weather forecasts.
    """

    def __init__(self, site: SiteCharacteristics) -> None:
        self.site = site

    def correct_temperature(self, nwp_temp_c: np.ndarray) -> np.ndarray:
        """Apply UHI and altitude corrections to NWP temperature."""
        altitude_correction = -0.0065 * self.site.altitude_m  # -6.5°C / 1000m
        return nwp_temp_c + self.site.urban_heat_island_c + altitude_correction

    def correct_wind_speed(
        self,
        nwp_wind_ms: np.ndarray,
        nwp_height_m: float = 10.0,
        target_height_m: float = 80.0,
    ) -> np.ndarray:
        """
        Correct NWP wind to hub height using local roughness length.
        """
        z0 = self.site.surface_roughness
        if z0 <= 0 or nwp_height_m <= z0 or target_height_m <= z0:
            return nwp_wind_ms.copy()

        correction = np.log(target_height_m / z0) / np.log(nwp_height_m / z0)
        return nwp_wind_ms * correction

    def correct_ghi(
        self,
        nwp_ghi: np.ndarray,
        hour_of_day: np.ndarray,
    ) -> np.ndarray:
        """
        Apply terrain shading correction to GHI.

        Applies horizon obstruction mask for morning and evening hours.
        """
        corrected = nwp_ghi.copy()
        horizon = self.site.horizon_angle_deg

        if horizon > 0:
            # Approximate: suppress GHI in early morning / late evening
            # based on horizon obstruction angle
            obstruct_hours = horizon / 15.0  # ~1 hour per 15 degrees
            morning_mask = hour_of_day < (6 + obstruct_hours)
            evening_mask = hour_of_day > (18 - obstruct_hours)
            corrected[morning_mask] = 0.0
            corrected[evening_mask] = 0.0

        return corrected

    def apply_all_corrections(
        self,
        temperature_c: List[float],
        wind_speed_ms: List[float],
        ghi_wm2: List[float],
        hours: Optional[List[int]] = None,
    ) -> Dict[str, np.ndarray]:
        """Apply all microclimate corrections and return corrected arrays."""
        temp = np.array(temperature_c)
        wind = np.array(wind_speed_ms)
        ghi = np.array(ghi_wm2)
        hour_arr = np.array(hours) if hours else np.arange(len(temp)) % 24

        return {
            "temperature_c": self.correct_temperature(temp),
            "wind_speed_ms": self.correct_wind_speed(wind),
            "ghi_wm2": self.correct_ghi(ghi, hour_arr),
        }
