"""Admin endpoints: user management, system config, audit logs."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: str
    roles: list[str] = Field(default_factory=lambda: ["viewer"])
    active: bool = True


class UserResponse(BaseModel):
    user_id: str
    username: str
    email: str
    roles: list[str]
    active: bool
    created_at: datetime
    last_login: datetime | None = None


class SystemConfig(BaseModel):
    key: str
    value: str
    description: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


class AuditEntry(BaseModel):
    entry_id: str
    timestamp: datetime
    actor: str
    action: str
    resource_type: str
    resource_id: str | None = None
    outcome: Literal["success", "failure"]
    details: dict = Field(default_factory=dict)


_USERS: dict[str, UserResponse] = {}
_CONFIG: dict[str, SystemConfig] = {
    "dispatch_interval_minutes": SystemConfig(
        key="dispatch_interval_minutes",
        value="5",
        description="How often the dispatch loop runs",
    ),
    "settlement_lag_hours": SystemConfig(
        key="settlement_lag_hours",
        value="72",
        description="Settlement finalization lag after real-time",
    ),
}
_AUDIT: list[AuditEntry] = []


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[UserResponse]:
    users = list(_USERS.values())
    if active is not None:
        users = [u for u in users if u.active == active]
    return users[:limit]


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(request: UserCreate) -> UserResponse:
    for u in _USERS.values():
        if u.username == request.username:
            raise HTTPException(status_code=409, detail=f"Username '{request.username}' already exists")
    user = UserResponse(
        user_id=str(uuid.uuid4()),
        username=request.username,
        email=request.email,
        roles=request.roles,
        active=request.active,
        created_at=datetime.now(timezone.utc),
    )
    _USERS[user.user_id] = user
    _audit("system", "create_user", "user", user.user_id)
    return user


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str) -> UserResponse:
    user = _USERS.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


@router.patch("/users/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(user_id: str) -> UserResponse:
    user = _USERS.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    user.active = False
    _audit("system", "deactivate_user", "user", user_id)
    return user


@router.get("/config", response_model=list[SystemConfig])
async def list_config() -> list[SystemConfig]:
    return list(_CONFIG.values())


@router.put("/config/{key}", response_model=SystemConfig)
async def set_config(key: str, value: str = Query(...), actor: str = Query(default="admin")) -> SystemConfig:
    entry = _CONFIG.get(key, SystemConfig(key=key, value=value))
    entry.value = value
    entry.updated_by = actor
    entry.updated_at = datetime.now(timezone.utc)
    _CONFIG[key] = entry
    _audit(actor, "set_config", "config", key)
    return entry


@router.get("/audit", response_model=list[AuditEntry])
async def get_audit_log(
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AuditEntry]:
    entries = list(_AUDIT)
    if actor:
        entries = [e for e in entries if e.actor == actor]
    if action:
        entries = [e for e in entries if e.action == action]
    return entries[-limit:]


def _audit(actor: str, action: str, resource_type: str, resource_id: str | None = None) -> None:
    _AUDIT.append(AuditEntry(
        entry_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome="success",
    ))
