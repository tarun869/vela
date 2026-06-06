"""
SCADA system integration bridge for VPP real-time data acquisition.

Abstracts Modbus TCP, DNP3, and IEC 61850 protocol differences into
a unified telemetry model for VPP core data consumption.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class ProtocolType(str, Enum):
    MODBUS_TCP = "modbus_tcp"
    DNP3 = "dnp3"
    IEC61850 = "iec61850"
    OPC_UA = "opc_ua"
    REST = "rest"


@dataclass
class SCADAPoint:
    point_id: str
    description: str
    data_type: str        # "float", "bool", "int"
    address: str          # Modbus register, DNP3 index, OPC node ID
    scale_factor: float = 1.0
    unit: str = ""


@dataclass
class Telemetry:
    point_id: str
    value: Any
    quality: str          # "good", "bad", "uncertain"
    timestamp: float = field(default_factory=time.time)
    source_id: str = ""


@dataclass
class SCADADevice:
    device_id: str
    hostname: str
    port: int
    protocol: ProtocolType
    points: List[SCADAPoint] = field(default_factory=list)
    poll_interval_s: float = 5.0
    timeout_s: float = 3.0


class SCADABridge:
    """
    Unified SCADA integration layer supporting multiple protocols.

    In production, uses pymodbus, dnp3-python, or opcua library.
    Here, implements simulation mode for testing.
    """

    def __init__(self) -> None:
        self._devices: Dict[str, SCADADevice] = {}
        self._telemetry_cache: Dict[str, Telemetry] = {}
        self._callbacks: List[Callable[[Telemetry], None]] = []
        self._simulation_mode = True

    def register_device(self, device: SCADADevice) -> None:
        self._devices[device.device_id] = device

    def on_telemetry(self, callback: Callable[[Telemetry], None]) -> None:
        self._callbacks.append(callback)

    def poll(self, device_id: str) -> List[Telemetry]:
        """
        Poll all points from a device.

        Simulation mode generates realistic values for battery/solar assets.
        """
        device = self._devices.get(device_id)
        if not device:
            return []

        results: List[Telemetry] = []
        import random
        for point in device.points:
            if self._simulation_mode:
                if point.data_type == "float":
                    raw = random.gauss(50.0, 5.0) * point.scale_factor
                elif point.data_type == "bool":
                    raw = random.choice([True, False])
                else:
                    raw = random.randint(0, 100)
                quality = "good"
            else:
                raw = 0.0
                quality = "uncertain"

            t = Telemetry(point_id=point.point_id, value=raw, quality=quality,
                          source_id=device_id)
            self._telemetry_cache[point.point_id] = t
            results.append(t)
            for cb in self._callbacks:
                try:
                    cb(t)
                except Exception:
                    pass

        return results

    def write_setpoint(self, device_id: str, point_id: str, value: float) -> bool:
        """Write a setpoint to a SCADA point (control action)."""
        device = self._devices.get(device_id)
        if not device:
            return False
        # Simulation: log the write and return success
        t = Telemetry(point_id=point_id, value=value, quality="good", source_id=device_id)
        self._telemetry_cache[point_id] = t
        return True

    def latest(self, point_id: str) -> Optional[Telemetry]:
        return self._telemetry_cache.get(point_id)
