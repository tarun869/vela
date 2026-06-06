"""Thermal energy storage asset model (hot water / chilled water / ice)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class ThermalStorageType(Enum):
    HOT_WATER = "hot_water"
    CHILLED_WATER = "chilled_water"
    ICE = "ice"
    MOLTEN_SALT = "molten_salt"     # For CSP or industrial applications


class ThermalMode(Enum):
    CHARGING = "charging"       # Adding thermal energy (heating/cooling)
    DISCHARGING = "discharging" # Releasing thermal energy
    IDLE = "idle"
    FAULT = "fault"


@dataclass
class ThermalAsset:
    """
    Thermal energy storage system (TES).

    Models a tank-based thermal storage that couples electrical power
    (via heat pump / chiller / heater) to stored thermal energy.
    Used for demand flexibility — charge during low-price periods,
    discharge (shift load) during high-price periods.

    The key coupling: electricity drives a heat pump or chiller with
    a COP, converting electrical energy to thermal energy for storage.
    """

    asset_id: str
    storage_type: ThermalStorageType
    capacity_mwht: float                    # Thermal MWh capacity
    charge_cop: float = 3.5                 # Coefficient of performance (cooling: 3–5, heating: 2–4)
    discharge_cop: float = 1.0              # For heating systems, discharge may be resistive
    max_charge_mw_thermal: float = 1.0      # Max thermal charging rate
    max_discharge_mw_thermal: float = 1.0   # Max thermal discharge rate
    standby_loss_pct_per_hour: float = 0.5  # Self-discharge / heat loss (%/hour)
    min_soc: float = 0.05
    max_soc: float = 0.95
    # Temperature parameters (for hot/cold storage)
    charge_temp_c: float = 6.0              # Chilled water: ~6°C supply; Hot: 90°C
    discharge_temp_c: float = 12.0          # Chilled water: ~12°C return; Hot: 60°C
    ambient_temp_c: float = 25.0

    _soc: float = field(default=0.5, init=False, repr=False)
    _mode: ThermalMode = field(default=ThermalMode.IDLE, init=False, repr=False)
    _total_charged_mwht: float = field(default=0.0, init=False, repr=False)
    _total_discharged_mwht: float = field(default=0.0, init=False, repr=False)

    WATER_SPECIFIC_HEAT_KJ_KG_K: ClassVar[float] = 4.186  # kJ/(kg·K)

    @property
    def soc(self) -> float:
        return self._soc

    @property
    def mode(self) -> ThermalMode:
        return self._mode

    @property
    def stored_energy_mwht(self) -> float:
        return self._soc * self.capacity_mwht

    @property
    def usable_capacity_mwht(self) -> float:
        return self.capacity_mwht * (self.max_soc - self.min_soc)

    @property
    def available_discharge_mwht(self) -> float:
        return max(0.0, (self._soc - self.min_soc) * self.capacity_mwht)

    @property
    def available_charge_mwht(self) -> float:
        return max(0.0, (self.max_soc - self._soc) * self.capacity_mwht)

    @property
    def max_charge_power_mw_electric(self) -> float:
        """Electrical power needed for max thermal charging rate."""
        return self.max_charge_mw_thermal / self.charge_cop

    @property
    def max_discharge_power_mw_electric(self) -> float:
        """Electrical power displaced during max thermal discharge."""
        return self.max_discharge_mw_thermal * self.discharge_cop

    def charge(self, electrical_power_mw: float, duration_hours: float) -> float:
        """
        Charge the thermal storage using the heat pump/chiller.

        Returns actual electrical energy consumed (MWh).
        """
        # Convert electrical to thermal via COP
        thermal_rate_mwh = electrical_power_mw * self.charge_cop
        thermal_rate_mwh = min(thermal_rate_mwh, self.max_charge_mw_thermal)
        thermal_in = thermal_rate_mwh * duration_hours
        delta_soc = thermal_in / self.capacity_mwht
        actual_delta = min(delta_soc, self.max_soc - self._soc)
        self._soc += actual_delta
        self._mode = ThermalMode.CHARGING
        self._total_charged_mwht += actual_delta * self.capacity_mwht
        # Apply standby losses
        self._apply_standby_loss(duration_hours)
        # Return actual electrical energy consumed
        actual_thermal = actual_delta * self.capacity_mwht
        return actual_thermal / self.charge_cop

    def discharge(self, thermal_demand_mw: float, duration_hours: float) -> float:
        """
        Discharge thermal energy to meet a cooling/heating load.

        Returns thermal energy actually delivered (MWht), which displaces
        equivalent electrical load.
        """
        thermal_demand_mw = min(thermal_demand_mw, self.max_discharge_mw_thermal)
        thermal_out = thermal_demand_mw * duration_hours
        delta_soc = thermal_out / self.capacity_mwht
        actual_delta = min(delta_soc, self._soc - self.min_soc)
        self._soc = max(self.min_soc, self._soc - actual_delta)
        self._mode = ThermalMode.DISCHARGING
        self._total_discharged_mwht += actual_delta * self.capacity_mwht
        self._apply_standby_loss(duration_hours)
        return actual_delta * self.capacity_mwht

    def _apply_standby_loss(self, duration_hours: float) -> None:
        """Apply thermal standby losses (heat exchange with ambient)."""
        loss_fraction = self.standby_loss_pct_per_hour / 100.0 * duration_hours
        self._soc = max(0.0, self._soc - loss_fraction)

    def idle(self, duration_hours: float) -> None:
        """Advance time with no charge/discharge, applying only standby losses."""
        self._mode = ThermalMode.IDLE
        self._apply_standby_loss(duration_hours)

    def electrical_load_shift_mw(
        self, discharge_rate_mwh_thermal_per_h: float
    ) -> float:
        """
        Compute the equivalent electrical load shifted by thermal discharge.

        When TES discharges at rate Q_th, it displaces electrical cooling/heating
        that would have consumed Q_th / COP electrical power.
        """
        return discharge_rate_mwh_thermal_per_h / self.charge_cop

    def optimal_charge_rate_for_price(
        self,
        price_usd_per_mwh: float,
        max_price_threshold: float = 60.0,
    ) -> float:
        """
        Return optimal electrical charging rate based on price signal.

        Charge aggressively at low prices, stop above threshold.
        """
        if price_usd_per_mwh <= 0:
            return self.max_charge_power_mw_electric
        if price_usd_per_mwh >= max_price_threshold:
            return 0.0
        # Linear scaling: 0% at max_price → 100% at 0
        fraction = 1.0 - price_usd_per_mwh / max_price_threshold
        return fraction * self.max_charge_power_mw_electric

    @property
    def tank_volume_m3(self) -> float:
        """Estimate tank volume from stored energy capacity."""
        delta_t = abs(self.discharge_temp_c - self.charge_temp_c)
        if delta_t <= 0:
            return 0.0
        # E = ρ * V * Cp * ΔT → V = E / (ρ * Cp * ΔT)
        # ρ_water = 1000 kg/m³
        energy_kj = self.capacity_mwht * 3600.0 * 1000.0  # Convert MWh to kJ
        return energy_kj / (1000.0 * self.WATER_SPECIFIC_HEAT_KJ_KG_K * delta_t)

    def __repr__(self) -> str:
        return (
            f"ThermalAsset(id={self.asset_id!r}, "
            f"type={self.storage_type.value}, "
            f"soc={self._soc:.1%}, cap={self.capacity_mwht}MWht, "
            f"mode={self._mode.value})"
        )
