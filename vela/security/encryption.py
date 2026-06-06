"""Field-level encryption for sensitive data (API keys, credentials, PII)."""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_KEY_ENV = "VELA_ENCRYPTION_KEY"


def _get_fernet():
    """Return a Fernet instance using the application encryption key."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise RuntimeError("cryptography package not installed: pip install cryptography")

    key_b64 = os.getenv(_KEY_ENV, "")
    if not key_b64:
        # Generate a key for dev; in production this must come from KMS
        key = Fernet.generate_key()
        logger.warning(
            "No %s set; generated ephemeral key. Set this env var in production.", _KEY_ENV
        )
    else:
        key = key_b64.encode()
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt a string to a base64-encoded ciphertext."""
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext back to plaintext."""
    fernet = _get_fernet()
    return fernet.decrypt(ciphertext.encode()).decode()


def encrypt_dict_fields(data: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Return a copy of `data` with the specified fields encrypted."""
    out = dict(data)
    for field in fields:
        if field in out and out[field] is not None:
            out[field] = encrypt(str(out[field]))
    return out


def decrypt_dict_fields(data: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Return a copy of `data` with the specified fields decrypted."""
    out = dict(data)
    for field in fields:
        if field in out and out[field] is not None:
            try:
                out[field] = decrypt(str(out[field]))
            except Exception as exc:
                logger.error("Failed to decrypt field '%s': %s", field, exc)
    return out


def mask(value: str, visible_chars: int = 4) -> str:
    """Return a masked representation of a sensitive string (e.g., API key)."""
    if len(value) <= visible_chars:
        return "*" * len(value)
    return value[:visible_chars] + "*" * (len(value) - visible_chars)


# --- Convenience wrapper for Pydantic models ---

class EncryptedStr(str):
    """
    A custom Pydantic-compatible string type that stores values as ciphertext.
    Usage: sensitive_field: EncryptedStr
    """

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v: Any) -> "EncryptedStr":
        if isinstance(v, cls):
            return v
        plaintext = str(v)
        ciphertext = encrypt(plaintext)
        return cls(ciphertext)

    def decrypt(self) -> str:
        return decrypt(str(self))
