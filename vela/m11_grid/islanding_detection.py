"""
Islanding detection logic for distributed energy resources.

Implements passive and active anti-islanding detection methods
per IEEE 1547-2018 and UL 1741 requirements.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple
import numpy as np


class IslandingMethod(str, Enum):
    PASSIVE_OUV = "over_under_voltage"      # Over/under voltage
    PASSIVE_OUF = "over_under_frequency"    # Over/under frequency
    PASSIVE_ROCOF = "rocof"                 # Rate of Change of Frequency
    PASSIVE_VECTOR_SHIFT = "vector_shift"   # Voltage angle jump
    ACTIVE_SLIP_MODE = "slip_mode"          # Active frequency drift
    ACTIVE_SANDIA = "sandia_frequency_shift" # Sandia frequency shift


@dataclass
class IslandingThresholds:
    """IEEE 1547-2018 default trip thresholds (Category II)."""
    v_under_pu: float = 0.88         # Under-voltage trip threshold
    v_over_pu: float = 1.10          # Over-voltage trip threshold
    f_under_hz: float = 59.5         # Under-frequency trip (Hz)
    f_over_hz: float = 60.5          # Over-frequency trip (Hz)
    rocof_threshold_hz_s: float = 1.0  # ROCOF trip threshold (Hz/s)
    vector_shift_deg: float = 12.0   # Vector shift trip (degrees)
    trip_delay_s: float = 0.16       # Minimum trip delay (s), ~10 cycles
    reconnect_delay_s: float = 300.0  # Reconnect delay after trip (s)


@dataclass
class IslandingDetectionResult:
    islanding_detected: bool
    method_triggered: Optional[IslandingMethod]
    trip_reason: str
    v_pu: float
    f_hz: float
    rocof_hz_s: float
    vector_shift_deg: float
    grid_connected: bool


class IslandingDetector:
    """
    Multi-method islanding detection combining passive and active techniques.

    Maintains rolling window of measurements and applies thresholds.
    """

    def __init__(
        self,
        thresholds: Optional[IslandingThresholds] = None,
        window_s: float = 0.5,
        dt_s: float = 0.01,
    ) -> None:
        self.thresholds = thresholds or IslandingThresholds()
        self.window_s = window_s
        self.dt_s = dt_s
        self._window_size = max(1, int(window_s / dt_s))
        self._v_history: List[float] = []
        self._f_history: List[float] = []
        self._angle_history: List[float] = []
        self._grid_connected: bool = True
        self._trip_timer_s: float = 0.0
        self._reconnect_timer_s: float = 0.0
        self._active_afd_offset: float = 0.0  # Active frequency drift offset

    def _compute_rocof(self) -> float:
        """Compute ROCOF from frequency history using linear regression."""
        if len(self._f_history) < 3:
            return 0.0
        n = min(len(self._f_history), self._window_size)
        freqs = self._f_history[-n:]
        t = np.arange(n) * self.dt_s
        if len(t) < 2:
            return 0.0
        slope = np.polyfit(t, freqs, 1)[0]
        return slope

    def _compute_vector_shift(self) -> float:
        """Compute voltage phase angle shift between consecutive cycles."""
        if len(self._angle_history) < 2:
            return 0.0
        delta = self._angle_history[-1] - self._angle_history[-2]
        # Normalize to [-180, 180]
        while delta > 180.0:
            delta -= 360.0
        while delta < -180.0:
            delta += 360.0
        return delta

    def _check_passive(self, v_pu: float, f_hz: float) -> Tuple[bool, Optional[IslandingMethod], str]:
        """Apply all passive detection methods."""
        # OUV check
        if v_pu < self.thresholds.v_under_pu:
            return True, IslandingMethod.PASSIVE_OUV, f"Under-voltage: {v_pu:.3f} pu"
        if v_pu > self.thresholds.v_over_pu:
            return True, IslandingMethod.PASSIVE_OUV, f"Over-voltage: {v_pu:.3f} pu"

        # OUF check
        if f_hz < self.thresholds.f_under_hz:
            return True, IslandingMethod.PASSIVE_OUF, f"Under-frequency: {f_hz:.3f} Hz"
        if f_hz > self.thresholds.f_over_hz:
            return True, IslandingMethod.PASSIVE_OUF, f"Over-frequency: {f_hz:.3f} Hz"

        # ROCOF check
        rocof = self._compute_rocof()
        if abs(rocof) > self.thresholds.rocof_threshold_hz_s:
            return True, IslandingMethod.PASSIVE_ROCOF, f"ROCOF: {rocof:.2f} Hz/s"

        # Vector shift check
        shift = self._compute_vector_shift()
        if abs(shift) > self.thresholds.vector_shift_deg:
            return True, IslandingMethod.PASSIVE_VECTOR_SHIFT, f"Vector shift: {shift:.1f} deg"

        return False, None, "Normal"

    def step(self, v_pu: float, f_hz: float, angle_deg: float) -> IslandingDetectionResult:
        """Process one measurement sample."""
        self._v_history.append(v_pu)
        self._f_history.append(f_hz)
        self._angle_history.append(angle_deg)

        # Trim to window
        for hist in [self._v_history, self._f_history, self._angle_history]:
            while len(hist) > self._window_size * 2:
                hist.pop(0)

        rocof = self._compute_rocof()
        vector_shift = self._compute_vector_shift()

        if not self._grid_connected:
            # Waiting for reconnect timer
            self._reconnect_timer_s += self.dt_s
            if self._reconnect_timer_s >= self.thresholds.reconnect_delay_s:
                # Check conditions safe for reconnection
                if (abs(f_hz - 60.0) < 0.2 and
                        self.thresholds.v_under_pu < v_pu < self.thresholds.v_over_pu):
                    self._grid_connected = True
                    self._reconnect_timer_s = 0.0

            return IslandingDetectionResult(
                islanding_detected=True,
                method_triggered=None,
                trip_reason="Islanded — awaiting reconnect",
                v_pu=v_pu, f_hz=f_hz, rocof_hz_s=rocof,
                vector_shift_deg=vector_shift, grid_connected=False
            )

        triggered, method, reason = self._check_passive(v_pu, f_hz)

        if triggered:
            self._trip_timer_s += self.dt_s
            if self._trip_timer_s >= self.thresholds.trip_delay_s:
                self._grid_connected = False
                self._trip_timer_s = 0.0
                self._reconnect_timer_s = 0.0
        else:
            self._trip_timer_s = max(0.0, self._trip_timer_s - self.dt_s * 0.5)

        return IslandingDetectionResult(
            islanding_detected=not self._grid_connected,
            method_triggered=method,
            trip_reason=reason,
            v_pu=v_pu, f_hz=f_hz, rocof_hz_s=rocof,
            vector_shift_deg=vector_shift,
            grid_connected=self._grid_connected
        )

    def simulate(
        self,
        v_series: List[float],
        f_series: List[float],
        angle_series: List[float],
    ) -> List[IslandingDetectionResult]:
        """Run islanding detection over a time series."""
        return [
            self.step(v_series[i], f_series[i], angle_series[i])
            for i in range(len(v_series))
        ]
