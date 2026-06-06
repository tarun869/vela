"""DNP3 (Distributed Network Protocol 3) protocol implementation for energy assets."""
from __future__ import annotations

import asyncio
import struct
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Any

logger = logging.getLogger(__name__)

# DNP3 default port
DNP3_PORT = 20000

# DNP3 Start bytes
DNP3_START = b"\x05\x64"


class FunctionCode(IntEnum):
    """DNP3 Application Layer function codes."""
    CONFIRM = 0x00
    READ = 0x01
    WRITE = 0x02
    SELECT = 0x03
    OPERATE = 0x04
    DIRECT_OPERATE = 0x05
    DIRECT_OPERATE_NR = 0x06
    FREEZE = 0x07
    FREEZE_NR = 0x08
    FREEZE_CLEAR = 0x09
    FREEZE_AT_TIME = 0x0A
    COLD_RESTART = 0x0D
    WARM_RESTART = 0x0E
    INITIALIZE_APPLICATION = 0x10
    RESPONSE = 0x81
    UNSOLICITED_RESPONSE = 0x82
    AUTHENTICATE_REQUEST = 0xC0


class GroupVariation(IntEnum):
    """DNP3 object group/variation pairs encoded as (group << 8 | variation)."""
    # Binary inputs
    BINARY_INPUT_ALL = 0x0100
    BINARY_INPUT_PACKED = 0x0101
    BINARY_INPUT_FLAG = 0x0102
    # Binary outputs
    BINARY_OUTPUT_STATUS = 0x0A02
    BINARY_OUTPUT_CONTROL = 0x0C01
    # Analog inputs
    ANALOG_INPUT_ALL = 0x1E00
    ANALOG_INPUT_32BIT = 0x1E01
    ANALOG_INPUT_FLOAT = 0x1E05
    # Analog output
    ANALOG_OUTPUT_STATUS = 0x2800
    ANALOG_OUTPUT_FLOAT = 0x2901
    # Counters
    COUNTER_32BIT = 0x1401
    # Time
    TIME_DATE = 0x3301


@dataclass
class BinaryInput:
    index: int
    value: bool
    online: bool = True
    restart: bool = False
    comm_lost: bool = False


@dataclass
class AnalogInput:
    index: int
    value: float
    online: bool = True
    overflow: bool = False
    comm_lost: bool = False


@dataclass
class AnalogOutput:
    index: int
    value: float
    status_code: int = 0  # 0=SUCCESS


@dataclass
class BinaryOutput:
    index: int
    value: bool
    status_code: int = 0


class DNP3Frame:
    """Represents a DNP3 Data Link Layer frame."""

    def __init__(
        self,
        destination: int,
        source: int,
        function_code: FunctionCode,
        payload: bytes = b"",
    ) -> None:
        self.destination = destination
        self.source = source
        self.function_code = function_code
        self.payload = payload

    def serialize(self) -> bytes:
        """Serialize to DNP3 Data Link Layer frame bytes."""
        # Application layer PDU
        app_pdu = bytes([0xC0, int(self.function_code)]) + self.payload
        # Transport layer wrapping
        transport = bytes([0xC0]) + app_pdu  # FIR+FIN set
        # Data Link header: start(2) + length(1) + ctrl(1) + dest(2) + src(2)
        ctrl = 0x44  # DIR=0, PRM=1, FCB=0, FCV=0, FC=4 (UNCONFIRMED_USER_DATA)
        length = 5 + len(transport)  # header bytes after length field
        header = DNP3_START + struct.pack("<BBHH", length, ctrl, self.destination, self.source)
        # Append CRC (simplified: last 2 bytes)
        frame = header + transport
        crc = self._crc16(frame)
        return frame + struct.pack("<H", crc)

    @staticmethod
    def _crc16(data: bytes) -> int:
        """DNP3 CRC-16 (CRC-CCITT polynomial 0x3D65)."""
        crc = 0x0000
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA6BC
                else:
                    crc >>= 1
        return crc ^ 0xFFFF


