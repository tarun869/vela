"""
Digital twin state synchronization for VPP assets.

Maintains a continuously updated virtual replica of physical assets,
synchronizing real-time telemetry and running predictive models
to anticipate failures and optimize operations.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np


class AssetStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    FAULT = "fault"
    MAINTENANCE = "maintenance"
    SYNCHRONIZING = "synchronizing"


@dataclass
class TelemetryPoint:
    timestamp: float
    tag: str
    value: float
    unit: str
    quality: str     # "good", "uncertain", "bad"


@dataclass
class DigitalTwinState:
    asset_id: str
    status: AssetStatus
    soc_kwh: float
    soc_pct: float
    power_kw: float
    temperature_c: float
    voltage_v: float
    current_a: float
    cycle_count: float
    health_score: float       # 0–100
    last_sync_time: float
    drift_magnitude: float    # Current state vs virtual state deviation
    predicted_fault_hours: Optional[float] = None  # Hours to next predicted fault
    tags: Dict[str, float] = field(default_factory=dict)


class DigitalTwin:
    """
    Digital twin for a battery energy storage asset.

    Maintains physical state estimates using a state observer (Luenberger/Kalman),
    detects drift between virtual and physical states, and supports
    what-if simulation scenarios.
    """

    def __init__(
        self,
        asset_id: str,
        capacity_kwh: float,
        nominal_voltage_v: float = 800.0,
        mass_kg: float = 5000.0,
    ) -> None:
        self.asset_id = asset_id
        self.capacity_kwh = capacity_kwh
        self.nominal_voltage = nominal_voltage_v
        self.mass_kg = mass_kg

        # Virtual state (model-based estimate)
        self._virtual_state = DigitalTwinState(
            asset_id=asset_id,
            status=AssetStatus.OFFLINE,
            soc_kwh=capacity_kwh * 0.5,
            soc_pct=50.0,
            power_kw=0.0,
            temperature_c=25.0,
            voltage_v=nominal_voltage_v,
            current_a=0.0,
            cycle_count=0.0,
            health_score=100.0,
            last_sync_time=time.time(),
            drift_magnitude=0.0,
        )

        self._telemetry_buffer: List[TelemetryPoint] = []
        self._subscribers: Dict[str, List[Callable]] = {}
        self._sync_count: int = 0
        self._observer_gain: float = 0.15   # Kalman-like correction gain

    def ingest_telemetry(self, points: List[TelemetryPoint]) -> None:
        """Ingest new telemetry from the physical asset."""
        self._telemetry_buffer.extend(points)
        if len(self._telemetry_buffer) > 10000:
            self._telemetry_buffer = self._telemetry_buffer[-5000:]

    def sync(self, telemetry: Dict[str, float]) -> DigitalTwinState:
        """
        Synchronize virtual state with measured telemetry.

        Uses a correction gain to blend model prediction with measurement.

        Args:
            telemetry: Dict of tag -> measured value.

        Returns:
            Updated DigitalTwinState.
        """
        measured_soc_kwh = telemetry.get("soc_kwh", self._virtual_state.soc_kwh)
        measured_power = telemetry.get("power_kw", self._virtual_state.power_kw)
        measured_temp = telemetry.get("temperature_c", self._virtual_state.temperature_c)
        measured_voltage = telemetry.get("voltage_v", self._virtual_state.voltage_v)
        measured_current = telemetry.get("current_a", self._virtual_state.current_a)
        measured_cycles = telemetry.get("cycle_count", self._virtual_state.cycle_count)

        # Observer correction: blend virtual and measured
        g = self._observer_gain
        new_soc = (1 - g) * self._virtual_state.soc_kwh + g * measured_soc_kwh
        new_temp = (1 - g) * self._virtual_state.temperature_c + g * measured_temp

        # Compute drift
        drift = abs(new_soc - self._virtual_state.soc_kwh) / max(self.capacity_kwh, 1.0)

        # Health scoring
        health = self._compute_health(measured_temp, measured_cycles, new_soc)

        # Status determination
        status = self._determine_status(measured_power, measured_temp, health)

        self._virtual_state = DigitalTwinState(
            asset_id=self.asset_id,
            status=status,
            soc_kwh=new_soc,
            soc_pct=new_soc / self.capacity_kwh * 100.0,
            power_kw=measured_power,
            temperature_c=new_temp,
            voltage_v=measured_voltage,
            current_a=measured_current,
            cycle_count=measured_cycles,
            health_score=health,
            last_sync_time=time.time(),
            drift_magnitude=drift,
            predicted_fault_hours=self._predict_fault_hours(health, new_temp),
        )
        self._sync_count += 1
        self._emit("sync", self._virtual_state)
        return self._virtual_state

    def _compute_health(
        self, temp_c: float, cycles: float, soc_kwh: float
    ) -> float:
        """
        Health score based on temperature, cycle count, and capacity fade.

        Simplified Arrhenius + cycle aging model.
        """
        # Temperature stress (above 35°C accelerates aging)
        temp_stress = max(0.0, (temp_c - 35.0) / 40.0)
        # Cycle aging (assume 80% capacity at 3000 cycles)
        cycle_stress = min(1.0, cycles / 3000.0)
        # Capacity fade
        capacity_fade = max(0.0, 1.0 - soc_kwh / self.capacity_kwh)

        health = 100.0 * (1.0 - 0.3 * cycle_stress - 0.2 * temp_stress - 0.1 * capacity_fade)
        return max(0.0, min(100.0, health))

    def _determine_status(self, power_kw: float, temp_c: float, health: float) -> AssetStatus:
        if health < 20.0:
            return AssetStatus.FAULT
        if temp_c > 55.0:
            return AssetStatus.FAULT
        if health < 50.0:
            return AssetStatus.DEGRADED
        if abs(power_kw) < 0.1:
            return AssetStatus.ONLINE
        return AssetStatus.ONLINE

    def _predict_fault_hours(self, health: float, temp_c: float) -> Optional[float]:
        """Estimate time to fault based on health trajectory."""
        if health > 80.0:
            return None
        # Simplified: fault when health < 20%
        health_margin = max(0.0, health - 20.0)
        # Degradation rate increases exponentially with temperature
        degradation_rate = 0.01 * (1 + max(0, temp_c - 35) * 0.05)
        return health_margin / max(degradation_rate, 0.001)

    def simulate_scenario(
        self,
        dispatch_profile_kw: List[float],
        dt_h: float = 1.0,
    ) -> List[DigitalTwinState]:
        """
        Run a what-if simulation from current state.

        Returns predicted state sequence.
        """
        states: List[DigitalTwinState] = []
        soc = self._virtual_state.soc_kwh
        temp = self._virtual_state.temperature_c
        cycles = self._virtual_state.cycle_count

        for p_kw in dispatch_profile_kw:
            # Update SOC
            soc_change = -p_kw * dt_h
            soc = max(0.0, min(self.capacity_kwh, soc + soc_change))

            # Temperature rise from power flow (simplified)
            r_thermal = 0.001   # K/W thermal resistance
            temp = temp + p_kw * r_thermal - (temp - 25.0) * 0.1

            # Cycle counting (using half-cycle method)
            cycles += abs(p_kw) * dt_h / (2 * self.capacity_kwh)

            health = self._compute_health(temp, cycles, soc)
            status = self._determine_status(p_kw, temp, health)

            states.append(DigitalTwinState(
                asset_id=self.asset_id,
                status=status,
                soc_kwh=soc,
                soc_pct=soc / self.capacity_kwh * 100.0,
                power_kw=p_kw,
                temperature_c=temp,
                voltage_v=self.nominal_voltage,
                current_a=p_kw * 1000 / max(self.nominal_voltage, 1),
                cycle_count=cycles,
                health_score=health,
                last_sync_time=time.time(),
                drift_magnitude=0.0,
                predicted_fault_hours=self._predict_fault_hours(health, temp),
            ))
        return states

    def on(self, event: str, callback: Callable) -> None:
        self._subscribers.setdefault(event, []).append(callback)

    def _emit(self, event: str, payload: Any) -> None:
        for cb in self._subscribers.get(event, []):
            try:
                cb(payload)
            except Exception:
                pass

    @property
    def current_state(self) -> DigitalTwinState:
        return self._virtual_state
