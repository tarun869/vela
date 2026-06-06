"""MQTT protocol adapter for IoT telemetry from energy assets."""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable

logger = logging.getLogger(__name__)

MQTT_PORT = 1883
MQTT_TLS_PORT = 8883

# MQTT fixed header control packet types
CONNECT = 0x10
CONNACK = 0x20
PUBLISH = 0x30
PUBACK = 0x40
SUBSCRIBE = 0x82
SUBACK = 0x90
UNSUBSCRIBE = 0xA2
UNSUBACK = 0xB0
PINGREQ = 0xC0
PINGRESP = 0xD0
DISCONNECT = 0xE0


class QoS(IntEnum):
    AT_MOST_ONCE = 0
    AT_LEAST_ONCE = 1
    EXACTLY_ONCE = 2


@dataclass
class MQTTMessage:
    topic: str
    payload: bytes
    qos: QoS = QoS.AT_MOST_ONCE
    retain: bool = False
    message_id: int = 0

    @property
    def payload_json(self) -> Any:
        return json.loads(self.payload.decode("utf-8"))

    @property
    def payload_str(self) -> str:
        return self.payload.decode("utf-8")


@dataclass
class TelemetryFrame:
    """Structured telemetry frame from an energy asset over MQTT."""
    asset_id: str
    timestamp: float
    power_mw: float
    soc_pct: float | None = None
    voltage_kv: float | None = None
    current_a: float | None = None
    temperature_c: float | None = None
    frequency_hz: float | None = None
    alarms: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mqtt_message(cls, msg: MQTTMessage) -> "TelemetryFrame":
        """Parse a TelemetryFrame from a standard Vela MQTT telemetry message."""
        data = msg.payload_json
        return cls(
            asset_id=data.get("asset_id", ""),
            timestamp=data.get("ts", time.time()),
            power_mw=float(data.get("power_mw", 0.0)),
            soc_pct=data.get("soc_pct"),
            voltage_kv=data.get("voltage_kv"),
            current_a=data.get("current_a"),
            temperature_c=data.get("temperature_c"),
            frequency_hz=data.get("frequency_hz"),
            alarms=data.get("alarms", []),
            raw=data,
        )


