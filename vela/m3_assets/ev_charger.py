"""EV charger (EVSE) asset model with smart charging and V2G capability."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class ChargerLevel(Enum):
    """SAE J1772 charger level classifications."""
    LEVEL_1 = "level_1"         # 120V AC, up to 1.4–1.9 kW
    LEVEL_2 = "level_2"         # 240V AC, up to 7.2–19.2 kW
    DC_FAST = "dc_fast"         # 50–350 kW DC (CHAdeMO, CCS)
    ULTRA_FAST = "ultra_fast"   # 350+ kW (HPC, Megacharger)


class EVSEMode(Enum):
    AVAILABLE = "available"     # Ready, no vehicle
    CHARGING = "charging"       # Vehicle connected, charging
    DISCHARGING = "discharging" # V2G: sending power to grid
    FAULT = "fault"
    OFFLINE = "offline"
    RESERVED = "reserved"


class ConnectorType(Enum):
    J1772 = "j1772"
    CCS1 = "ccs1"
    CCS2 = "ccs2"
    CHADEMO = "chademo"
    NACS = "nacs"       # Tesla/SAE J3400
    TYPE2 = "type2"     # European IEC 62196


@dataclass
class EVSession:
    """Active EV charging session data."""
    session_id: str
    vehicle_id: str
    start_time: float = field(default_factory=time.time)
    energy_delivered_kwh: float = 0.0
    initial_soc: float = 0.0
    current_soc: float = 0.0
    target_soc: float = 0.80
    vehicle_battery_kwh: float = 60.0   # Vehicle battery capacity
    vehicle_max_charge_kw: float = 7.4  # Vehicle EVSE acceptance rate
    # V2G parameters
    v2g_capable: bool = False
    v2g_min_soc: float = 0.30           # Min SOC for V2G (customer preference)

    @property
    def energy_remaining_to_target_kwh(self) -> float:
        return max(
            0.0,
            (self.target_soc - self.current_soc) * self.vehicle_battery_kwh,
        )

    @property
    def duration_minutes(self) -> float:
        return (time.time() - self.start_time) / 60.0


@dataclass
class EVChargerAsset:
    """
    EV Supply Equipment (EVSE) — smart charger with bidirectional V2G support.

    Handles OCPP-based charging sessions, smart charging profiles,
    and V2G dispatch for grid services.
    """

    asset_id: str
    charger_level: ChargerLevel
    max_power_kw: float
    connector_type: ConnectorType = ConnectorType.CCS1
    efficiency: float = 0.92            # Charger efficiency (AC→DC)
    v2g_efficiency: float = 0.90        # V2G efficiency (DC→AC)
    min_power_kw: float = 0.0           # Minimum charge rate (or 0)
    location: str = ""

    _mode: EVSEMode = field(default=EVSEMode.AVAILABLE, init=False, repr=False)
    _current_session: EVSession | None = field(default=None, init=False, repr=False)
    _current_power_kw: float = field(default=0.0, init=False, repr=False)
    _total_energy_kwh: float = field(default=0.0, init=False, repr=False)
    _total_sessions: int = field(default=0, init=False, repr=False)
    _total_v2g_kwh: float = field(default=0.0, init=False, repr=False)

    # Smart charging control
    _scheduled_power_kw: float | None = field(default=None, init=False, repr=False)

    # Typical level power ratings (kW)
    LEVEL_RATINGS: ClassVar[dict[str, tuple[float, float]]] = {
        "level_1": (1.4, 1.9),
        "level_2": (3.3, 19.2),
        "dc_fast": (24.0, 150.0),
        "ultra_fast": (150.0, 350.0),
    }

    @property
    def mode(self) -> EVSEMode:
        return self._mode

    @property
    def is_occupied(self) -> bool:
        return self._current_session is not None

    @property
    def current_power_kw(self) -> float:
        """Positive = consuming (charging), negative = V2G (injecting)."""
        return self._current_power_kw

    @property
    def current_session(self) -> EVSession | None:
        return self._current_session

    @property
    def vehicle_soc(self) -> float:
        if self._current_session:
            return self._current_session.current_soc
        return 0.0

    def connect_vehicle(
        self,
        session_id: str,
        vehicle_id: str,
        vehicle_battery_kwh: float,
        initial_soc: float,
        target_soc: float = 0.80,
        vehicle_max_charge_kw: float | None = None,
        v2g_capable: bool = False,
        v2g_min_soc: float = 0.30,
    ) -> EVSession:
        """Initiate a new charging session when a vehicle connects."""
        if self._mode == EVSEMode.OFFLINE:
            raise RuntimeError(f"Charger {self.asset_id} is offline")
        max_charge = vehicle_max_charge_kw or self.max_power_kw
        session = EVSession(
            session_id=session_id,
            vehicle_id=vehicle_id,
            vehicle_battery_kwh=vehicle_battery_kwh,
            initial_soc=initial_soc,
            current_soc=initial_soc,
            target_soc=target_soc,
            vehicle_max_charge_kw=min(max_charge, self.max_power_kw),
            v2g_capable=v2g_capable,
            v2g_min_soc=v2g_min_soc,
        )
        self._current_session = session
        self._mode = EVSEMode.CHARGING
        self._total_sessions += 1
        return session

    def disconnect_vehicle(self) -> EVSession | None:
        """End the current session when vehicle unplugs."""
        session = self._current_session
        self._current_session = None
        self._current_power_kw = 0.0
        self._mode = EVSEMode.AVAILABLE
        self._scheduled_power_kw = None
        return session

    def charge(self, power_kw: float, duration_hours: float) -> float:
        """
        Charge the connected vehicle at the specified power.

        Returns actual AC energy consumed (kWh).
        """
        if self._current_session is None or self._mode != EVSEMode.CHARGING:
            return 0.0

        session = self._current_session
        # Apply charger and vehicle limits
        effective_max = min(
            self.max_power_kw,
            session.vehicle_max_charge_kw,
            self._scheduled_power_kw if self._scheduled_power_kw is not None else self.max_power_kw,
        )
        power_kw = max(self.min_power_kw, min(power_kw, effective_max))

        # Energy delivered to battery (after charger losses)
        energy_to_battery = power_kw * duration_hours * self.efficiency
        delta_soc = energy_to_battery / session.vehicle_battery_kwh
        actual_delta = min(delta_soc, session.target_soc - session.current_soc)

        if actual_delta <= 0:
            # Battery is full
            self._current_power_kw = 0.0
            return 0.0

        session.current_soc += actual_delta
        session.energy_delivered_kwh += actual_delta * session.vehicle_battery_kwh / self.efficiency
        actual_energy_ac = actual_delta / delta_soc * power_kw * duration_hours
        self._current_power_kw = power_kw * (actual_delta / delta_soc)
        self._total_energy_kwh += actual_energy_ac
        return actual_energy_ac

    def discharge_v2g(self, power_kw: float, duration_hours: float) -> float:
        """
        Discharge vehicle battery to grid (V2G).

        Returns AC energy injected to grid (kWh).
        """
        if self._current_session is None or not self._current_session.v2g_capable:
            return 0.0
        if self._mode not in (EVSEMode.CHARGING, EVSEMode.DISCHARGING):
            return 0.0

        session = self._current_session
        power_kw = min(power_kw, self.max_power_kw, session.vehicle_max_charge_kw)

        # Energy drawn from battery
        energy_from_battery_kwh = power_kw * duration_hours / self.v2g_efficiency
        delta_soc = energy_from_battery_kwh / session.vehicle_battery_kwh
        # Respect V2G minimum SOC
        max_delta = max(0.0, session.current_soc - session.v2g_min_soc)
        actual_delta = min(delta_soc, max_delta)

        if actual_delta <= 0:
            return 0.0

        session.current_soc -= actual_delta
        ac_energy_kwh = (actual_delta / delta_soc) * power_kw * duration_hours
        self._current_power_kw = -(power_kw * actual_delta / delta_soc)  # Negative
        self._mode = EVSEMode.DISCHARGING
        self._total_v2g_kwh += ac_energy_kwh
        return ac_energy_kwh

    def set_smart_charge_limit(self, power_kw: float | None) -> None:
        """
        Set a smart charging power limit from the OCPP CSMS.

        None removes the limit (uncontrolled charging).
        """
        if power_kw is not None:
            self._scheduled_power_kw = max(0.0, min(power_kw, self.max_power_kw))
        else:
            self._scheduled_power_kw = None

    def price_responsive_charge(
        self,
        price_usd_per_mwh: float,
        duration_hours: float,
        low_price_threshold: float = 30.0,
        high_price_threshold: float = 80.0,
    ) -> float:
        """
        Smart charging with price signal response.

        Below low_price: charge at maximum rate.
        Above high_price: pause charging (except must-fill).
        Linear interpolation in between.
        """
        if self._current_session is None:
            return 0.0
        session = self._current_session
        must_charge_remaining = session.energy_remaining_to_target_kwh
        if must_charge_remaining <= 0:
            return 0.0

        if price_usd_per_mwh <= low_price_threshold:
            target_kw = self.max_power_kw
        elif price_usd_per_mwh >= high_price_threshold:
            # Only charge if urgently needed (< 30 min of session remaining)
            if session.duration_minutes > 30:
                target_kw = 0.0
            else:
                target_kw = min(self.max_power_kw, must_charge_remaining / (0.5 * self.efficiency))
        else:
            t = (price_usd_per_mwh - low_price_threshold) / (
                high_price_threshold - low_price_threshold
            )
            target_kw = self.max_power_kw * (1.0 - t)

        return self.charge(target_kw, duration_hours)

    @property
    def available_reg_down_kw(self) -> float:
        """Regulation-down (increase charge) capacity."""
        if self._current_session is None:
            return 0.0
        return max(0.0, self.max_power_kw - self._current_power_kw)

    @property
    def available_reg_up_kw(self) -> float:
        """Regulation-up (reduce charge or V2G) capacity."""
        if self._current_session is None:
            return 0.0
        if self._current_session.v2g_capable:
            return min(self.max_power_kw, self._current_power_kw + self.max_power_kw)
        return max(0.0, self._current_power_kw)

    def __repr__(self) -> str:
        session_info = (
            f"vehicle={self._current_session.vehicle_id}, soc={self._current_session.current_soc:.1%}"
            if self._current_session
            else "no vehicle"
        )
        return (
            f"EVChargerAsset(id={self.asset_id!r}, "
            f"level={self.charger_level.value}, {self.max_power_kw}kW, "
            f"mode={self._mode.value}, {session_info})"
        )
