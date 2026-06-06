"""OCPP (Open Charge Point Protocol) 1.6/2.0.1 implementation for EV chargers."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)

# OCPP WebSocket subprotocol identifiers
OCPP_16_SUBPROTOCOL = "ocpp1.6"
OCPP_201_SUBPROTOCOL = "ocpp2.0.1"

# OCPP message type IDs
CALL = 2
CALLRESULT = 3
CALLERROR = 4


class ChargePointStatus(Enum):
    """OCPP 1.6 ChargePoint status values."""
    AVAILABLE = "Available"
    PREPARING = "Preparing"
    CHARGING = "Charging"
    SUSPENDED_EV = "SuspendedEV"
    SUSPENDED_EVSE = "SuspendedEVSE"
    FINISHING = "Finishing"
    RESERVED = "Reserved"
    UNAVAILABLE = "Unavailable"
    FAULTED = "Faulted"


class ChargingProfilePurpose(Enum):
    """Purpose of a charging profile."""
    CHARGE_POINT_MAX = "ChargePointMaxProfile"
    TX_DEFAULT = "TxDefaultProfile"
    TX = "TxProfile"


class ChargingRateUnit(Enum):
    """Unit of charging rate in a charging schedule."""
    WATTS = "W"
    AMPS = "A"


@dataclass
class ChargingSchedulePeriod:
    start_period: int           # Seconds from schedule start
    limit: float                # Power limit (W or A)
    number_phases: int = 3


@dataclass
class ChargingSchedule:
    duration: int | None        # Total duration in seconds (None = unlimited)
    start_schedule: str | None  # ISO 8601 datetime
    charging_rate_unit: ChargingRateUnit
    charging_schedule_period: list[ChargingSchedulePeriod]
    min_charging_rate: float | None = None


@dataclass
class ChargingProfile:
    charging_profile_id: int
    stack_level: int
    charging_profile_purpose: ChargingProfilePurpose
    charging_profile_kind: str  # "Absolute", "Recurring", "Relative"
    charging_schedule: ChargingSchedule
    transaction_id: int | None = None
    recurrency_kind: str | None = None  # "Daily", "Weekly"
    valid_from: str | None = None
    valid_to: str | None = None


@dataclass
class MeterValue:
    timestamp: str
    sampled_value: list[dict[str, Any]] = field(default_factory=list)

    @property
    def energy_active_import_kwh(self) -> float:
        """Extract active imported energy in kWh."""
        for sv in self.sampled_value:
            if (
                sv.get("measurand") == "Energy.Active.Import.Register"
                and sv.get("unit") == "kWh"
            ):
                return float(sv.get("value", 0))
        return 0.0

    @property
    def power_active_import_w(self) -> float:
        """Extract current active power in W."""
        for sv in self.sampled_value:
            if (
                sv.get("measurand") == "Power.Active.Import"
                and sv.get("unit") == "W"
            ):
                return float(sv.get("value", 0))
        return 0.0


class OCPPCentralSystem:
    """
    OCPP Central System (CSMS — Charge Point Management System).

    Manages a fleet of OCPP charge points, handling BootNotification,
    Heartbeat, MeterValues, and smart charging profile dispatch.

    In a VPP context, the CSMS dispatches charging profiles derived
    from the optimization engine to shape EV load.
    """

    def __init__(self) -> None:
        self._charge_points: dict[str, "OCPPChargePoint"] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._meter_value_callbacks: list[Callable[[str, MeterValue], None]] = []
        self._status_change_callbacks: list[Callable[[str, int, ChargePointStatus], None]] = []

    def register_charge_point(self, cp_id: str, websocket: Any) -> "OCPPChargePoint":
        """Register a newly connected charge point."""
        cp = OCPPChargePoint(cp_id=cp_id, websocket=websocket, csms=self)
        self._charge_points[cp_id] = cp
        logger.info("OCPP charge point registered: %s", cp_id)
        return cp

    def unregister_charge_point(self, cp_id: str) -> None:
        self._charge_points.pop(cp_id, None)
        logger.info("OCPP charge point disconnected: %s", cp_id)

    def on_meter_values(self, callback: Callable[[str, MeterValue], None]) -> None:
        """Subscribe to meter value updates from any charge point."""
        self._meter_value_callbacks.append(callback)

    def on_status_change(
        self, callback: Callable[[str, int, ChargePointStatus], None]
    ) -> None:
        """Subscribe to connector status changes."""
        self._status_change_callbacks.append(callback)

    def dispatch_meter_values(self, cp_id: str, mv: MeterValue) -> None:
        for cb in self._meter_value_callbacks:
            try:
                cb(cp_id, mv)
            except Exception:
                logger.exception("MeterValues callback error for %s", cp_id)

    def dispatch_status_change(
        self, cp_id: str, connector_id: int, status: ChargePointStatus
    ) -> None:
        for cb in self._status_change_callbacks:
            try:
                cb(cp_id, connector_id, status)
            except Exception:
                logger.exception("StatusNotification callback error for %s", cp_id)

    async def set_charging_profile(
        self,
        cp_id: str,
        connector_id: int,
        profile: ChargingProfile,
    ) -> bool:
        """
        Send a SetChargingProfile command to a charge point.

        This is the primary VPP dispatch mechanism for EV load shaping.
        """
        if cp_id not in self._charge_points:
            logger.warning("SetChargingProfile: unknown charge point %s", cp_id)
            return False
        return await self._charge_points[cp_id].set_charging_profile(
            connector_id, profile
        )

    async def get_meter_values(
        self, cp_id: str, connector_id: int = 0
    ) -> list[MeterValue]:
        """Request current meter values from a charge point."""
        if cp_id not in self._charge_points:
            return []
        return await self._charge_points[cp_id].trigger_meter_values(connector_id)

    async def remote_start_transaction(
        self,
        cp_id: str,
        connector_id: int,
        id_tag: str,
        charging_profile: ChargingProfile | None = None,
    ) -> bool:
        """Start a charging transaction remotely."""
        if cp_id not in self._charge_points:
            return False
        return await self._charge_points[cp_id].remote_start_transaction(
            connector_id, id_tag, charging_profile
        )

    @property
    def connected_count(self) -> int:
        return len(self._charge_points)


@dataclass
class OCPPChargePoint:
    """
    Represents a single OCPP-connected charge point (EVSE).

    Handles sending/receiving OCPP messages over a WebSocket connection.
    """

    cp_id: str
    websocket: Any          # asyncio WebSocket connection
    csms: OCPPCentralSystem
    _pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict, init=False)
    status: ChargePointStatus = field(default=ChargePointStatus.AVAILABLE, init=False)
    model: str = field(default="", init=False)
    vendor: str = field(default="", init=False)
    firmware_version: str = field(default="", init=False)

    async def handle_message(self, raw: str) -> None:
        """Parse and dispatch an incoming OCPP message."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("OCPP invalid JSON from %s", self.cp_id)
            return

        if msg[0] == CALL:
            _, unique_id, action, payload = msg
            await self._handle_call(unique_id, action, payload)
        elif msg[0] == CALLRESULT:
            _, unique_id, payload = msg
            fut = self._pending.pop(unique_id, None)
            if fut and not fut.done():
                fut.set_result(payload)
        elif msg[0] == CALLERROR:
            _, unique_id, error_code, error_description, error_details = msg
            fut = self._pending.pop(unique_id, None)
            if fut and not fut.done():
                fut.set_exception(Exception(f"OCPP error {error_code}: {error_description}"))

    async def _handle_call(self, unique_id: str, action: str, payload: dict[str, Any]) -> None:
        """Handle an incoming CALL from the charge point."""
        handler = getattr(self, f"_on_{action.lower()}", None)
        if handler:
            try:
                result = await handler(payload)
            except Exception:
                logger.exception("OCPP handler error for %s", action)
                result = {}
        else:
            logger.debug("OCPP unhandled action: %s", action)
            result = {}
        response = json.dumps([CALLRESULT, unique_id, result])
        if self.websocket:
            await self.websocket.send(response)

    async def _on_bootnotification(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.vendor = payload.get("chargePointVendor", "")
        self.model = payload.get("chargePointModel", "")
        self.firmware_version = payload.get("firmwareVersion", "")
        logger.info(
            "OCPP BootNotification from %s: %s %s FW=%s",
            self.cp_id, self.vendor, self.model, self.firmware_version,
        )
        return {
            "status": "Accepted",
            "currentTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "interval": 60,
        }

    async def _on_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"currentTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    async def _on_statusnotification(self, payload: dict[str, Any]) -> dict[str, Any]:
        connector_id = payload.get("connectorId", 0)
        status_str = payload.get("status", "Available")
        try:
            status = ChargePointStatus(status_str)
        except ValueError:
            status = ChargePointStatus.AVAILABLE
        self.status = status
        self.csms.dispatch_status_change(self.cp_id, connector_id, status)
        return {}

    async def _on_metervalues(self, payload: dict[str, Any]) -> dict[str, Any]:
        for mv_raw in payload.get("meterValue", []):
            mv = MeterValue(
                timestamp=mv_raw.get("timestamp", ""),
                sampled_value=mv_raw.get("sampledValue", []),
            )
            self.csms.dispatch_meter_values(self.cp_id, mv)
        return {}

    async def _on_starttransaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        logger.info("OCPP StartTransaction from %s: idTag=%s", self.cp_id, payload.get("idTag"))
        return {
            "transactionId": int(time.time()),
            "idTagInfo": {"status": "Accepted"},
        }

    async def _on_stoptransaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "OCPP StopTransaction from %s: txId=%s reason=%s",
            self.cp_id,
            payload.get("transactionId"),
            payload.get("reason"),
        )
        return {"idTagInfo": {"status": "Accepted"}}

    async def _call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a CALL message and await the response."""
        unique_id = str(uuid.uuid4())
        message = json.dumps([CALL, unique_id, action, payload])
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[unique_id] = fut
        if self.websocket:
            await self.websocket.send(message)
        return await asyncio.wait_for(fut, timeout=30.0)

    async def set_charging_profile(
        self, connector_id: int, profile: ChargingProfile
    ) -> bool:
        """Send SetChargingProfile to this charge point."""
        schedule = profile.charging_schedule
        payload = {
            "connectorId": connector_id,
            "csChargingProfiles": {
                "chargingProfileId": profile.charging_profile_id,
                "stackLevel": profile.stack_level,
                "chargingProfilePurpose": profile.charging_profile_purpose.value,
                "chargingProfileKind": profile.charging_profile_kind,
                "chargingSchedule": {
                    "chargingRateUnit": schedule.charging_rate_unit.value,
                    "chargingSchedulePeriod": [
                        {
                            "startPeriod": p.start_period,
                            "limit": p.limit,
                            "numberPhases": p.number_phases,
                        }
                        for p in schedule.charging_schedule_period
                    ],
                    **({"duration": schedule.duration} if schedule.duration else {}),
                    **(
                        {"startSchedule": schedule.start_schedule}
                        if schedule.start_schedule
                        else {}
                    ),
                },
            },
        }
        try:
            result = await self._call("SetChargingProfile", payload)
            return result.get("status") == "Accepted"
        except Exception:
            logger.exception("SetChargingProfile failed for %s", self.cp_id)
            return False

    async def trigger_meter_values(self, connector_id: int = 0) -> list[MeterValue]:
        """Request the charge point to send current meter values."""
        try:
            await self._call(
                "TriggerMessage",
                {"requestedMessage": "MeterValues", "connectorId": connector_id},
            )
        except Exception:
            logger.exception("TriggerMessage failed for %s", self.cp_id)
        return []

    async def remote_start_transaction(
        self,
        connector_id: int,
        id_tag: str,
        charging_profile: ChargingProfile | None = None,
    ) -> bool:
        """Send RemoteStartTransaction to begin a charging session."""
        payload: dict[str, Any] = {
            "connectorId": connector_id,
            "idTag": id_tag,
        }
        if charging_profile:
            schedule = charging_profile.charging_schedule
            payload["chargingProfile"] = {
                "chargingProfileId": charging_profile.charging_profile_id,
                "stackLevel": charging_profile.stack_level,
                "chargingProfilePurpose": charging_profile.charging_profile_purpose.value,
                "chargingProfileKind": charging_profile.charging_profile_kind,
                "chargingSchedule": {
                    "chargingRateUnit": schedule.charging_rate_unit.value,
                    "chargingSchedulePeriod": [
                        {"startPeriod": p.start_period, "limit": p.limit}
                        for p in schedule.charging_schedule_period
                    ],
                },
            }
        try:
            result = await self._call("RemoteStartTransaction", payload)
            return result.get("status") == "Accepted"
        except Exception:
            logger.exception("RemoteStartTransaction failed for %s", self.cp_id)
            return False
