"""EV fleet asset model with V2G (vehicle-to-grid) capability."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import ClassVar


class EVFleetMode(Enum):
    CHARGING = "charging"
    DISCHARGING_V2G = "discharging_v2g"
    IDLE = "idle"
    AWAY = "away"             # Vehicles not plugged in


@dataclass
class EVVehicle:
    """Individual vehicle in the fleet."""
    vehicle_id: str
    battery_capacity_kwh: float
    max_charge_rate_kw: float = 7.4     # Level 2 AC charging (typical)
    max_discharge_rate_kw: float = 0.0  # V2G discharge (0 if not V2G capable)
    soc: float = 0.5
    soc_min: float = 0.2                # Fleet policy minimum
    soc_max: float = 0.95
    plugged_in: bool = True
    departure_time: datetime | None = None
    required_soc_at_departure: float = 0.80  # Customer-required SOC

    @property
    def available_energy_kwh(self) -> float:
        return max(0.0, (self.soc - self.soc_min) * self.battery_capacity_kwh)

    @property
    def needed_energy_kwh(self) -> float:
        return max(0.0, (self.required_soc_at_departure - self.soc) * self.battery_capacity_kwh)

    @property
    def v2g_capable(self) -> bool:
        return self.max_discharge_rate_kw > 0


@dataclass
class EVFleetAsset:
    """
    Fleet of Electric Vehicles with managed charging and V2G capability.

    Aggregates a set of EVs and coordinates charging/discharging as a
    dispatchable VPP asset, respecting customer departure requirements.
    """

    asset_id: str
    location: str = ""
    vehicles: list[EVVehicle] = field(default_factory=list)
    charger_efficiency: float = 0.92    # Charger AC-DC efficiency
    v2g_efficiency: float = 0.90        # V2G (DC-AC) efficiency

    _mode: EVFleetMode = field(default=EVFleetMode.IDLE, init=False, repr=False)
    _aggregate_power_kw: float = field(default=0.0, init=False, repr=False)

    @property
    def plugged_count(self) -> int:
        return sum(1 for v in self.vehicles if v.plugged_in)

    @property
    def v2g_count(self) -> int:
        return sum(1 for v in self.vehicles if v.plugged_in and v.v2g_capable)

    @property
    def fleet_soc(self) -> float:
        """Capacity-weighted average SOC of plugged-in vehicles."""
        plugged = [v for v in self.vehicles if v.plugged_in]
        if not plugged:
            return 0.0
        total_cap = sum(v.battery_capacity_kwh for v in plugged)
        weighted = sum(v.soc * v.battery_capacity_kwh for v in plugged)
        return weighted / total_cap if total_cap > 0 else 0.0

    @property
    def total_capacity_kwh(self) -> float:
        return sum(v.battery_capacity_kwh for v in self.vehicles if v.plugged_in)

    @property
    def total_capacity_mwh(self) -> float:
        return self.total_capacity_kwh / 1000.0

    @property
    def max_aggregate_charge_kw(self) -> float:
        return sum(v.max_charge_rate_kw for v in self.vehicles if v.plugged_in)

    @property
    def max_aggregate_discharge_kw(self) -> float:
        return sum(
            v.max_discharge_rate_kw for v in self.vehicles if v.plugged_in and v.v2g_capable
        )

    @property
    def available_discharge_kwh(self) -> float:
        """Total energy available for V2G discharge."""
        return sum(
            v.available_energy_kwh
            for v in self.vehicles
            if v.plugged_in and v.v2g_capable
        )

    @property
    def available_charge_kwh(self) -> float:
        """Total headroom available for managed charging."""
        return sum(
            max(0.0, (v.soc_max - v.soc) * v.battery_capacity_kwh)
            for v in self.vehicles
            if v.plugged_in
        )

    @property
    def current_power_kw(self) -> float:
        """Positive = consuming (charging), negative = producing (V2G)."""
        return self._aggregate_power_kw

    @property
    def current_power_mw(self) -> float:
        return self._aggregate_power_kw / 1000.0

    def charge(self, total_power_kw: float, duration_hours: float) -> float:
        """
        Distribute charging power across plugged-in vehicles.

        Uses proportional allocation based on needed energy.
        Returns actual aggregate AC power consumed (kW).
        """
        plugged = [v for v in self.vehicles if v.plugged_in]
        if not plugged or total_power_kw <= 0:
            self._aggregate_power_kw = 0.0
            return 0.0

        # Allocate proportionally to needed energy, up to each vehicle's max rate
        total_needed = sum(v.needed_energy_kwh / duration_hours for v in plugged)
        total_actual_kw = 0.0

        for v in plugged:
            if total_needed > 0:
                share = (v.needed_energy_kwh / duration_hours) / total_needed
            else:
                share = 1.0 / len(plugged)
            allocated_kw = min(
                total_power_kw * share,
                v.max_charge_rate_kw,
            )
            # Apply charger efficiency
            energy_in_kwh = allocated_kw * duration_hours * self.charger_efficiency
            delta_soc = energy_in_kwh / v.battery_capacity_kwh
            actual_delta = min(delta_soc, v.soc_max - v.soc)
            v.soc = min(v.soc_max, v.soc + actual_delta)
            # Actual AC power consumed
            actual_kw = allocated_kw * (actual_delta / delta_soc) if delta_soc > 0 else 0.0
            total_actual_kw += actual_kw

        self._mode = EVFleetMode.CHARGING
        self._aggregate_power_kw = total_actual_kw
        return total_actual_kw

    def discharge_v2g(self, total_power_kw: float, duration_hours: float) -> float:
        """
        Dispatch V2G power from the fleet.

        Returns actual aggregate AC power delivered to grid (kW).
        """
        v2g_capable = [v for v in self.vehicles if v.plugged_in and v.v2g_capable]
        if not v2g_capable or total_power_kw <= 0:
            self._aggregate_power_kw = 0.0
            return 0.0

        total_available = sum(v.available_energy_kwh / duration_hours for v in v2g_capable)
        total_actual_kw = 0.0

        for v in v2g_capable:
            if total_available > 0:
                share = (v.available_energy_kwh / duration_hours) / total_available
            else:
                share = 1.0 / len(v2g_capable)
            allocated_kw = min(
                total_power_kw * share,
                v.max_discharge_rate_kw,
            )
            energy_out_dc = allocated_kw * duration_hours / self.v2g_efficiency
            delta_soc = energy_out_dc / v.battery_capacity_kwh
            actual_delta = min(delta_soc, v.soc - v.soc_min)
            v.soc = max(v.soc_min, v.soc - actual_delta)
            actual_kw = allocated_kw * (actual_delta / delta_soc) if delta_soc > 0 else 0.0
            total_actual_kw += actual_kw

        self._mode = EVFleetMode.DISCHARGING_V2G
        self._aggregate_power_kw = -total_actual_kw  # Negative = injecting to grid
        return total_actual_kw

    def smart_charge_schedule(
        self,
        available_power_kw: float,
        duration_hours: float,
        price_signal: float = 0.0,
    ) -> float:
        """
        Compute optimal charging rate using simplified price-responsive logic.

        When price is high: minimize charging (only maintain departure SOC).
        When price is low: opportunistic charging up to max.
        """
        if not self.vehicles:
            return 0.0

        # Must-charge to meet departures (non-negotiable)
        must_charge = min(
            available_power_kw,
            sum(
                v.max_charge_rate_kw
                for v in self.vehicles
                if v.plugged_in and v.needed_energy_kwh > 0
            ),
        )
        # Optional charge based on price signal
        if price_signal < 20.0:  # Low price threshold $/MWh
            target_kw = min(available_power_kw, self.max_aggregate_charge_kw)
        elif price_signal > 80.0:  # High price: only must-charge
            target_kw = must_charge
        else:
            # Linear interpolation between must-charge and full
            t = (price_signal - 20.0) / 60.0
            target_kw = must_charge + (1.0 - t) * (
                min(available_power_kw, self.max_aggregate_charge_kw) - must_charge
            )
        return self.charge(target_kw, duration_hours)

    def update_plugged_status(
        self, vehicle_id: str, plugged_in: bool
    ) -> None:
        """Update plug-in status for a vehicle (from OCPP status notification)."""
        for v in self.vehicles:
            if v.vehicle_id == vehicle_id:
                v.plugged_in = plugged_in
                break

    def reg_up_capability_kw(self) -> float:
        """Available V2G regulation-up capacity."""
        return min(
            self.max_aggregate_discharge_kw,
            self.available_discharge_kwh / 0.25,  # 15-min sustained
        )

    def reg_down_capability_kw(self) -> float:
        """Available charge regulation-down capacity."""
        return min(
            self.max_aggregate_charge_kw,
            self.available_charge_kwh / 0.25,
        )

    def add_vehicle(self, vehicle: EVVehicle) -> None:
        self.vehicles.append(vehicle)

    def remove_vehicle(self, vehicle_id: str) -> bool:
        for i, v in enumerate(self.vehicles):
            if v.vehicle_id == vehicle_id:
                self.vehicles.pop(i)
                return True
        return False

    def __repr__(self) -> str:
        return (
            f"EVFleetAsset(id={self.asset_id!r}, "
            f"vehicles={len(self.vehicles)}, plugged={self.plugged_count}, "
            f"fleet_soc={self.fleet_soc:.1%}, "
            f"power={self._aggregate_power_kw:.1f}kW)"
        )