class MQTTClient:
    """
    Minimal async MQTT 3.1.1 client.

    Implements CONNECT, PUBLISH, SUBSCRIBE, PING keepalive.
    Suitable for VPP telemetry ingestion and dispatch signaling via MQTT.
    """

    def __init__(
        self,
        host: str,
        port: int = MQTT_PORT,
        client_id: str = "vela-vpp",
        username: str = "",
        password: str = "",
        keepalive: int = 60,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.username = username
        self.password = password
        self.keepalive = keepalive
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._packet_id = 0
        self._subscriptions: dict[str, list[Callable[[MQTTMessage], None]]] = {}
        self._running = False
        self._ping_task: asyncio.Task[None] | None = None
        self._recv_task: asyncio.Task[None] | None = None

    def _next_pid(self) -> int:
        self._packet_id = (self._packet_id + 1) & 0xFFFF
        return self._packet_id

    @staticmethod
    def _encode_string(s: str) -> bytes:
        b = s.encode("utf-8")
        return struct.pack(">H", len(b)) + b

    @staticmethod
    def _encode_remaining(n: int) -> bytes:
        result = bytearray()
        while True:
            byte = n % 128
            n //= 128
            if n > 0:
                byte |= 0x80
            result.append(byte)
            if n == 0:
                break
        return bytes(result)

    async def connect(self) -> None:
        """Connect to the MQTT broker and send CONNECT packet."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout,
        )
        # Build CONNECT variable header
        var_header = (
            self._encode_string("MQTT")  # Protocol name
            + bytes([0x04])              # Protocol level (3.1.1)
        )
        connect_flags = 0x02  # Clean session
        if self.username:
            connect_flags |= 0x80
        if self.password:
            connect_flags |= 0x40
        var_header += bytes([connect_flags])
        var_header += struct.pack(">H", self.keepalive)

        # Payload: client_id (required), username, password
        payload = self._encode_string(self.client_id)
        if self.username:
            payload += self._encode_string(self.username)
        if self.password:
            payload += self._encode_string(self.password)

        remaining = var_header + payload
        packet = bytes([CONNECT]) + self._encode_remaining(len(remaining)) + remaining
        self._writer.write(packet)
        await self._writer.drain()

        # Read CONNACK
        resp = await asyncio.wait_for(self._reader.read(4), timeout=self.timeout)
        if len(resp) < 4 or resp[0] != CONNACK:
            raise ConnectionError("MQTT CONNACK not received")
        if resp[3] != 0:
            codes = {
                1: "Unacceptable protocol version",
                2: "Identifier rejected",
                3: "Server unavailable",
                4: "Bad credentials",
                5: "Not authorized",
            }
            raise ConnectionError(f"MQTT connection refused: {codes.get(resp[3], str(resp[3]))}")

        self._running = True
        self._ping_task = asyncio.create_task(self._keepalive_loop())
        self._recv_task = asyncio.create_task(self._receive_loop())
        logger.info("MQTT connected to %s:%s (client_id=%s)", self.host, self.port, self.client_id)

    async def subscribe(
        self,
        topic: str,
        callback: Callable[[MQTTMessage], None],
        qos: QoS = QoS.AT_MOST_ONCE,
    ) -> None:
        """Subscribe to a topic with a callback."""
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
            # Send SUBSCRIBE packet
            pid = self._next_pid()
            topic_bytes = self._encode_string(topic)
            payload = struct.pack(">H", pid) + topic_bytes + bytes([int(qos)])
            packet = bytes([SUBSCRIBE]) + self._encode_remaining(len(payload)) + payload
            if self._writer:
                self._writer.write(packet)
                await self._writer.drain()
        self._subscriptions[topic].append(callback)
        logger.debug("MQTT subscribed to %s", topic)

    async def publish(
        self,
        topic: str,
        payload: bytes | str | dict[str, Any],
        qos: QoS = QoS.AT_MOST_ONCE,
        retain: bool = False,
    ) -> None:
        """Publish a message to a topic."""
        if isinstance(payload, dict):
            raw = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, str):
            raw = payload.encode("utf-8")
        else:
            raw = payload

        topic_bytes = self._encode_string(topic)
        fixed = PUBLISH | (int(qos) << 1) | (0x01 if retain else 0x00)
        var_header = topic_bytes
        if qos > QoS.AT_MOST_ONCE:
            var_header += struct.pack(">H", self._next_pid())
        remaining = var_header + raw
        packet = bytes([fixed]) + self._encode_remaining(len(remaining)) + remaining
        if self._writer:
            self._writer.write(packet)
            await self._writer.drain()

    async def _receive_loop(self) -> None:
        """Continuously receive and dispatch incoming MQTT packets."""
        while self._running and self._reader:
            try:
                first_byte = await self._reader.read(1)
                if not first_byte:
                    break
                pkt_type = first_byte[0] & 0xF0
                # Read variable-length remaining length
                multiplier = 1
                remaining_len = 0
                while True:
                    byte = await self._reader.read(1)
                    if not byte:
                        break
                    remaining_len += (byte[0] & 0x7F) * multiplier
                    multiplier *= 128
                    if not (byte[0] & 0x80):
                        break
                if remaining_len == 0:
                    continue
                data = await self._reader.readexactly(remaining_len)
                if pkt_type == PUBLISH:
                    await self._handle_publish(first_byte[0], data)
                elif pkt_type == PUBACK:
                    pass  # QoS 1 acknowledgment
                elif pkt_type == PINGRESP:
                    logger.debug("MQTT PINGRESP received")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("MQTT receive error")
                break

    async def _handle_publish(self, fixed_byte: int, data: bytes) -> None:
        """Parse an incoming PUBLISH packet and call subscribers."""
        qos = (fixed_byte >> 1) & 0x03
        topic_len = struct.unpack(">H", data[:2])[0]
        topic = data[2 : 2 + topic_len].decode("utf-8")
        offset = 2 + topic_len
        if qos > 0:
            offset += 2  # skip packet ID
        payload = data[offset:]
        msg = MQTTMessage(topic=topic, payload=payload, qos=QoS(qos))

        # Match wildcards
        for subscribed_topic, callbacks in self._subscriptions.items():
            if self._topic_matches(subscribed_topic, topic):
                for cb in callbacks:
                    try:
                        cb(msg)
                    except Exception:
                        logger.exception("MQTT subscriber error for topic %s", topic)

    @staticmethod
    def _topic_matches(filter_: str, topic: str) -> bool:
        """MQTT topic wildcard matching (+ single-level, # multi-level)."""
        if filter_ == topic:
            return True
        filter_parts = filter_.split("/")
        topic_parts = topic.split("/")
        for i, fp in enumerate(filter_parts):
            if fp == "#":
                return True
            if i >= len(topic_parts):
                return False
            if fp != "+" and fp != topic_parts[i]:
                return False
        return len(filter_parts) == len(topic_parts)

    async def _keepalive_loop(self) -> None:
        """Send PINGREQ packets to maintain the connection."""
        while self._running:
            await asyncio.sleep(self.keepalive)
            if self._writer:
                self._writer.write(bytes([PINGREQ, 0x00]))
                await self._writer.drain()
                logger.debug("MQTT PINGREQ sent")

    async def disconnect(self) -> None:
        """Send DISCONNECT and close the connection."""
        self._running = False
        if self._ping_task:
            self._ping_task.cancel()
        if self._recv_task:
            self._recv_task.cancel()
        if self._writer:
            self._writer.write(bytes([DISCONNECT, 0x00]))
            await self._writer.drain()
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        logger.info("MQTT disconnected from %s:%s", self.host, self.port)


class VelaMQTTTelemetryBridge:
    """
    High-level MQTT bridge for Vela asset telemetry.

    Subscribes to Vela topic namespaces and routes telemetry
    to the appropriate asset state handlers.
    """

    TELEMETRY_TOPIC = "vela/+/telemetry"
    COMMAND_TOPIC_PREFIX = "vela/{asset_id}/command"
    RESPONSE_TOPIC_PREFIX = "vela/{asset_id}/response"

    def __init__(self, mqtt_client: MQTTClient) -> None:
        self._client = mqtt_client
        self._telemetry_handlers: list[Callable[[TelemetryFrame], None]] = []

    def on_telemetry(self, handler: Callable[[TelemetryFrame], None]) -> None:
        self._telemetry_handlers.append(handler)

    async def start(self) -> None:
        """Subscribe to all Vela telemetry topics."""
        await self._client.subscribe(
            self.TELEMETRY_TOPIC, self._handle_telemetry_message
        )
        logger.info("VelaMQTTBridge subscribed to %s", self.TELEMETRY_TOPIC)

    def _handle_telemetry_message(self, msg: MQTTMessage) -> None:
        try:
            frame = TelemetryFrame.from_mqtt_message(msg)
            for handler in self._telemetry_handlers:
                handler(frame)
        except Exception:
            logger.exception("Error parsing telemetry from topic %s", msg.topic)

    async def send_dispatch_command(
        self, asset_id: str, command: dict[str, Any]
    ) -> None:
        """Publish a dispatch command to a specific asset."""
        topic = self.COMMAND_TOPIC_PREFIX.format(asset_id=asset_id)
        command.setdefault("ts", time.time())
        await self._client.publish(topic, command)
        logger.debug("Dispatched command to %s: %s", asset_id, command)
