"""JWT-based authentication with API key support."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

logger = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET", "changeme-insecure")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 3600


def create_access_token(
    subject: str,
    roles: list[str] | None = None,
    expires_in: int = JWT_EXPIRY_SECONDS,
) -> str:
    """Create a signed JWT access token."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "roles": roles or ["viewer"],
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def hash_api_key(raw_key: str) -> str:
    """One-way hash of an API key for storage comparison."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    computed = hash_api_key(raw_key)
    return hmac.compare_digest(computed, stored_hash)


def generate_api_key(prefix: str = "vela") -> str:
    """Generate a random opaque API key."""
    import secrets
    return f"{prefix}_{secrets.token_urlsafe(32)}"


class AuthenticationError(Exception):
    """Raised when a credential cannot be validated."""


def authenticate_request(
    token: str | None = None,
    api_key: str | None = None,
    known_key_hashes: list[str] | None = None,
) -> dict[str, Any]:
    """
    Validate a bearer token or API key.
    Returns the identity payload on success.
    Raises AuthenticationError on failure.
    """
    if token:
        try:
            payload = decode_access_token(token)
            return {"subject": payload["sub"], "roles": payload.get("roles", []), "method": "jwt"}
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid token: {exc}")

    if api_key and known_key_hashes:
        for stored in known_key_hashes:
            if verify_api_key(api_key, stored):
                return {"subject": "api_key_user", "roles": ["operator"], "method": "api_key"}
        raise AuthenticationError("Invalid API key")

    raise AuthenticationError("No credentials provided")
