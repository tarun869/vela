"""WebSocket endpoint for real-time telemetry streaming."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections per topic."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, topic: str) -> None:
        await websocket.accept()
        self._connections.setdefault(topic, []).append(websocket)
        logger.info("WS connected: topic=%s total=%d", topic, len(self._connections[topic]))

    def disconnect(self, websocket: WebSocket, topic: str) -> None:
        conns = self._connections.get(topic, [])
        if websocket in conns:
            conns.remove(websocket)
        logger.info("WS disconnected: topic=%s remaining=%d", topic, len(conns))

    async def broadcast(self, topic: str, message: dict[str, Any]) -> None:
        conns = list(self._connections.get(topic, []))
        dead: list[WebSocket] = []
        payload = json.dumps(message, default=str)
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, topic)

    async def send_to(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        await websocket.send_text(json.dumps(message, default=str))

    @property
    def connection_count(self) -> dict[str, int]:
        return {t: len(ws) for t, ws in self._connections.items()}


manager = ConnectionManager()


@router.websocket("/ws/telemetry/{asset_id}")
async def telemetry_stream(websocket: WebSocket, asset_id: str) -> None:
    """Stream real-time SOC, power, and LMP data for a given asset."""
    topic = f"telemetry:{asset_id}"
    await manager.connect(websocket, topic)
    try:
        # Send welcome message
        await manager.send_to(websocket, {
            "type": "connected",
            "asset_id": asset_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Simulate streaming telemetry at 1 Hz
        soc = 0.5
        while True:
            # In production this would read from a time-series DB or message bus
            import random
            soc = max(0.05, min(0.95, soc + random.uniform(-0.02, 0.02)))
            msg = {
                "type": "telemetry",
                "asset_id": asset_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "soc": round(soc, 4),
                "power_mw": round(random.uniform(-2.0, 2.0), 3),
                "lmp": round(random.uniform(20.0, 120.0), 2),
                "status": "online",
            }
            await manager.send_to(websocket, msg)
            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        manager.disconnect(websocket, topic)
    except Exception as exc:
        logger.error("WS error asset=%s: %s", asset_id, exc)
        manager.disconnect(websocket, topic)


@router.websocket("/ws/dispatch")
async def dispatch_stream(websocket: WebSocket) -> None:
    """Stream dispatch plan updates to all connected clients."""
    topic = "dispatch:global"
    await manager.connect(websocket, topic)
    try:
        await manager.send_to(websocket, {
            "type": "connected",
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Keep connection alive; the server pushes events via manager.broadcast()
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await manager.send_to(websocket, {"type": "pong", "ts": time.time()})
    except WebSocketDisconnect:
        manager.disconnect(websocket, topic)
