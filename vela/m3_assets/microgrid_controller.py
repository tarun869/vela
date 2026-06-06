"""Microgrid controller — island/grid-tie mode switching and power balance."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class MicrogridMode(Enum):
    GRID_TIED = "grid_tied"         # Connected to utility grid
    ISLANDED = "islanded"           # Disconnected, self-sufficient
    TRANSITIONING = "transitioning" # In process of mode switch
    BLACK_START = "black_start"     # Starting up from zero power
    FAULT = "fault"


class LoadPriority(Enum):
    """Load shedding priority levels for islanded operation."""
    CRITICAL = 1    # Life safety: hospital, emergency lighting
    HIGH = 2        # Operations: servers, refrigeration
    MEDIUM = 3      # Comfort: HVAC, elevators
    LOW = 4         # Deferrable: EV charging, water heating


@dataclass
class DispatchableAsset(Protocol):
    """Protocol for assets controllable by the microgrid controller."""
    asset_id: str

    def current_power_mw(self) -> float: ...


@dataclass
class ManagedLoad:
    """A load that can be shed or modulated by the controller."""
    load_id: str
    rated_power_kw: float
    priority: LoadPriority
    currently_energized: bool = True
    shed_cost_usd_per_kwh: float = 0.50  # Cost of curtailment

    @property
    def current_power_kw(self) -> float:
        return self.rated_power_kw if self.currently_energized else 0.0


@dataclass
class MicrogridMetrics:
    """Real-time operational metrics of the microgrid."""
    timestamp: datetime
    mode: MicrogridMode
    frequency_hz: float = 60.0
    voltage_pu: float = 1.0
    total_generation_mw: float = 0.0
    total_load_mw: float = 0.0
    net_import_mw: float = 0.0       # Positive = importing from grid
    battery_soc: float = 0.0
    renewable_fraction: float = 0.0
    load_shed_kw: float = 0.0


@dataclass
class MicrogridController:
    """
    Microgrid Energy Management System (EMS) controller.

    Manages power balance, mode transitions (grid-tied ↔ island),
    load shedding, black-start sequences, and ancillary service provision
    for a microgrid consisting of multiple DER assets and loads.
    """

    microgrid_id: str
    rated_capacity_mw: float            # Aggregate generation capacity
    grid_import_limit_mw: float = 0.0   # Max import from grid (0 = island only)
    grid_export_limit_mw: float = 0.0   # Max export to grid

    # Registered assets and loads
    generation_assets: dict[str, Any] = field(default_factory=dict)
    storage_assets: dict[str, Any] = field(default_factory=dict)
    managed_loads: dict[str, ManagedLoad] = field(default_factory=dict)

    # Control parameters
    frequency_deadband_hz: float = 0.1  # Deadband for freq response
    voltage_deadband_pu: float = 0.03
    min_battery_soc_islanded: float = 0.20   # Min SOC before load shedding
    reserve_margin_pct: float = 10.0         # Required spinning reserve (%)

    _mode: MicrogridMode = field(default=MicrogridMode.GRID_TIED, init=False, repr=False)
    _frequency_hz: float = field(default=60.0, init=False, repr=False)
    _voltage_pu: float = field(default=1.0, init=False, repr=False)
    _net_import_mw: float = field(default=0.0, init=False, repr=False)
    _shed_loads: set[str] = field(default_factory=set, init=False, repr=False)
    _mode_transitions: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    @property
    def mode(self) -> MicrogridMode:
        return self._mode

    def register_generation(self, asset_id: str, asset: Any) -> None:
        self.generation_assets[asset_id] = asset
        logger.info("MG %s: registered generation asset %s", self.microgrid_id, asset_id)

    def register_storage(self, asset_id: str, asset: Any) -> None:
        self.storage_assets[asset_id] = asset
        logger.info("MG %s: registered storage asset %s", self.microgrid_id, asset_id)

    def register_load(self, load: ManagedLoad) -> None:
        self.managed_loads[load.load_id] = load
        logger.info(
            "MG %s: registered load %s (priority=%s, %.1f kW)",
            self.microgrid_id, load.load_id, load.priority.name, load.rated_power_kw,
        )

    @property
    def total_generation_mw(self) -> float:
        total = 0.0
        for asset in self.generation_assets.values():
            try:
                pwr = asset.current_power_mw
                total += pwr if isinstance(pwr, (int, float)) else pwr()
            except Exception:
                pass
        return total

    @property
    def total_load_mw(self) -> float:
        return sum(
            load.current_power_kw / 1000.0
            for load in self.managed_loads.values()
            if load.currently_energized
        )

    @property
    def power_balance_mw(self) -> float:
        """Positive = generation surplus, negative = deficit."""
        return self.total_generation_mw - self.total_load_mw + self._net_import_mw

    def dispatch_cycle(
        self,
        load_mw: float,
        gen_mw: float,
        frequency_hz: float = 60.0,
        voltage_pu: float = 1.0,
    ) -> MicrogridMetrics:
        """
        Execute one dispatch cycle.

        Balances the microgrid, handles frequency deviations,
        and returns the current operational metrics.
        """
        self._frequency_hz = frequency_hz
        self._voltage_pu = voltage_pu

        # Frequency response
        if self._mode == MicrogridMode.ISLANDED:
            self._respond_to_frequency_deviation(frequency_hz, load_mw, gen_mw)

        # Check for fault conditions
        if frequency_hz < 59.0 or frequency_hz > 61.0:
            logger.warning("MG %s: abnormal frequency %.2f Hz", self.microgrid_id, frequency_hz)
        if voltage_pu < 0.90 or voltage_pu > 1.10:
            logger.warning("MG %s: abnormal voltage %.3f pu", self.microgrid_id, voltage_pu)

        # Compute net power balance
        imbalance_mw = gen_mw - load_mw
        if self._mode == MicrogridMode.GRID_TIED:
            self._net_import_mw = -imbalance_mw  # Grid absorbs surplus or supplies deficit
            self._net_import_mw = max(
                -self.grid_export_limit_mw,
                min(self.grid_import_limit_mw, self._net_import_mw),
            )
        else:
            self._net_import_mw = 0.0
            if imbalance_mw < 0:
                # Deficit: try to discharge storage, then shed loads
                self._handle_islanded_deficit(-imbalance_mw)

        return MicrogridMetrics(
            timestamp=datetime.now(timezone.utc),
            mode=self._mode,
            frequency_hz=self._frequency_hz,
            voltage_pu=self._voltage_pu,
            total_generation_mw=gen_mw,
            total_load_mw=load_mw,
            net_import_mw=self._net_import_mw,
            load_shed_kw=self._total_shed_kw(),
        )

    def _respond_to_frequency_deviation(
        self, freq_hz: float, load_mw: float, gen_mw: float
    ) -> None:
        """
        Primary frequency response for islanded operation.

        Uses a simple droop control: Δf → ΔP command.
        Droop setting of 5% means 5% frequency deviation = 100% power response.
        """
        droop_pct = 5.0
        freq_deviation = freq_hz - 60.0
        if abs(freq_deviation) <= self.frequency_deadband_hz:
            return
        # Power response proportional to frequency deviation
        delta_p_mw = -(freq_deviation / (60.0 * droop_pct / 100.0)) * self.rated_capacity_mw
        logger.debug(
            "MG %s: freq response Δf=%.3f Hz → ΔP=%.3f MW",
            self.microgrid_id, freq_deviation, delta_p_mw,
        )

    def _handle_islanded_deficit(self, deficit_mw: float) -> None:
        """Load shedding hierarchy for islanded mode."""
        remaining_deficit_mw = deficit_mw
        # Shed loads in reverse priority order (LOW first)
        for priority in [LoadPriority.LOW, LoadPriority.MEDIUM, LoadPriority.HIGH]:
            if remaining_deficit_mw <= 0:
                break
            for load in sorted(
                self.managed_loads.values(),
                key=lambda x: x.rated_power_kw,
                reverse=True,
            ):
                if load.priority == priority and load.currently_energized:
                    load.currently_energized = False
                    self._shed_loads.add(load.load_id)
                    remaining_deficit_mw -= load.rated_power_kw / 1000.0
                    logger.info(
                        "MG %s: shed load %s (%.1f kW, %s)",
                        self.microgrid_id, load.load_id, load.rated_power_kw, priority.name,
                    )
                    if remaining_deficit_mw <= 0:
                        break

    def restore_loads(self, available_headroom_mw: float) -> float:
        """
        Restore shed loads when surplus power is available.

        Returns kW of load restored.
        """
        restored_kw = 0.0
        for priority in [LoadPriority.HIGH, LoadPriority.MEDIUM, LoadPriority.LOW]:
            for load in self.managed_loads.values():
                if (
                    load.load_id in self._shed_loads
                    and load.priority == priority
                    and load.rated_power_kw / 1000.0 <= available_headroom_mw
                ):
                    load.currently_energized = True
                    self._shed_loads.discard(load.load_id)
                    available_headroom_mw -= load.rated_power_kw / 1000.0
                    restored_kw += load.rated_power_kw
                    logger.info("MG %s: restored load %s", self.microgrid_id, load.load_id)
        return restored_kw

    def transition_to_island(self) -> bool:
        """
        Initiate transition from grid-tied to islanded mode.

        Validates that sufficient generation + storage capacity exists.
        """
        total_gen = self.total_generation_mw + sum(
            getattr(a, "available_discharge_mwh", 0) / 0.25  # 15-min headroom
            for a in self.storage_assets.values()
        )
        if total_gen < self.total_load_mw * (1 + self.reserve_margin_pct / 100.0):
            logger.warning(
                "MG %s: insufficient capacity to island (need %.2f MW, have %.2f MW)",
                self.microgrid_id,
                self.total_load_mw * (1 + self.reserve_margin_pct / 100.0),
                total_gen,
            )
            return False
        self._mode = MicrogridMode.TRANSITIONING
        self._mode_transitions.append({
            "from": MicrogridMode.GRID_TIED.value,
            "to": MicrogridMode.ISLANDED.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._mode = MicrogridMode.ISLANDED
        logger.info("MG %s: transitioned to islanded mode", self.microgrid_id)
        return True

    def reconnect_to_grid(self) -> bool:
        """Reconnect to utility grid (synchronization check)."""
        if self._mode != MicrogridMode.ISLANDED:
            return False
        # In production: verify voltage/frequency/phase match before closing tie breaker
        self._mode = MicrogridMode.TRANSITIONING
        self._mode = MicrogridMode.GRID_TIED
        self._net_import_mw = 0.0
        # Restore all shed loads
        self.restore_loads(9999.0)
        logger.info("MG %s: reconnected to grid", self.microgrid_id)
        return True

    def _total_shed_kw(self) -> float:
        return sum(
            self.managed_loads[lid].rated_power_kw
            for lid in self._shed_loads
            if lid in self.managed_loads
        )

    def spinning_reserve_mw(self) -> float:
        """Available spinning reserve (on-line generation headroom)."""
        return max(
            0.0,
            self.rated_capacity_mw * (1 + self.reserve_margin_pct / 100.0)
            - self.total_load_mw
        )

    def __repr__(self) -> str:
        return (
            f"MicrogridController(id={self.microgrid_id!r}, "
            f"mode={self._mode.value}, "
            f"gen={self.total_generation_mw:.2f}MW, "
            f"load={self.total_load_mw:.2f}MW)"
        )
