"""Asset registry with CRUD operations and type-safe access."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, TypeVar

from vela.m4_state.models import AssetState, AssetStatus

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class AssetRegistration:
    """Registration record for an asset in the VPP."""
    asset_id: str
    asset_type: str           # "battery", "solar", "wind", "ev_fleet", etc.
    site_id: str
    owner: str
    capacity_mw: float
    energy_capacity_mwh: float | None = None
    protocol: str = ""        # "modbus_tcp", "dnp3", "ocpp", etc.
    ip_address: str = ""
    port: int = 502
    unit_id: int = 1
    metering_id: str = ""
    registration_date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active: bool = True
    tags: dict[str, str] = field(default_factory=dict)
    asset_object: Any = None  # The actual asset model instance


class AssetRegistry:
    """
    Thread-safe in-memory asset registry.

    Stores asset registration metadata and live asset model objects.
    Supports CRUD operations and filtered queries.
    """

    def __init__(self) -> None:
        self._registrations: dict[str, AssetRegistration] = {}
        self._states: dict[str, AssetState] = {}
        self._lock = threading.RLock()
        logger.info("AssetRegistry initialized")

    def register(self, registration: AssetRegistration) -> None:
        """Register a new asset."""
        with self._lock:
            if registration.asset_id in self._registrations:
                logger.warning("Asset %s already registered; updating", registration.asset_id)
            self._registrations[registration.asset_id] = registration
            # Initialize state
            self._states[registration.asset_id] = AssetState(
                asset_id=registration.asset_id,
                asset_type=registration.asset_type,
                status=AssetStatus.OFFLINE,
                power_mw=0.0,
                soc=None,
            )
            logger.info(
                "Registered asset %s (type=%s, site=%s)",
                registration.asset_id,
                registration.asset_type,
                registration.site_id,
            )

    def deregister(self, asset_id: str) -> bool:
        """Remove an asset from the registry."""
        with self._lock:
            if asset_id not in self._registrations:
                return False
            del self._registrations[asset_id]
            self._states.pop(asset_id, None)
            logger.info("Deregistered asset %s", asset_id)
            return True

    def get(self, asset_id: str) -> AssetRegistration | None:
        """Retrieve an asset registration by ID."""
        with self._lock:
            return self._registrations.get(asset_id)

    def get_object(self, asset_id: str) -> Any:
        """Return the live asset model object."""
        with self._lock:
            reg = self._registrations.get(asset_id)
            return reg.asset_object if reg else None

    def set_object(self, asset_id: str, obj: Any) -> None:
        """Attach a live asset model object to a registration."""
        with self._lock:
            if asset_id in self._registrations:
                self._registrations[asset_id].asset_object = obj

    def update_state(self, state: AssetState) -> None:
        """Update the live state for an asset."""
        with self._lock:
            self._states[state.asset_id] = state

    def get_state(self, asset_id: str) -> AssetState | None:
        """Get the latest state for an asset."""
        with self._lock:
            return self._states.get(asset_id)

    def all_states(self) -> list[AssetState]:
        """Return all current asset states."""
        with self._lock:
            return list(self._states.values())

    def by_type(self, asset_type: str) -> list[AssetRegistration]:
        """Filter registrations by asset type."""
        with self._lock:
            return [
                r for r in self._registrations.values()
                if r.asset_type == asset_type and r.active
            ]

    def by_site(self, site_id: str) -> list[AssetRegistration]:
        """Filter registrations by site."""
        with self._lock:
            return [
                r for r in self._registrations.values()
                if r.site_id == site_id and r.active
            ]

    def online(self) -> list[AssetRegistration]:
        """Return registrations whose current state is ONLINE."""
        with self._lock:
            return [
                self._registrations[sid]
                for sid, state in self._states.items()
                if state.status == AssetStatus.ONLINE
                and sid in self._registrations
                and self._registrations[sid].active
            ]

    def aggregate_power_mw(self, asset_type: str | None = None) -> float:
        """Sum of current power output across matching assets (MW)."""
        with self._lock:
            states = list(self._states.values())
        if asset_type:
            regs = self._registrations
            states = [
                s for s in states
                if regs.get(s.asset_id) and regs[s.asset_id].asset_type == asset_type
            ]
        return sum(s.power_mw for s in states)

    def aggregate_capacity_mw(self, asset_type: str | None = None) -> float:
        """Total registered capacity in MW."""
        with self._lock:
            regs = list(self._registrations.values())
        if asset_type:
            regs = [r for r in regs if r.asset_type == asset_type]
        return sum(r.capacity_mw for r in regs if r.active)

    def mark_online(self, asset_id: str) -> None:
        """Mark an asset as online."""
        with self._lock:
            state = self._states.get(asset_id)
            if state:
                state.status = AssetStatus.ONLINE
                state.last_updated = datetime.now(timezone.utc)

    def mark_offline(self, asset_id: str) -> None:
        """Mark an asset as offline."""
        with self._lock:
            state = self._states.get(asset_id)
            if state:
                state.status = AssetStatus.OFFLINE
                state.last_updated = datetime.now(timezone.utc)

    def mark_fault(self, asset_id: str, fault_description: str = "") -> None:
        """Mark an asset as faulted."""
        with self._lock:
            state = self._states.get(asset_id)
            if state:
                state.status = AssetStatus.FAULT
                if fault_description:
                    state.metadata["fault"] = fault_description
                state.last_updated = datetime.now(timezone.utc)
        logger.error("Asset %s faulted: %s", asset_id, fault_description)

    def stale_assets(self, max_age_seconds: float = 300.0) -> list[str]:
        """Return IDs of assets whose state has not been updated recently."""
        with self._lock:
            return [
                asset_id
                for asset_id, state in self._states.items()
                if state.is_stale(max_age_seconds)
            ]

    def __len__(self) -> int:
        with self._lock:
            return len(self._registrations)

    def __iter__(self) -> Iterator[AssetRegistration]:
        with self._lock:
            return iter(list(self._registrations.values()))

    def __contains__(self, asset_id: str) -> bool:
        with self._lock:
            return asset_id in self._registrations

    def summary(self) -> dict[str, Any]:
        """Return a summary dict for logging/monitoring."""
        with self._lock:
            type_counts: dict[str, int] = {}
            for r in self._registrations.values():
                type_counts[r.asset_type] = type_counts.get(r.asset_type, 0) + 1
            online_count = sum(
                1 for s in self._states.values()
                if s.status == AssetStatus.ONLINE
            )
            return {
                "total_assets": len(self._registrations),
                "online": online_count,
                "offline": len(self._registrations) - online_count,
                "by_type": type_counts,
                "total_capacity_mw": self.aggregate_capacity_mw(),
            }
