"""Modbus TCP protocol adapter for energy assets."""
from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Sequence


class FunctionCode(IntEnum):
    READ_COILS = 1
    READ_DISCRETE_INPUTS = 2
    READ_HOLDING_REGISTERS = 3
    READ_INPUT_REGISTERS = 4
    WRITE_SINGLE_COIL = 5
    WRITE_SINGLE_REGISTER = 6
    WRITE_MULTIPLE_COILS = 15
    WRITE_MULTIPLE_REGISTERS = 16


class ModbusException(Exception):
    """Raised when a Modbus error response is received."""

    def __init__(self, function_code: int, exception_code: int) -> None:
        self.function_code = function_code
        self.exception_code = exception_code
        codes = {
            1: "ILLEGAL_FUNCTION",
            2: "ILLEGAL_DATA_ADDRESS",
            3: "ILLEGAL_DATA_VALUE",
            4: "SERVER_DEVICE_FAILURE",
        }
        super().__init__(
            f"Modbus error FC={function_code:#04x} "
            f"exception={codes.get(exception_code, str(exception_code))}"
        )


@dataclass
class ModbusRequest:
    transaction_id: int
    unit_id: int
    function_code: FunctionCode
    address: int
    count: int = 1
    data: list[int] = field(default_factory=list)

    def to_bytes(self) -> bytes:
        if self.function_code in (
            FunctionCode.READ_COILS,
            FunctionCode.READ_DISCRETE_INPUTS,
            FunctionCode.READ_HOLDING_REGISTERS,
            FunctionCode.READ_INPUT_REGISTERS,
        ):
            pdu = struct.pack(">BHH", self.function_code, self.address, self.count)
        elif self.function_code == FunctionCode.WRITE_SINGLE_REGISTER:
            value = self.data[0] if self.data else 0
            pdu = struct.pack(">BHH", self.function_code, self.address, value)
        elif self.function_code == FunctionCode.WRITE_MULTIPLE_REGISTERS:
            byte_count = len(self.data) * 2
            pdu = struct.pack(
                f">BHHB{len(self.data)}H",
                self.function_code,
                self.address,
                len(self.data),
                byte_count,
                *self.data,
            )
        else:
            pdu = struct.pack(">BHH", self.function_code, self.address, self.count)
        # MBAP header: transaction_id(2) + protocol_id(2) + length(2) + unit_id(1)
        header = struct.pack(">HHHB", self.transaction_id, 0, len(pdu) + 1, self.unit_id)
        return header + pdu


class ModbusTCPClient:
    """
    Async Modbus TCP client implementing the MBAP framing protocol.

    Supports reading/writing holding registers, input registers, and coils.
    Thread-safe via asyncio lock for pipelined requests.
    """

    def __init__(self, host: str, port: int = 502, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._transaction_id: int = 0
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open a TCP connection to the Modbus server."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout,
        )

    def _next_tid(self) -> int:
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        return self._transaction_id

    async def _send_recv(self, request: ModbusRequest) -> bytes:
        assert self._writer is not None and self._reader is not None, "Not connected"
        async with self._lock:
            self._writer.write(request.to_bytes())
            await self._writer.drain()
            # Read 7-byte MBAP header
            header = await asyncio.wait_for(self._reader.readexactly(7), timeout=self.timeout)
            _tid, _proto, length, _uid = struct.unpack(">HHHB", header)
            # Read PDU (length includes unit_id byte already read)
            pdu = await asyncio.wait_for(
                self._reader.readexactly(length - 1), timeout=self.timeout
            )
            # Check for exception response (MSB set on function code)
            if pdu[0] & 0x80:
                raise ModbusException(pdu[0] & 0x7F, pdu[1] if len(pdu) > 1 else 0)
            return pdu

    async def read_holding_registers(
        self, address: int, count: int, unit_id: int = 1
    ) -> list[int]:
        """Read `count` holding registers starting at `address`."""
        req = ModbusRequest(
            transaction_id=self._next_tid(),
            unit_id=unit_id,
            function_code=FunctionCode.READ_HOLDING_REGISTERS,
            address=address,
            count=count,
        )
        pdu = await self._send_recv(req)
        byte_count = pdu[1]
        return list(struct.unpack(f">{byte_count // 2}H", pdu[2 : 2 + byte_count]))

    async def read_input_registers(
        self, address: int, count: int, unit_id: int = 1
    ) -> list[int]:
        """Read `count` input registers starting at `address`."""
        req = ModbusRequest(
            transaction_id=self._next_tid(),
            unit_id=unit_id,
            function_code=FunctionCode.READ_INPUT_REGISTERS,
            address=address,
            count=count,
        )
        pdu = await self._send_recv(req)
        byte_count = pdu[1]
        return list(struct.unpack(f">{byte_count // 2}H", pdu[2 : 2 + byte_count]))

    async def read_coils(
        self, address: int, count: int, unit_id: int = 1
    ) -> list[bool]:
        """Read `count` coil values starting at `address`."""
        req = ModbusRequest(
            transaction_id=self._next_tid(),
            unit_id=unit_id,
            function_code=FunctionCode.READ_COILS,
            address=address,
            count=count,
        )
        pdu = await self._send_recv(req)
        byte_count = pdu[1]
        raw = pdu[2 : 2 + byte_count]
        bits: list[bool] = []
        for byte in raw:
            for bit_pos in range(8):
                bits.append(bool(byte & (1 << bit_pos)))
        return bits[:count]

    async def write_register(self, address: int, value: int, unit_id: int = 1) -> bool:
        """Write a single holding register."""
        req = ModbusRequest(
            transaction_id=self._next_tid(),
            unit_id=unit_id,
            function_code=FunctionCode.WRITE_SINGLE_REGISTER,
            address=address,
            data=[value],
        )
        await self._send_recv(req)
        return True

    async def write_multiple_registers(
        self, address: int, values: Sequence[int], unit_id: int = 1
    ) -> bool:
        """Write multiple holding registers starting at `address`."""
        req = ModbusRequest(
            transaction_id=self._next_tid(),
            unit_id=unit_id,
            function_code=FunctionCode.WRITE_MULTIPLE_REGISTERS,
            address=address,
            count=len(values),
            data=list(values),
        )
        await self._send_recv(req)
        return True

    @staticmethod
    def registers_to_float32(regs: list[int]) -> float:
        """Convert two 16-bit registers to a 32-bit IEEE 754 float (big-endian)."""
        raw = struct.pack(">HH", regs[0], regs[1])
        return struct.unpack(">f", raw)[0]

    @staticmethod
    def float32_to_registers(value: float) -> tuple[int, int]:
        """Convert a 32-bit float to two 16-bit Modbus registers."""
        raw = struct.pack(">f", value)
        hi, lo = struct.unpack(">HH", raw)
        return hi, lo

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
