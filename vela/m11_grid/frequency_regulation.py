"""
Primary and secondary frequency response for grid-connected VPP resources.

Implements:
  - Primary frequency response (droop control, governor response)
  - Secondary frequency response (AGC / Automatic Generation Control)
  - ROCOF (Rate of Change of Frequency) detection
  - Frequency deviation metrics per NERC BAL-001 / ENTSO-E Grid Code
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class FrequencyRegParams:
    """Parameters for a frequency-regulating resource."""
    resource_id: str
    p_rated_mw: float           # Rated power (MW)
    droop_percent: float = 5.0  # Droop setting (%), standard is 4–5%
    dead_band_hz: float = 0.036 # Primary frequency dead band (Hz), NERC standard
    response_time_s: float = 10.0  # Time to full primary response (s)
    ramp_rate_mw_s: float = 1.0    # Ramp rate (MW/s)
    f_nominal_hz: float = 60.0     # Nominal system frequency (Hz)
    agc_participation: float = 1.0  # AGC participation factor (0–1)


@dataclass
class FrequencyEvent:
    """Record of a frequency deviation event."""
    timestamp_s: float
    f_hz: float
    delta_f_hz: float
    rocof_hz_s: float
    p_primary_mw: float
    p_agc_mw: float
    regulation_state: str   # "normal", "primary_active", "agc_active", "disturbance"


class PrimaryFrequencyResponse:
    """
    Droop-based primary frequency response (governor action).

    Response = P_rated * (delta_f / (droop% * f_nominal)) when |delta_f| > dead_band.
    """

    def __init__(self, params: FrequencyRegParams) -> None:
        self.params = params
        self._p_ref_mw: float = 0.0        # Current power reference (MW)
        self._p_primary_mw: float = 0.0    # Current primary response (MW)
        self._ramp_target_mw: float = 0.0

    def set_reference(self, p_ref_mw: float) -> None:
        self._p_ref_mw = max(0.0, min(p_ref_mw, self.params.p_rated_mw))

    def _droop_response(self, delta_f_hz: float) -> float:
        """Compute droop response power change (MW)."""
        if abs(delta_f_hz) <= self.params.dead_band_hz:
            return 0.0
        # Excess beyond dead band
        db_sign = math.copysign(self.params.dead_band_hz, delta_f_hz)
        delta_f_eff = delta_f_hz - db_sign
        droop_pu = self.params.droop_percent / 100.0
        return -self.params.p_rated_mw * delta_f_eff / (droop_pu * self.params.f_nominal_hz)

    def compute_response(
        self, f_hz: float, dt_s: float = 4.0
    ) -> float:
        """
        Compute and ramp primary response.

        Returns:
            Total dispatch power (p_ref + primary response) in MW.
        """
        delta_f = f_hz - self.params.f_nominal_hz
        target = self._droop_response(delta_f)
        self._ramp_target_mw = target

        # Apply ramp rate limit
        max_delta = self.params.ramp_rate_mw_s * dt_s
        ramp_delta = max(-max_delta, min(max_delta, target - self._p_primary_mw))
        self._p_primary_mw += ramp_delta

        return max(0.0, min(self._p_ref_mw + self._p_primary_mw, self.params.p_rated_mw))

    @property
    def regulation_band_mw(self) -> Tuple[float, float]:
        """Available regulation up/down capability (MW)."""
        reg_up = min(
            self.params.p_rated_mw - self._p_ref_mw,
            self.params.p_rated_mw * self.params.droop_percent / 100.0
        )
        reg_dn = min(
            self._p_ref_mw,
            self.params.p_rated_mw * self.params.droop_percent / 100.0
        )
        return reg_up, reg_dn


class SecondaryFrequencyResponse:
    """
    Automatic Generation Control (AGC) — Area Control Error correction.

    ACE = (Actual_interchange - Scheduled_interchange) + 10 * B * (f - f_nominal)

    where B is the frequency bias (MW/0.1Hz).
    """

    def __init__(
        self,
        b_freq_bias_mw_hz: float,
        ki_mw_per_hz_s: float = 0.1,
    ) -> None:
        self.b_bias = b_freq_bias_mw_hz   # Frequency bias setting
        self.ki = ki_mw_per_hz_s          # Integral gain for ACE correction
        self._ace_integral: float = 0.0
        self._p_agc_mw: float = 0.0

    def compute_ace(
        self, f_hz: float, f_nominal: float, actual_interchange_mw: float, scheduled_interchange_mw: float
    ) -> float:
        """Compute Area Control Error (MW)."""
        delta_f = f_hz - f_nominal
        ace = (actual_interchange_mw - scheduled_interchange_mw) + 10.0 * self.b_bias * delta_f
        return ace

    def agc_signal(self, ace_mw: float, dt_s: float) -> float:
        """
        Compute AGC regulation signal using proportional-integral control.

        Returns:
            AGC power correction signal (MW).
        """
        self._ace_integral += ace_mw * dt_s
        correction = -self.ki * self._ace_integral
        self._p_agc_mw = correction
        return correction

    def reset_integral(self) -> None:
        self._ace_integral = 0.0


class FrequencyRegulator:
    """
    Combined primary + secondary frequency regulator for a VPP resource.
    Tracks frequency events and computes regulation revenue.
    """

    def __init__(
        self,
        params: FrequencyRegParams,
        freq_bias_mw_hz: float = 50.0,
    ) -> None:
        self.params = params
        self.primary = PrimaryFrequencyResponse(params)
        self.secondary = SecondaryFrequencyResponse(freq_bias_mw_hz)
        self._history: List[FrequencyEvent] = []
        self._time_s: float = 0.0

    def step(
        self,
        f_hz: float,
        dt_s: float,
        ace_mw: float = 0.0,
        p_ref_mw: Optional[float] = None,
    ) -> FrequencyEvent:
        """Process one time step of frequency regulation."""
        if p_ref_mw is not None:
            self.primary.set_reference(p_ref_mw)

        delta_f = f_hz - self.params.f_nominal_hz
        rocof = (
            (f_hz - self._history[-1].f_hz) / dt_s
            if self._history else 0.0
        )

        p_primary = self.primary.compute_response(f_hz, dt_s)
        p_agc = self.secondary.agc_signal(ace_mw, dt_s)

        if abs(delta_f) > 0.5:
            state = "disturbance"
        elif abs(delta_f) > self.params.dead_band_hz:
            state = "primary_active"
        elif abs(ace_mw) > 1.0:
            state = "agc_active"
        else:
            state = "normal"

        event = FrequencyEvent(
            timestamp_s=self._time_s,
            f_hz=f_hz,
            delta_f_hz=delta_f,
            rocof_hz_s=rocof,
            p_primary_mw=p_primary,
            p_agc_mw=p_agc,
            regulation_state=state,
        )
        self._history.append(event)
        self._time_s += dt_s
        return event

    def simulate(
        self,
        f_profile_hz: List[float],
        ace_profile_mw: Optional[List[float]],
        dt_s: float = 4.0,
        p_ref_mw: float = 0.5,
    ) -> List[FrequencyEvent]:
        """Run a full frequency regulation simulation."""
        n = len(f_profile_hz)
        ace_profile_mw = ace_profile_mw or [0.0] * n
        self.primary.set_reference(p_ref_mw)
        return [
            self.step(f_profile_hz[i], dt_s, ace_profile_mw[i])
            for i in range(n)
        ]

    def mileage(self) -> float:
        """Regulation mileage: total MW movement over simulation (MW)."""
        if len(self._history) < 2:
            return 0.0
        return sum(
            abs(self._history[i].p_primary_mw - self._history[i-1].p_primary_mw)
            for i in range(1, len(self._history))
        )

    def cps1_score(self) -> float:
        """
        Simplified Control Performance Standard 1 (CPS1) score.
        CPS1 = 200 * (1 - <ACE * delta_f>) / (epsilon1^2)
        """
        if not self._history:
            return 0.0
        products = [e.p_agc_mw * e.delta_f_hz for e in self._history]
        mean_product = sum(products) / len(products)
        epsilon1_sq = (0.025 * self.params.f_nominal_hz) ** 2 / self.params.p_rated_mw
        return max(0.0, 200.0 * (1.0 - mean_product / max(epsilon1_sq, 1e-9)))
