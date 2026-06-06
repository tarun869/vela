"""
Extreme weather event detection for VPP grid risk management.

Identifies heat waves, cold snaps, severe storms, and renewable generation
droughts that impact VPP dispatch and grid stability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class ExtremeEvent:
    event_type: str       # "heat_wave", "cold_snap", "storm", "solar_drought", "wind_drought"
    start_idx: int
    end_idx: int
    duration_h: float
    severity: str         # "moderate", "severe", "extreme"
    peak_value: float
    description: str
    grid_impact: str      # "high_load", "low_generation", "both"


class ExtremeWeatherDetector:
    """
    Detects and classifies extreme weather events from weather time series.
    """

    def detect_heat_wave(
        self,
        temperature_c: List[float],
        dt_h: float = 1.0,
        hot_threshold_c: float = 35.0,
        min_duration_h: float = 48.0,
    ) -> List[ExtremeEvent]:
        """Detect heat wave events (sustained high temperature)."""
        arr = np.array(temperature_c)
        events: List[ExtremeEvent] = []
        above = arr >= hot_threshold_c
        in_event = False
        start = 0

        for i, hot in enumerate(above):
            if hot and not in_event:
                start = i
                in_event = True
            elif not hot and in_event:
                duration = (i - start) * dt_h
                if duration >= min_duration_h:
                    peak = float(arr[start:i].max())
                    sev = "extreme" if peak > 42 else "severe" if peak > 38 else "moderate"
                    events.append(ExtremeEvent(
                        event_type="heat_wave",
                        start_idx=start, end_idx=i,
                        duration_h=duration, severity=sev,
                        peak_value=peak,
                        description=f"Heat wave: peak {peak:.1f}°C for {duration:.0f}h",
                        grid_impact="high_load",
                    ))
                in_event = False

        return events

    def detect_cold_snap(
        self,
        temperature_c: List[float],
        dt_h: float = 1.0,
        cold_threshold_c: float = -5.0,
        min_duration_h: float = 24.0,
    ) -> List[ExtremeEvent]:
        """Detect cold snap events."""
        arr = np.array(temperature_c)
        events: List[ExtremeEvent] = []
        cold = arr <= cold_threshold_c
        in_event = False
        start = 0

        for i, c in enumerate(cold):
            if c and not in_event:
                start = i
                in_event = True
            elif not c and in_event:
                duration = (i - start) * dt_h
                if duration >= min_duration_h:
                    peak = float(arr[start:i].min())
                    sev = "extreme" if peak < -20 else "severe" if peak < -10 else "moderate"
                    events.append(ExtremeEvent(
                        event_type="cold_snap",
                        start_idx=start, end_idx=i,
                        duration_h=duration, severity=sev,
                        peak_value=peak,
                        description=f"Cold snap: min {peak:.1f}°C for {duration:.0f}h",
                        grid_impact="high_load",
                    ))
                in_event = False

        return events

    def detect_solar_drought(
        self,
        ghi_series: List[float],
        dt_h: float = 1.0,
        threshold_fraction: float = 0.15,
        min_duration_h: float = 72.0,
    ) -> List[ExtremeEvent]:
        """Detect prolonged low-solar generation periods."""
        arr = np.array(ghi_series)
        mean_ghi = arr.mean()
        threshold = mean_ghi * threshold_fraction
        drought = arr <= threshold
        events: List[ExtremeEvent] = []
        in_event = False
        start = 0

        for i, d in enumerate(drought):
            if d and not in_event:
                start = i
                in_event = True
            elif not d and in_event:
                duration = (i - start) * dt_h
                if duration >= min_duration_h:
                    min_ghi = float(arr[start:i].mean())
                    sev = "extreme" if duration > 168 else "severe" if duration > 96 else "moderate"
                    events.append(ExtremeEvent(
                        event_type="solar_drought",
                        start_idx=start, end_idx=i,
                        duration_h=duration, severity=sev,
                        peak_value=min_ghi,
                        description=f"Solar drought: avg {min_ghi:.0f} W/m2 for {duration:.0f}h",
                        grid_impact="low_generation",
                    ))
                in_event = False

        return events

    def analyze_all(
        self,
        temperature_c: List[float],
        ghi_series: List[float],
        wind_speed_ms: List[float],
        dt_h: float = 1.0,
    ) -> Dict[str, List[ExtremeEvent]]:
        """Run all extreme event detectors."""
        return {
            "heat_waves": self.detect_heat_wave(temperature_c, dt_h),
            "cold_snaps": self.detect_cold_snap(temperature_c, dt_h),
            "solar_droughts": self.detect_solar_drought(ghi_series, dt_h),
        }
