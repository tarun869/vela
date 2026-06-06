"""IEC 61850 GOOSE and MMS protocol implementation for substation automation."""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable

logger = logging.getLogger(__name__)

# MMS default port
MMS_PORT = 102
# GOOSE uses Ethertype 0x88B8 (raw Ethernet, not TCP)
GOOSE_ETHERTYPE = 0x88B8


class MMSServiceCode(IntEnum):
    """MMS (Manufacturing Message Specification) service codes per IEC 61850-8-1."""
    INITIATE = 0x01
    CONFIRMED_REQUEST = 0x00
    CONFIRMED_RESPONSE = 0x80
    CONFIRMED_ERROR = 0x40
    UNCONFIRMED = 0x20
    REJECT = 0x30
    CANCEL = 0x10
    STATUS_REQUEST = 0x00
    READ = 0xA4
    WRITE = 0xA5
    GET_NAME_LIST = 0xA1
    GET_VARIABLE_ACCESS_ATTRIBUTES = 0xA9
    DEFINE_NAMED_VARIABLE_LIST = 0xAB
    GET_NAMED_VARIABLE_LIST_ATTRIBUTES = 0xAC
    DELETE_NAMED_VARIABLE_LIST = 0xAD


class IEC61850Quality(IntEnum):
    """IEC 61850 data attribute quality bits."""
    VALIDITY_GOOD = 0x00
    VALIDITY_INVALID = 0x01
    VALIDITY_RESERVED = 0x02
    VALIDITY_QUESTIONABLE = 0x03
    OVERFLOW = 0x04
    OUT_OF_RANGE = 0x08
    BAD_REFERENCE = 0x10
    OSCILLATORY = 0x20
    FAILURE = 0x40
    OLD_DATA = 0x80
    INCONSISTENT = 0x100
    INACCURATE = 0x200
    SOURCE_SUBSTITUTED = 0x400
    TEST = 0x800
    OPERATOR_BLOCKED = 0x1000


@dataclass
class IEC61850Value:
    """A value read from an IEC 61850 data attribute."""
    logical_node: str       # e.g., "MMXU1"
    data_object: str        # e.g., "PhV"
    data_attribute: str     # e.g., "phsA.cVal.mag.f"
    value: Any
    quality: IEC61850Quality = IEC61850Quality.VALIDITY_GOOD
    timestamp: float = field(default_factory=time.time)

    @property
    def reference(self) -> str:
        return f"{self.logical_node}/{self.data_object}.{self.data_attribute}"


@dataclass
class GOOSEMessage:
    """
    GOOSE (Generic Object Oriented Substation Event) message.

    GOOSE messages are published over raw Ethernet multicast and carry
    protection relay trip signals, interlocking states, and alarms.
    """
    app_id: int             # Application ID (0x0000–0x3FFF)
    gocb_ref: str           # GOOSE Control Block reference
    time_allowed_to_live: int  # ms
    dat_set: str            # Dataset reference
    go_id: str              # GOOSE ID
    sq_num: int             # Sequence number (increments on state change)
    st_num: int             # Status number (increments on each state change)
    test: bool              # Test flag
    conf_rev: int           # Config revision
    nds_com: bool           # Needs commissioning
    entries: list[Any] = field(default_factory=list)  # Dataset values

    def serialize_header(self) -> bytes:
        """Serialize the GOOSE PDU header (simplified, without full ASN.1 BER)."""
        # APPID (2) + Length (2) + Reserved1 (2) + Reserved2 (2)
        header = struct.pack(">HHHH", self.app_id, 8, 0x0000, 0x0000)
        return header

    @classmethod
    def trip_command(cls, app_id: int, go_id: str, trip: bool) -> "GOOSEMessage":
        """Factory method for a protection trip GOOSE message."""
        return cls(
            app_id=app_id,
            gocb_ref=f"PROT/LLN0$GO${go_id}",
            time_allowed_to_live=2000,
            dat_set=f"PROT/LLN0$GOOSE_Outputs",
            go_id=go_id,
            sq_num=0,
            st_num=1,
            test=False,
            conf_rev=1,
            nds_com=False,
            entries=[trip],
        )