class DNP3Client:
    """
    Async DNP3 master station client.

    Implements direct operate, select-before-operate, and polling
    patterns used for SCADA communication with energy storage assets.
    """

    def __init__(
        self,
        host: str,
        port: int = DNP3_PORT,
        master_addr: int = 1,
        outstation_addr: int = 10,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.master_addr = master_addr
        self.outstation_addr = outstation_addr
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._unsolicited_handlers: list[Callable[[bytes], None]] = []
        self._sequence = 0

    async def connect(self) -> None:
        """Establish a TCP connection to the DNP3 outstation."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout,
        )
        logger.info("DNP3 connected to %s:%s (outstation=%s)", self.host, self.port, self.outstation_addr)

    def _next_seq(self) -> int:
        self._sequence = (self._sequence + 1) & 0x0F
        return self._sequence

    async def read_class_0(self) -> bytes:
        """
        Send a Class 0 (static data) poll to the outstation.

        Returns the raw response payload for downstream parsing.
        """
        # Object header: Group 60 Var 1 (All static data)
        obj_header = bytes([0x3C, 0x01, 0x06])  # g60v1, qualifier=ALL
        frame = DNP3Frame(
            destination=self.outstation_addr,
            source=self.master_addr,
            function_code=FunctionCode.READ,
            payload=obj_header,
        )
        assert self._writer is not None
        self._writer.write(frame.serialize())
        await self._writer.drain()
        assert self._reader is not None
        return await asyncio.wait_for(self._reader.read(4096), timeout=self.timeout)

    async def direct_operate_binary(
        self, index: int, value: bool
    ) -> bool:
        """
        Direct Operate a binary output (e.g., circuit breaker, relay).

        Returns True if the outstation acknowledges the command.
        """
        # CROB: Control Relay Output Block
        # TCC=0, Count=1, OnTime=100ms, OffTime=100ms, Status=0
        tcc_code = 0x03 if value else 0x04  # LATCH_ON / LATCH_OFF
        crob = struct.pack("<BBHHHB", tcc_code, 1, 100, 100, 0, 0)
        # Object header: Group 12 Var 1, index prefix, single object
        obj_header = (
            bytes([0x0C, 0x01, 0x28])  # g12v1, qualifier=1-byte-index
            + struct.pack("<B", index)
            + crob
        )
        frame = DNP3Frame(
            destination=self.outstation_addr,
            source=self.master_addr,
            function_code=FunctionCode.DIRECT_OPERATE,
            payload=obj_header,
        )
        assert self._writer is not None
        self._writer.write(frame.serialize())
        await self._writer.drain()
        assert self._reader is not None
        resp = await asyncio.wait_for(self._reader.read(1024), timeout=self.timeout)
        # Check response function code (0x81 = response, check for success)
        return len(resp) > 10 and resp[11] == 0x81

    async def direct_operate_analog(
        self, index: int, value: float
    ) -> bool:
        """
        Direct Operate an analog output (e.g., set-point for power output in MW).
        """
        # Group 41 Var 3 (Analog Output Float32)
        packed_value = struct.pack("<f", value)
        obj_header = (
            bytes([0x29, 0x03, 0x28])  # g41v3, qualifier=1-byte-index
            + struct.pack("<B", index)
            + packed_value
            + bytes([0x00])  # status byte
        )
        frame = DNP3Frame(
            destination=self.outstation_addr,
            source=self.master_addr,
            function_code=FunctionCode.DIRECT_OPERATE,
            payload=obj_header,
        )
        assert self._writer is not None
        self._writer.write(frame.serialize())
        await self._writer.drain()
        assert self._reader is not None
        resp = await asyncio.wait_for(self._reader.read(1024), timeout=self.timeout)
        return len(resp) > 10 and resp[11] == 0x81

    async def select_before_operate_analog(
        self, index: int, value: float
    ) -> bool:
        """
        Select-Before-Operate (SBO) for an analog output.

        SBO is the safer two-step command used for critical controls.
        """
        packed_value = struct.pack("<f", value)
        obj_header = (
            bytes([0x29, 0x03, 0x28])
            + struct.pack("<B", index)
            + packed_value
            + bytes([0x00])
        )
        select_frame = DNP3Frame(
            destination=self.outstation_addr,
            source=self.master_addr,
            function_code=FunctionCode.SELECT,
            payload=obj_header,
        )
        assert self._writer is not None
        self._writer.write(select_frame.serialize())
        await self._writer.drain()
        assert self._reader is not None
        select_resp = await asyncio.wait_for(self._reader.read(1024), timeout=self.timeout)
        if not (len(select_resp) > 10 and select_resp[11] == 0x81):
            return False
        # Now operate
        return await self.direct_operate_analog(index, value)

    def register_unsolicited_handler(self, handler: Callable[[bytes], None]) -> None:
        """Register a callback invoked when an unsolicited response arrives."""
        self._unsolicited_handlers.append(handler)

    async def listen_unsolicited(self) -> None:
        """Continuously listen for unsolicited responses from the outstation."""
        assert self._reader is not None
        while True:
            try:
                data = await self._reader.read(4096)
                if not data:
                    break
                # Check if it's an unsolicited response (FC=0x82)
                if len(data) > 12 and data[12] == 0x82:
                    for handler in self._unsolicited_handlers:
                        try:
                            handler(data)
                        except Exception:
                            logger.exception("Unsolicited handler error")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("DNP3 unsolicited listen error")
                break

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
