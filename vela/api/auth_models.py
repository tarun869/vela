"""Pydantic models for authentication requests and responses."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TokenRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 3600
    roles: list[str]


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="Human-readable label")
    roles: list[str] = Field(default_factory=lambda: ["viewer"])
    expires_at: datetime | None = None

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        allowed = {"viewer", "operator", "admin"}
        for role in v:
            if role not in allowed:
                raise ValueError(f"Unknown role '{role}'. Allowed: {allowed}")
        return v


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    prefix: str
    roles: list[str]
    created_at: datetime
    expires_at: datetime | None = None
    raw_key: str | None = None  # only set on creation, never stored


class RefreshRequest(BaseModel):
    refresh_token: str


class UserIdentity(BaseModel):
    subject: str
    roles: list[str]
    method: Literal["jwt", "api_key"]


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v
