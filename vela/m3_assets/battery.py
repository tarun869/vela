"""Battery Energy Storage System (BESS) asset model."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import ClassVar


class BatteryMode(Enum):
    IDLE = "idle"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    STANDBY = "standby"
    FAULT = "fault"


@dataclass
class BatteryDegradation:
    """Tracks calendar and cycle-based capacity degradation."""
    calendar_loss_pct: float = 0.0      # Annual calendar fade (%)
    cycle_loss_pct: float = 0.0         # Accumulated cycle fade (%)
    total_cycles: float = 0.0           # Equivalent full cycles completed

    @property
    def capacity_factor(self) -> float:
        """Remaining usable capacity fraction (floor 70% per warranty)."""
        return max(0.70, 1.0 - (self.calendar_loss_pct + self.cycle_loss_pct) / 100.0)

    def apply_calendar_aging(self, days: float, temperature_c: float = 25.0) -> None:
        """
        Apply calendar aging per Arrhenius model.

        Reference temperature 25°C yields ~2% annual fade.
        Every 10°C above reference doubles the rate.
        """
        rate_per_day = 0.02 / 365.0  # 2% per year at 25°C
        temp_factor = 2.0 ** ((temperature_c - 25.0) / 10.0)
        self.calendar_loss_pct += rate_per_day * days * temp_factor * 100.0


@dataclass
class BatteryAsset:
    """
    Lithium-ion Battery Energy Storage System (BESS).

    Models a grid-scale BESS with state-of-charge tracking, round-trip
    efficiency, C-rate constraints, and degradation.
    """

    asset_id: str
    capacity_mwh: float             # Nameplate energy capacity
    power_mw: float                 # Nameplate power rating
    rte: float = 0.92               # Round-trip efficiency
    soc_min: float = 0.05           # Minimum SOC (depth-of-discharge limit)
    soc_max: float = 0.95           # Maximum SOC
    c_rate_max: float = 1.0         # Max C-rate (1C = full charge in 1 hour)
    degradation: BatteryDegradation = field(default_factory=BatteryDegradation)

    _soc: float = field(default=0.5, init=False, repr=False)
    _mode: BatteryMode = field(default=BatteryMode.IDLE, init=False, repr=False)
    _last_update: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc), init=False, repr=False
    )
    _total_energy_charged_mwh: float = field(default=0.0, init=False, repr=False)
    _total_energy_discharged_mwh: float = field(default=0.0, init=False, repr=False)

    CYCLE_THRESHOLD: ClassVar[float] = 0.2  # SOC delta considered significant

    @property
    def soc(self) -> float:
        """Current state of charge [0.0–1.0]."""
        return self._soc

    @property
    def mode(self) -> BatteryMode:
        return self._mode

    @property
    def usable_capacity_mwh(self) -> float:
        """Usable energy window considering SOC limits and degradation."""
        return (
            self.capacity_mwh
            * (self.soc_max - self.soc_min)
            * self.degradation.capacity_factor
        )

    @property
    def available_discharge_mwh(self) -> float:
        """Energy that can be discharged from current SOC."""
        return max(
            0.0,
            (self._soc - self.soc_min)
            * self.capacity_mwh
            * self.degradation.capacity_factor,
        )

    @property
    def available_charge_mwh(self) -> float:
        """Energy that can be charged from current SOC."""
        return max(
            0.0,
            (self.soc_max - self._soc)
            * self.capacity_mwh
            * self.degradation.capacity_factor,
        )

    @property
    def max_charge_power_mw(self) -> float:
        """C-rate limited maximum charge power."""
        return min(self.power_mw, self.c_rate_max * self.capacity_mwh)

    @property
    def max_discharge_power_mw(self) -> float:
        """C-rate limited maximum discharge power."""
        return min(self.power_mw, self.c_rate_max * self.capacity_mwh)

    def charge(self, power_mw: float, duration_hours: float) -> float:
        """
        Charge the battery at the given power for a duration.

        Returns the actual energy delivered to the AC side (input) in MWh.
        """
        power_mw = min(power_mw, self.max_charge_power_mw)
        energy_in_dc = power_mw * duration_hours * self.rte
        delta_soc = energy_in_dc / (
            self.capacity_mwh * self.degradation.capacity_factor
        )
        actual_delta = min(delta_soc, self.soc_max - self._soc)
        self._soc = min(self.soc_max, self._soc + actual_delta)
        self._mode = BatteryMode.CHARGING
        self._last_update = datetime.now(timezone.utc)
        # Actual AC energy consumed
        actual_energy_ac = (actual_delta / delta_soc * power_mw * duration_hours) if delta_soc > 0 else 0.0
        self._total_energy_charged_mwh += actual_energy_ac
        self._update_cycle_degradation(actual_delta)
        return actual_energy_ac

    def discharge(self, power_mw: float, duration_hours: float) -> float:
        """
        Discharge the battery at the given power for a duration.

        Returns the actual energy delivered to the AC side (output) in MWh.
        """
        power_mw = min(power_mw, self.max_discharge_power_mw)
        energy_out_dc = power_mw * duration_hours
        delta_soc = energy_out_dc / (
            self.capacity_mwh * self.degradation.capacity_factor * self.rte
        )
        actual_delta = min(delta_soc, self._soc - self.soc_min)
        self._soc = max(self.soc_min, self._soc - actual_delta)
        self._mode = BatteryMode.DISCHARGING
        self._last_update = datetime.now(timezone.utc)
        actual_energy_ac = (actual_delta / delta_soc * power_mw * duration_hours) if delta_soc > 0 else 0.0
        self._total_energy_discharged_mwh += actual_energy_ac
        self._update_cycle_degradation(actual_delta)
        return actual_energy_ac

    def idle(self) -> None:
        """Set the battery to idle mode (no charge/discharge)."""
        self._mode = BatteryMode.IDLE

    def _update_cycle_degradation(self, delta_soc: float) -> None:
        """Update cycle count and resulting capacity fade."""
        # Half-cycle counting: charge + discharge = 1 full cycle
        self.degradation.total_cycles += delta_soc * 0.5
        # Empirical NMC fade: ~0.002% per equivalent full cycle
        self.degradation.cycle_loss_pct = min(30.0, self.degradation.total_cycles * 0.002)

    @property
    def lifetime_throughput_mwh(self) -> float:
        """Total energy discharged over asset lifetime."""
        return self._total_energy_discharged_mwh

    def reg_up_capability_mw(self) -> float:
        """Available upward regulation capacity (discharge headroom)."""
        return min(self.max_discharge_power_mw, self.available_discharge_mwh / 0.25)

    def reg_down_capability_mw(self) -> float:
        """Available downward regulation capacity (charge headroom)."""
        return min(self.max_charge_power_mw, self.available_charge_mwh / 0.25)

    def spinning_reserve_mw(self) -> float:
        """Available 10-minute spinning reserve (must respond in <10 min)."""
        # Must be able to sustain for 10 minutes (1/6 hour)
        return min(self.max_discharge_power_mw, self.available_discharge_mwh / (10 / 60))

    def __repr__(self) -> str:
        return (
            f"BatteryAsset(id={self.asset_id!r}, "
            f"soc={self._soc:.1%}, mode={self._mode.value}, "
            f"cap={self.capacity_mwh}MWh, pwr={self.power_mw}MW)"
        )
