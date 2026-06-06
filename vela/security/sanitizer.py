"""Input sanitization to prevent injection attacks and validate user data."""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Any


# Characters allowed in identifiers (asset IDs, node names, etc.)
_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
_SQL_INJECTION_PATTERN = re.compile(
    r"(\b(select|insert|update|delete|drop|create|alter|exec|union|script)\b)",
    re.IGNORECASE,
)
_XSS_PATTERN = re.compile(r"<[^>]*script[^>]*>", re.IGNORECASE)


def sanitize_id(value: str, max_length: int = 128) -> str:
    """
    Validate that an ID-like string contains only safe characters.
    Raises ValueError on invalid input.
    """
    if not value or not isinstance(value, str):
        raise ValueError("ID must be a non-empty string")
    stripped = value.strip()
    if len(stripped) > max_length:
        raise ValueError(f"ID exceeds maximum length of {max_length}")
    if not _SAFE_ID_PATTERN.match(stripped):
        raise ValueError(
            f"ID contains invalid characters. Only alphanumeric, dash, underscore, and dot are allowed."
        )
    return stripped


def sanitize_text(value: str, max_length: int = 4096, strip_html: bool = True) -> str:
    """
    Sanitize free-text input: normalize unicode, optionally escape HTML, truncate.
    """
    if not isinstance(value, str):
        value = str(value)
    # Normalize unicode (NFC form)
    value = unicodedata.normalize("NFC", value)
    # Strip null bytes
    value = value.replace("\x00", "")
    if strip_html:
        value = html.escape(value)
    # Truncate
    return value[:max_length]


def check_sql_injection(value: str) -> bool:
    """Return True if the value looks like a SQL injection attempt."""
    return bool(_SQL_INJECTION_PATTERN.search(value))


def check_xss(value: str) -> bool:
    """Return True if the value contains an XSS script tag pattern."""
    return bool(_XSS_PATTERN.search(value))


def sanitize_dict(data: dict[str, Any], text_fields: list[str] | None = None) -> dict[str, Any]:
    """
    Apply text sanitization to specified string fields in a dict.
    If text_fields is None, all string values are sanitized.
    """
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            if text_fields is None or key in text_fields:
                result[key] = sanitize_text(value)
            else:
                result[key] = value
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value, text_fields)
        else:
            result[key] = value
    return result


def validate_email(email: str) -> bool:
    """Basic RFC-5321 email format check."""
    pattern = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
    return bool(pattern.match(email.strip()))


def validate_node_id(node: str) -> bool:
    """Validate a pricing node ID (e.g., TH_NP15_GEN-APND)."""
    return bool(re.match(r"^[A-Z0-9_\-]{3,64}$", node.upper()))
