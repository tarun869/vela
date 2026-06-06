"""Kalman filter state estimator for power output and SOC estimation."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KalmanState:
    """State vector and covariance for a 1D Kalman filter."""
    x: float = 0.0             # State estimate
    P: float = 1.0             # Estimate covariance
    Q: float = 0.001           # Process noise covariance
    R: float = 0.1             # Measurement noise covariance

    def predict(self, F: float = 1.0, B: float = 0.0, u: float = 0.0) -> None:
        """
        Kalman prediction step.

        x_k|k-1 = F * x_k-1|k-1 + B * u
        P_k|k-1 = F * P * F^T + Q
        """
        self.x = F * self.x + B * u
        self.P = F * self.P * F + self.Q

    def update(self, z: float, H: float = 1.0) -> float:
        """
        Kalman update step.

        Innovation: y = z - H * x
        Innovation covariance: S = H * P * H + R
        Kalman gain: K = P * H / S
        State update: x = x + K * y
        Covariance update: P = (I - K * H) * P
        Returns the residual (innovation).
        """
        innovation = z - H * self.x
        S = H * self.P * H + self.R
        K = self.P * H / S
        self.x = self.x + K * innovation
        self.P = (1.0 - K * H) * self.P
        return innovation


@dataclass
class KalmanState2D:
    """2D Kalman filter state for tracking (position, velocity) or (SOC, power)."""
    x: list[float] = field(default_factory=lambda: [0.0, 0.0])   # State vector [x0, x1]
    P: list[list[float]] = field(
        default_factory=lambda: [[1.0, 0.0], [0.0, 1.0]]          # 2x2 covariance
    )
    Q: list[list[float]] = field(
        default_factory=lambda: [[0.001, 0.0], [0.0, 0.001]]
    )
    R: float = 0.1              # Scalar measurement noise

    @staticmethod
    def _matmul2(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
        return [
            [A[0][0]*B[0][0] + A[0][1]*B[1][0], A[0][0]*B[0][1] + A[0][1]*B[1][1]],
            [A[1][0]*B[0][0] + A[1][1]*B[1][0], A[1][0]*B[0][1] + A[1][1]*B[1][1]],
        ]

    @staticmethod
    def _matadd2(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
        return [
            [A[0][0]+B[0][0], A[0][1]+B[0][1]],
            [A[1][0]+B[1][0], A[1][1]+B[1][1]],
        ]

    def predict(self, F: list[list[float]]) -> None:
        """Predict step: x = F*x, P = F*P*F^T + Q."""
        x0 = F[0][0]*self.x[0] + F[0][1]*self.x[1]
        x1 = F[1][0]*self.x[0] + F[1][1]*self.x[1]
        self.x = [x0, x1]
        FP = self._matmul2(F, self.P)
        FT = [[F[0][0], F[1][0]], [F[0][1], F[1][1]]]  # F transposed
        FPFT = self._matmul2(FP, FT)
        self.P = self._matadd2(FPFT, self.Q)

    def update(self, z: float, H: list[float] = None) -> None:
        """Update step with scalar measurement."""
        if H is None:
            H = [1.0, 0.0]
        # Innovation: y = z - H*x
        Hx = H[0]*self.x[0] + H[1]*self.x[1]
        y = z - Hx
        # Innovation covariance: S = H*P*H^T + R
        HP = [H[0]*self.P[0][0]+H[1]*self.P[1][0], H[0]*self.P[0][1]+H[1]*self.P[1][1]]
        S = HP[0]*H[0] + HP[1]*H[1] + self.R
        # Kalman gain: K = P*H^T / S
        PH = [self.P[0][0]*H[0]+self.P[0][1]*H[1], self.P[1][0]*H[0]+self.P[1][1]*H[1]]
        K = [PH[0]/S, PH[1]/S]
        # Update state
        self.x[0] += K[0]*y
        self.x[1] += K[1]*y
        # Update covariance: P = (I - K*H)*P
        KH = [[K[0]*H[0], K[0]*H[1]], [K[1]*H[0], K[1]*H[1]]]
        I_KH = [[1-KH[0][0], -KH[0][1]], [-KH[1][0], 1-KH[1][1]]]
        self.P = self._matmul2(I_KH, self.P)


class BatterySOCEstimator:
    """
    Kalman filter-based SOC estimator for a battery energy storage system.

    State vector: [SOC, drift]
    Measurement: voltage or current-integrated SOC

    The estimator fuses:
    1. Coulomb counting (current integration) — prediction step
    2. Voltage-based SOC lookup — measurement update

    Reference: Plett (2004) "Extended Kalman filtering for battery management systems"
    """

    def __init__(
        self,
        initial_soc: float = 0.5,
        capacity_mwh: float = 4.0,
        process_noise: float = 1e-4,
        measurement_noise: float = 0.01,
    ) -> None:
        self._state = KalmanState(
            x=initial_soc,
            P=0.01,         # Initial SOC uncertainty
            Q=process_noise,
            R=measurement_noise,
        )
        self.capacity_mwh = capacity_mwh
        self._last_soc = initial_soc

    @property
    def estimated_soc(self) -> float:
        return max(0.0, min(1.0, self._state.x))

    def predict_coulomb_counting(
        self, power_mw: float, duration_hours: float, efficiency: float = 0.92
    ) -> float:
        """
        Prediction step using current integration (Coulomb counting).

        For charging: SOC increases by (P * η * dt) / capacity
        For discharging: SOC decreases by (P * dt) / (capacity * η)
        """
        if power_mw > 0:  # Discharging
            delta_soc = -(power_mw * duration_hours) / (self.capacity_mwh * efficiency)
        else:  # Charging (power_mw < 0 convention) — or positive with sign convention
            delta_soc = -(power_mw * duration_hours * efficiency) / self.capacity_mwh

        # State transition: SOC_k+1 = SOC_k + delta_soc
        F = 1.0
        B = 1.0
        self._state.predict(F=F, B=B, u=delta_soc)
        self._state.x = max(0.0, min(1.0, self._state.x))
        return self.estimated_soc

    def update_from_voltage(
        self,
        voltage_v: float,
        soc_from_voltage: float | None = None,
    ) -> float:
        """
        Measurement update step using open-circuit voltage.

        If soc_from_voltage is provided, uses it directly.
        Otherwise, uses a simplified linear OCV→SOC relationship.
        """
        if soc_from_voltage is not None:
            z = soc_from_voltage
        else:
            # Simplified OCV model for LFP: V_oc = 3.2 + 0.4 * SOC (per cell)
            # Single-cell nominal: 3.2V (empty) to 3.6V (full)
            z = max(0.0, min(1.0, (voltage_v - 3.2) / 0.4))
        self._state.update(z, H=1.0)
        self._state.x = max(0.0, min(1.0, self._state.x))
        return self.estimated_soc

    def update_from_direct_measurement(self, measured_soc: float) -> float:
        """
        Update from a direct SOC measurement (e.g., BMS readout).
        """
        self._state.update(measured_soc, H=1.0)
        self._state.x = max(0.0, min(1.0, self._state.x))
        return self.estimated_soc

    @property
    def uncertainty(self) -> float:
        """1-sigma SOC uncertainty from filter covariance."""
        return math.sqrt(abs(self._state.P))


class PowerOutputEstimator:
    """
    Kalman filter for smoothing noisy power measurements from metering systems.

    State vector: [power_mw, rate_of_change_mw_per_s]
    """

    def __init__(
        self,
        initial_power_mw: float = 0.0,
        process_noise_power: float = 0.01,
        process_noise_rate: float = 0.001,
        measurement_noise: float = 0.05,
        dt_seconds: float = 5.0,
    ) -> None:
        self._dt = dt_seconds
        self._state = KalmanState2D(
            x=[initial_power_mw, 0.0],
            P=[[1.0, 0.0], [0.0, 0.1]],
            Q=[[process_noise_power, 0.0], [0.0, process_noise_rate]],
            R=measurement_noise,
        )

    @property
    def estimated_power_mw(self) -> float:
        return self._state.x[0]

    @property
    def estimated_ramp_rate_mw_per_s(self) -> float:
        return self._state.x[1]

    def update(self, measured_power_mw: float) -> float:
        """
        Update the power estimate with a new measurement.

        Returns the filtered power estimate in MW.
        """
        # State transition: [power, rate] → [power + rate*dt, rate]
        F = [[1.0, self._dt], [0.0, 1.0]]
        self._state.predict(F)
        self._state.update(measured_power_mw, H=[1.0, 0.0])
        return self.estimated_power_mw


class GridFrequencyEstimator:
    """
    Kalman filter for grid frequency tracking with noise rejection.

    Used to generate clean frequency signals for droop control
    and synthetic inertia response, filtering out measurement noise
    from PMU (phasor measurement unit) data.
    """

    def __init__(
        self,
        nominal_hz: float = 60.0,
        process_noise: float = 1e-6,
        measurement_noise: float = 1e-4,
    ) -> None:
        self._state = KalmanState(
            x=nominal_hz,
            P=1e-4,
            Q=process_noise,
            R=measurement_noise,
        )
        self.nominal_hz = nominal_hz

    @property
    def estimated_frequency(self) -> float:
        return self._state.x

    @property
    def frequency_deviation(self) -> float:
        return self._state.x - self.nominal_hz

    def update(self, measured_hz: float) -> float:
        """Update filter with a raw frequency measurement."""
        self._state.predict(F=1.0)
        self._state.update(measured_hz, H=1.0)
        return self.estimated_frequency

    @property
    def uncertainty_hz(self) -> float:
        return math.sqrt(abs(self._state.P))
