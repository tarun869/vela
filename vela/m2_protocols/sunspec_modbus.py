"""SunSpec Modbus implementation for solar inverters and battery storage."""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from vela.m2_protocols.modbus_tcp import ModbusTCPClient

logger = logging.getLogger(__name__)

# SunSpec "SunS" identifier at well-known Modbus register addresses
SUNSPEC_START_REGISTERS = [40000, 50000, 0]
SUNSPEC_IDENTIFIER = 0x53756E53  # "SunS" as big-endian uint32

# SunSpec model IDs (relevant subset for VPP)
SUNSPEC_MODELS = {
    1: "Common",
    101: "Inverter (single phase)",
    102: "Inverter (split phase)",
    103: "Inverter (three phase)",
    120: "Nameplate ratings",
    121: "Basic settings",
    122: "Measurements/Status",
    123: "Immediate controls",
    124: "Basic storage control",
    126: "Static volt-VAr",
    127: "Freq-Watt param",
    129: "High-frequency ride-through",
    130: "Low-frequency ride-through",
    131: "High-voltage ride-through",
    132: "Low-voltage ride-through",
    160: "Multiple MPPT inverter extension",
    701: "DER AC Measurement",
    702: "DER Capacity",
    703: "DER Enter Service",
    704: "DER AC Controls",
    705: "DER Volt-Watt",
    706: "DER Volt-VAr",
    707: "DER Freq-Watt",
    708: "DER Freq-Watt Curve",
    709: "DER Dynamic Reactive Current",
    710: "DER LVRT Must Trip",
    711: "DER HVRT Must Trip",
    712: "DER Trip LV Momentary Cessation",
    714: "DER Trip HV Momentary Cessation",
    715: "DER Frequency-Watt Curve",
    802: "Battery Base Model",
    803: "Li-Ion Battery Bank Model",
    804: "Lead-Acid Battery",
}


class SunSpecOperatingState(IntEnum):
    """SunSpec inverter operating states (model 101-103, register St)."""
    OFF = 1
    SLEEPING = 2
    STARTING = 3
    MPPT = 4      # Producing maximum power
    THROTTLED = 5
    SHUTTING_DOWN = 6
    FAULT = 7
    STANDBY = 8


class SunSpecBatteryStatus(IntEnum):
    """SunSpec battery status (model 802)."""
    OFF = 1
    STANDBY = 2
    INITIALIZING = 3
    CHARGING = 4
    DISCHARGING = 5
    COMPLETING = 6
    FULLY_CHARGED = 7
    WAITING = 8
    TESTING = 9


@dataclass
class SunSpecCommonModel:
    """SunSpec Model 1 — Common block (device identification)."""
    manufacturer: str = ""
    model: str = ""
    options: str = ""
    version: str = ""
    serial_number: str = ""
    device_address: int = 1


@dataclass
class SunSpecInverterModel:
    """SunSpec Model 101/103 — Single/Three-Phase Inverter status."""
    amps: float = 0.0               # AC current (A)
    voltage_ab: float = 0.0         # AC voltage L1 (V)
    voltage_bc: float = 0.0
    voltage_ca: float = 0.0
    ac_power_w: float = 0.0         # AC power output (W)
    frequency_hz: float = 60.0
    apparent_power_va: float = 0.0
    reactive_power_var: float = 0.0
    power_factor: float = 1.0
    energy_wh: float = 0.0          # Lifetime energy (Wh)
    dc_current_a: float = 0.0
    dc_voltage_v: float = 0.0
    dc_power_w: float = 0.0
    cabinet_temp_c: float = 25.0
    operating_state: SunSpecOperatingState = SunSpecOperatingState.MPPT
    vendor_state: int = 0


@dataclass
class SunSpecBasicStorage:
    """SunSpec Model 124 — Basic storage control."""
    wh_rating: float = 0.0          # Nameplate energy (Wh)
    wh_avail: float = 0.0           # Available energy (Wh)
    w_cha_max: float = 0.0          # Max charge rate (W)
    w_dis_max: float = 0.0          # Max discharge rate (W)
    cha_state: float = 0.0          # State of charge (%)
    stored_energy: float = 0.0      # Currently stored energy (Wh)
    cha_status: SunSpecBatteryStatus = SunSpecBatteryStatus.STANDBY
    # Setpoints
    w_cha_sf: int = 0               # Scale factor for W
    in_wp: float = 0.0              # Setpoint for charge power (W)
    out_wp: float = 0.0             # Setpoint for discharge power (W)