class MMSClient:
    """
    MMS (Manufacturing Message Specification) client for IEC 61850.

    Used to read/write Logical Node data attributes in IEDs (Intelligent
    Electronic Devices) such as relays, meters, and bay controllers.
    """

    def __init__(
        self, host: str, port: int = MMS_PORT, timeout: float = 10.0
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._invoke_id = 0

    async def connect(self) -> None:
        """Establish MMS connection over TCP/COTP/OSI stack (simplified)."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout,
        )
        # Send MMS Initiate request
        await self._initiate()
        logger.info("MMS connected to %s:%s", self.host, self.port)

    async def _initiate(self) -> None:
        """Send MMS Initiate PDU to negotiate connection parameters."""
        # Simplified COTP + MMS initiate (real implementation uses full OSI stack)
        initiate_pdu = bytes([
            0x03, 0x00, 0x00, 0x1D,  # TPKT header
            0x02, 0xF0, 0x80,         # COTP CR
            0x00, 0x01,               # PDU type = initiate-RequestPDU
            0x00, 0xFD,               # proposed-max-SPDU-len
            0x00, 0x01,               # proposed-SPDU-version
        ])
        if self._writer:
            self._writer.write(initiate_pdu)
            await self._writer.drain()
            if self._reader:
                await asyncio.wait_for(self._reader.read(256), timeout=self.timeout)

    def _next_invoke_id(self) -> int:
        self._invoke_id = (self._invoke_id + 1) & 0xFFFF
        return self._invoke_id

    async def read(self, reference: str) -> IEC61850Value:
        """
        Read a data attribute by IEC 61850 reference string.

        Reference format: IEDName/LogicalDevice/LogicalNode.DataObject.DataAttribute
        e.g., "IED1/PROT/MMXU1.PhV.phsA.cVal.mag.f"
        """
        parts = reference.split("/", 2)
        if len(parts) < 2:
            raise ValueError(f"Invalid IEC 61850 reference: {reference}")

        ln_and_da = parts[-1]
        ln_parts = ln_and_da.split(".", 1)
        logical_node = ln_parts[0]
        da = ln_parts[1] if len(ln_parts) > 1 else ""

        # Build MMS Read request PDU
        invoke_id = self._next_invoke_id()
        ref_bytes = reference.encode("ascii")
        read_pdu = (
            bytes([MMSServiceCode.CONFIRMED_REQUEST, 0x00, invoke_id & 0xFF])
            + bytes([MMSServiceCode.READ])
            + struct.pack(">H", len(ref_bytes))
            + ref_bytes
        )

        if self._writer:
            self._writer.write(read_pdu)
            await self._writer.drain()

        if self._reader:
            resp = await asyncio.wait_for(self._reader.read(1024), timeout=self.timeout)
            value = self._parse_mms_value(resp)
        else:
            value = 0.0

        return IEC61850Value(
            logical_node=logical_node,
            data_object=ln_parts[0].split("/")[-1] if "/" in ln_parts[0] else "",
            data_attribute=da,
            value=value,
        )

    def _parse_mms_value(self, data: bytes) -> Any:
        """Parse an MMS response PDU and extract the typed value."""
        if len(data) < 8:
            return None
        # Simplified: extract float32 from offset 6 if present
        try:
            if data[5] == 0x9:  # MMS floating-point type tag
                return struct.unpack(">f", data[6:10])[0]
            elif data[5] == 0x3:  # boolean
                return bool(data[6])
            elif data[5] == 0x5:  # integer
                return struct.unpack(">i", data[6:10])[0]
        except struct.error:
            pass
        return None

    async def write(self, reference: str, value: Any) -> bool:
        """
        Write a data attribute by IEC 61850 reference string.

        Returns True on success.
        """
        invoke_id = self._next_invoke_id()
        ref_bytes = reference.encode("ascii")

        if isinstance(value, float):
            val_bytes = bytes([0x09, 0x08]) + struct.pack(">f", value)
        elif isinstance(value, bool):
            val_bytes = bytes([0x83, 0x01, 0x01 if value else 0x00])
        elif isinstance(value, int):
            val_bytes = bytes([0x85, 0x04]) + struct.pack(">i", value)
        else:
            return False

        write_pdu = (
            bytes([MMSServiceCode.CONFIRMED_REQUEST, 0x00, invoke_id & 0xFF])
            + bytes([MMSServiceCode.WRITE])
            + struct.pack(">H", len(ref_bytes))
            + ref_bytes
            + val_bytes
        )

        if self._writer:
            self._writer.write(write_pdu)
            await self._writer.drain()
            if self._reader:
                resp = await asyncio.wait_for(self._reader.read(256), timeout=self.timeout)
                return len(resp) > 5 and resp[4] == MMSServiceCode.CONFIRMED_RESPONSE
        return False

    async def get_logical_nodes(self, logical_device: str) -> list[str]:
        """List all logical nodes in a logical device via GetNameList."""
        invoke_id = self._next_invoke_id()
        ld_bytes = logical_device.encode("ascii")
        pdu = (
            bytes([MMSServiceCode.CONFIRMED_REQUEST, 0x00, invoke_id & 0xFF])
            + bytes([MMSServiceCode.GET_NAME_LIST])
            + struct.pack(">H", len(ld_bytes))
            + ld_bytes
        )
        if self._writer and self._reader:
            self._writer.write(pdu)
            await self._writer.drain()
            resp = await asyncio.wait_for(self._reader.read(2048), timeout=self.timeout)
            return self._parse_name_list(resp)
        return []

    def _parse_name_list(self, data: bytes) -> list[str]:
        names: list[str] = []
        i = 8  # skip TPKT + COTP + MMS header
        while i < len(data) - 2:
            length = data[i]
            name = data[i + 1 : i + 1 + length].decode("ascii", errors="ignore")
            if name:
                names.append(name)
            i += length + 1
        return names

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass


class GOOSEPublisher:
    """
    GOOSE publisher for protection and interlocking signals.

    In production, GOOSE runs over raw Ethernet (not IP), requiring
    a raw socket with CAP_NET_RAW capability. This class provides
    the message serialization logic.
    """

    def __init__(
        self,
        interface: str,
        multicast_mac: str = "01:0c:cd:01:00:01",
    ) -> None:
        self.interface = interface
        self.multicast_mac = multicast_mac
        self._sq_num = 0
        self._st_num = 0
        self._subscribers: list[Callable[[GOOSEMessage], None]] = []

    def build_trip_message(
        self,
        go_id: str,
        trip: bool,
        app_id: int = 0x1000,
    ) -> GOOSEMessage:
        """Build a trip command GOOSE message."""
        if trip:
            self._st_num += 1
            self._sq_num = 0
        else:
            self._sq_num += 1

        return GOOSEMessage(
            app_id=app_id,
            gocb_ref=f"PROT/LLN0$GO${go_id}",
            time_allowed_to_live=2000,
            dat_set="PROT/LLN0$GOOSE_Outputs",
            go_id=go_id,
            sq_num=self._sq_num,
            st_num=self._st_num,
            test=False,
            conf_rev=1,
            nds_com=False,
            entries=[trip],
        )

    def subscribe(self, handler: Callable[[GOOSEMessage], None]) -> None:
        """Register a subscriber for incoming GOOSE messages."""
        self._subscribers.append(handler)

    def dispatch(self, msg: GOOSEMessage) -> None:
        """Deliver a parsed GOOSE message to all subscribers."""
        for handler in self._subscribers:
            try:
                handler(msg)
            except Exception:
                logger.exception("GOOSE subscriber error")
