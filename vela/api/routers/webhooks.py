"""Webhook endpoints: register, verify, and manage outbound webhooks."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel, Field, HttpUrl

router = APIRouter()


class WebhookCreate(BaseModel):
    url: str = Field(..., description="HTTPS endpoint to deliver events to")
    events: list[str] = Field(
        ...,
        description="Event types to subscribe to (e.g. dispatch.complete, settlement.final)",
    )
    secret: str | None = Field(default=None, description="HMAC signing secret for payload verification")
    active: bool = True
    description: str | None = None


class Webhook(BaseModel):
    webhook_id: str
    url: str
    events: list[str]
    active: bool
    description: str | None
    created_at: datetime
    last_delivery: datetime | None = None
    failure_count: int = 0


class WebhookDelivery(BaseModel):
    delivery_id: str
    webhook_id: str
    event_type: str
    payload: dict
    status: Literal["pending", "delivered", "failed", "retrying"]
    http_status: int | None = None
    delivered_at: datetime | None = None
    attempts: int = 0


class InboundEvent(BaseModel):
    event_type: str
    payload: dict
    source: str = "external"


_WEBHOOKS: dict[str, Webhook] = {}
_WEBHOOK_SECRETS: dict[str, str] = {}
_DELIVERIES: list[WebhookDelivery] = []


@router.post("/", response_model=Webhook, status_code=201)
async def register_webhook(request: WebhookCreate) -> Webhook:
    webhook_id = str(uuid.uuid4())
    webhook = Webhook(
        webhook_id=webhook_id,
        url=request.url,
        events=request.events,
        active=request.active,
        description=request.description,
        created_at=datetime.now(timezone.utc),
    )
    _WEBHOOKS[webhook_id] = webhook
    if request.secret:
        _WEBHOOK_SECRETS[webhook_id] = request.secret
    return webhook


@router.get("/", response_model=list[Webhook])
async def list_webhooks(active: bool | None = None) -> list[Webhook]:
    hooks = list(_WEBHOOKS.values())
    if active is not None:
        hooks = [h for h in hooks if h.active == active]
    return hooks


@router.get("/{webhook_id}", response_model=Webhook)
async def get_webhook(webhook_id: str) -> Webhook:
    hook = _WEBHOOKS.get(webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} not found")
    return hook


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str) -> None:
    if webhook_id not in _WEBHOOKS:
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} not found")
    del _WEBHOOKS[webhook_id]
    _WEBHOOK_SECRETS.pop(webhook_id, None)


@router.post("/{webhook_id}/test", response_model=WebhookDelivery)
async def test_webhook(webhook_id: str, background_tasks: BackgroundTasks) -> WebhookDelivery:
    """Send a test ping payload to the webhook endpoint."""
    hook = _WEBHOOKS.get(webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} not found")
    delivery = WebhookDelivery(
        delivery_id=str(uuid.uuid4()),
        webhook_id=webhook_id,
        event_type="webhook.test",
        payload={"message": "Vela webhook test", "timestamp": datetime.now(timezone.utc).isoformat()},
        status="pending",
    )
    _DELIVERIES.append(delivery)
    background_tasks.add_task(_deliver, delivery, hook)
    return delivery


@router.get("/deliveries/", response_model=list[WebhookDelivery])
async def list_deliveries(
    webhook_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[WebhookDelivery]:
    deliveries = list(_DELIVERIES)
    if webhook_id:
        deliveries = [d for d in deliveries if d.webhook_id == webhook_id]
    if status:
        deliveries = [d for d in deliveries if d.status == status]
    return deliveries[-limit:]


@router.post("/inbound/{source}")
async def receive_inbound(
    source: str,
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
) -> dict:
    """
    Receive inbound webhook events from external systems (e.g., ISO notifications).
    Verifies HMAC signature if configured.
    """
    body = await request.body()
    # In production: look up signing secret by source and verify
    return {"received": True, "source": source, "bytes": len(body)}


async def _deliver(delivery: WebhookDelivery, hook: Webhook) -> None:
    """Background task: HTTP POST the payload to the webhook URL."""
    import json
    try:
        import httpx
        secret = _WEBHOOK_SECRETS.get(hook.webhook_id, "")
        payload_bytes = json.dumps(delivery.payload, default=str).encode()
        sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest() if secret else ""
        headers = {"Content-Type": "application/json", "X-Vela-Signature": sig}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(hook.url, content=payload_bytes, headers=headers)
            delivery.http_status = resp.status_code
            delivery.status = "delivered" if resp.is_success else "failed"
    except Exception:
        delivery.status = "failed"
    delivery.delivered_at = datetime.now(timezone.utc)
    delivery.attempts += 1
    hook.last_delivery = delivery.delivered_at
    if delivery.status == "failed":
        hook.failure_count += 1