@dataclass
class SunSpecNameplate:
    """SunSpec Model 120 — Nameplate ratings."""
    wrtg: float = 0.0               # Watts rating
    va_rtg: float = 0.0             # VA rating
    var_rtg_q1: float = 0.0
    var_rtg_q4: float = 0.0
    ar_rtg_q1: float = 0.0          # Ampere rating
    wh_rtg: float = 0.0             # Wh rating (storage)
    ahr_rtg: float = 0.0            # Ah rating (storage)


class SunSpecClient:
    """
    SunSpec Modbus TCP client for solar inverters and battery storage.

    SunSpec builds a device model on top of Modbus holding registers.
    The device announces its supported models via a well-known register
    address and the "SunS" magic identifier.
    """

    def __init__(
        self,
        host: str,
        port: int = 502,
        unit_id: int = 1,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self._modbus = ModbusTCPClient(host, port, timeout)
        self._base_address: int = 40000
        self._model_offsets: dict[int, int] = {}  # model_id -> register offset
        logger.info("SunSpecClient initialized: %s:%s unit=%s", host, port, unit_id)

    async def connect(self) -> None:
        """Connect and discover the SunSpec model map."""
        await self._modbus.connect()
        await self._discover_models()

    async def _discover_models(self) -> None:
        """Locate the SunSpec base address and map all model offsets."""
        for base in SUNSPEC_START_REGISTERS:
            try:
                regs = await self._modbus.read_holding_registers(base, 2, self.unit_id)
                identifier = (regs[0] << 16) | regs[1]
                if identifier == SUNSPEC_IDENTIFIER:
                    self._base_address = base
                    logger.info("SunSpec identifier found at register %d", base)
                    await self._map_models(base + 2)
                    return
            except Exception:
                continue
        logger.warning("SunSpec identifier not found at any well-known address")

    async def _map_models(self, start: int) -> None:
        """Walk the SunSpec model list starting at `start`."""
        offset = start
        while True:
            try:
                header = await self._modbus.read_holding_registers(offset, 2, self.unit_id)
                model_id = header[0]
                model_len = header[1]
                if model_id == 0xFFFF:  # End marker
                    break
                self._model_offsets[model_id] = offset + 2
                model_name = SUNSPEC_MODELS.get(model_id, f"Unknown({model_id})")
                logger.debug("SunSpec model %d (%s) at offset %d", model_id, model_name, offset)
                offset += 2 + model_len
            except Exception:
                break
        logger.info("SunSpec discovered %d models", len(self._model_offsets))

    async def read_common(self) -> SunSpecCommonModel:
        """Read Model 1 (Common block) — device identification."""
        offset = self._model_offsets.get(1)
        if offset is None:
            return SunSpecCommonModel()
        try:
            regs = await self._modbus.read_holding_registers(offset, 65, self.unit_id)
            return SunSpecCommonModel(
                manufacturer=self._regs_to_str(regs[0:16]),
                model=self._regs_to_str(regs[16:32]),
                options=self._regs_to_str(regs[32:40]),
                version=self._regs_to_str(regs[40:48]),
                serial_number=self._regs_to_str(regs[48:64]),
                device_address=regs[64],
            )
        except Exception:
            logger.exception("SunSpec read_common failed")
            return SunSpecCommonModel()

    async def read_inverter(self, model_id: int = 103) -> SunSpecInverterModel:
        """Read Model 101/103 (Inverter status)."""
        offset = self._model_offsets.get(model_id) or self._model_offsets.get(101)
        if offset is None:
            return SunSpecInverterModel()
        try:
            regs = await self._modbus.read_holding_registers(offset, 50, self.unit_id)
            # Scale factors are at the end of the block
            a_sf = self._to_signed16(regs[39])
            v_sf = self._to_signed16(regs[40])
            w_sf = self._to_signed16(regs[41])
            hz_sf = self._to_signed16(regs[42])
            wh_sf = self._to_signed16(regs[43])
            return SunSpecInverterModel(
                amps=regs[0] * (10 ** a_sf),
                voltage_ab=regs[3] * (10 ** v_sf),
                voltage_bc=regs[4] * (10 ** v_sf),
                voltage_ca=regs[5] * (10 ** v_sf),
                ac_power_w=self._to_signed16(regs[13]) * (10 ** w_sf),
                frequency_hz=regs[14] * (10 ** hz_sf),
                apparent_power_va=self._to_signed16(regs[15]) * (10 ** w_sf),
                reactive_power_var=self._to_signed16(regs[16]) * (10 ** w_sf),
                energy_wh=(regs[23] << 16 | regs[24]) * (10 ** wh_sf),
                dc_current_a=regs[25] * (10 ** a_sf),
                dc_voltage_v=regs[26] * (10 ** v_sf),
                dc_power_w=self._to_signed16(regs[27]) * (10 ** w_sf),
                cabinet_temp_c=self._to_signed16(regs[32]) * 0.1,
                operating_state=SunSpecOperatingState(regs[39] if regs[39] in range(1, 9) else 8),
            )
        except Exception:
            logger.exception("SunSpec read_inverter failed")
            return SunSpecInverterModel()

    async def read_storage(self) -> SunSpecBasicStorage:
        """Read Model 124 (Basic storage control)."""
        offset = self._model_offsets.get(124)
        if offset is None:
            return SunSpecBasicStorage()
        try:
            regs = await self._modbus.read_holding_registers(offset, 24, self.unit_id)
            wh_sf = self._to_signed16(regs[20])
            w_sf = self._to_signed16(regs[21])
            return SunSpecBasicStorage(
                wh_rating=regs[0] * (10 ** wh_sf),
                wh_avail=regs[1] * (10 ** wh_sf),
                w_cha_max=regs[2] * (10 ** w_sf),
                w_dis_max=regs[3] * (10 ** w_sf),
                cha_state=regs[5] * 0.1,
                stored_energy=regs[6] * (10 ** wh_sf),
                cha_status=SunSpecBatteryStatus(regs[9] if regs[9] in range(1, 10) else 2),
            )
        except Exception:
            logger.exception("SunSpec read_storage failed")
            return SunSpecBasicStorage()

    async def write_storage_setpoint(
        self, charge_power_w: float | None = None, discharge_power_w: float | None = None
    ) -> bool:
        """
        Write charge/discharge power setpoints to Model 124.

        Positive = charge, negative or use discharge_power_w = discharge.
        """
        offset = self._model_offsets.get(124)
        if offset is None:
            return False
        try:
            if charge_power_w is not None:
                # InWRte and OutWRte registers
                await self._modbus.write_register(
                    offset + 13,  # InWRte
                    max(0, min(100, int(charge_power_w / 100))),
                    self.unit_id,
                )
            if discharge_power_w is not None:
                await self._modbus.write_register(
                    offset + 14,  # OutWRte
                    max(0, min(100, int(discharge_power_w / 100))),
                    self.unit_id,
                )
            return True
        except Exception:
            logger.exception("SunSpec write_storage_setpoint failed")
            return False

    async def write_inverter_watt_setpoint(self, power_w: float) -> bool:
        """Write an immediate real-power setpoint to Model 123 (Immediate controls)."""
        offset = self._model_offsets.get(123)
        if offset is None:
            return False
        try:
            # WMaxLimPct register: percentage of nameplate (0-100 scaled by 100 → 10000=100%)
            pct = max(0, min(10000, int(abs(power_w) / 100)))
            await self._modbus.write_register(offset, pct, self.unit_id)
            # Enable WMaxLim_Ena (register offset + 13)
            await self._modbus.write_register(offset + 13, 1, self.unit_id)
            return True
        except Exception:
            logger.exception("SunSpec write_inverter_watt_setpoint failed")
            return False

    @staticmethod
    def _regs_to_str(regs: list[int]) -> str:
        raw = b"".join(struct.pack(">H", r) for r in regs)
        return raw.rstrip(b"\x00").decode("ascii", errors="replace").strip()

    @staticmethod
    def _to_signed16(value: int) -> int:
        if value >= 0x8000:
            return value - 0x10000
        return value

    async def close(self) -> None:
        await self._modbus.close()
