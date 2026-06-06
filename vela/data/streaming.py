"""Kafka streaming: produce and consume market data and telemetry events."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

_KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

TOPICS = {
    "lmp_prices": "vela.market.lmp_prices",
    "telemetry": "vela.assets.telemetry",
    "dispatch_plans": "vela.dispatch.plans",
    "settlement_events": "vela.settlements.events",
    "carbon_signals": "vela.carbon.signals",
    "alerts": "vela.ops.alerts",
}


@dataclass
class KafkaMessage:
    topic: str
    key: str | None
    value: dict[str, Any]
    timestamp: datetime
    partition: int = 0
    offset: int = 0


class VelaProducer:
    """
    Thin wrapper around the kafka-python producer.
    Falls back to in-memory queue if Kafka is unavailable.
    """

    def __init__(self, bootstrap_servers: str = _KAFKA_BOOTSTRAP) -> None:
        self.bootstrap_servers = bootstrap_servers
        self._producer = None
        self._fallback: list[KafkaMessage] = []
        self._using_fallback = False

    def _get_producer(self):
        if self._producer is not None:
            return self._producer
        try:
            from kafka import KafkaProducer as _KP
            self._producer = _KP(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, default=str).encode(),
                key_serializer=lambda k: k.encode() if k else None,
            )
            return self._producer
        except Exception as exc:
            if not self._using_fallback:
                logger.warning("Kafka unavailable (%s); using in-memory fallback", exc)
                self._using_fallback = True
            return None

    def send(self, topic: str, value: dict[str, Any], key: str | None = None) -> None:
        """Send a message to a Kafka topic."""
        producer = self._get_producer()
        msg = KafkaMessage(
            topic=topic,
            key=key,
            value=value,
            timestamp=datetime.now(timezone.utc),
        )
        if producer:
            try:
                producer.send(topic, value=value, key=key)
                return
            except Exception as exc:
                logger.error("Kafka send failed: %s", exc)
        self._fallback.append(msg)

    def flush(self) -> None:
        if self._producer:
            self._producer.flush()

    def emit_lmp(self, node: str, lmp: float, market: str = "CAISO") -> None:
        self.send(
            TOPICS["lmp_prices"],
            {"node": node, "lmp": lmp, "market": market, "ts": datetime.now(timezone.utc).isoformat()},
            key=node,
        )

    def emit_telemetry(self, asset_id: str, soc: float, power_mw: float) -> None:
        self.send(
            TOPICS["telemetry"],
            {"asset_id": asset_id, "soc": soc, "power_mw": power_mw, "ts": datetime.now(timezone.utc).isoformat()},
            key=asset_id,
        )

    def emit_dispatch_plan(self, plan_id: str, status: str, objective: float | None) -> None:
        self.send(
            TOPICS["dispatch_plans"],
            {"plan_id": plan_id, "status": status, "objective": objective, "ts": datetime.now(timezone.utc).isoformat()},
            key=plan_id,
        )

    def drain_fallback(self) -> list[KafkaMessage]:
        """Return and clear all buffered fallback messages."""
        msgs = list(self._fallback)
        self._fallback.clear()
        return msgs


class VelaConsumer:
    """Consumer wrapper for reading Vela topics."""

    def __init__(
        self,
        topics: list[str],
        group_id: str = "vela-consumer",
        bootstrap_servers: str = _KAFKA_BOOTSTRAP,
    ) -> None:
        self.topics = topics
        self.group_id = group_id
        self.bootstrap_servers = bootstrap_servers

    def consume(self, handler: Callable[[KafkaMessage], None], timeout_ms: int = 1000) -> None:
        """Poll Kafka and invoke `handler` for each message."""
        try:
            from kafka import KafkaConsumer
            consumer = KafkaConsumer(
                *self.topics,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                value_deserializer=lambda v: json.loads(v.decode()),
                auto_offset_reset="latest",
                enable_auto_commit=True,
                consumer_timeout_ms=timeout_ms,
            )
            for msg in consumer:
                km = KafkaMessage(
                    topic=msg.topic,
                    key=msg.key.decode() if msg.key else None,
                    value=msg.value,
                    timestamp=datetime.now(timezone.utc),
                    partition=msg.partition,
                    offset=msg.offset,
                )
                handler(km)
        except ImportError:
            logger.warning("kafka-python not installed; consumer is a no-op")
        except Exception as exc:
            logger.error("Kafka consumer error: %s", exc)


# Singleton producer
producer = VelaProducer()
