"""Cursor-based pagination utilities."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T")


def encode_cursor(payload: dict[str, Any]) -> str:
    """Encode a dict payload into a URL-safe base64 cursor string."""
    raw = json.dumps(payload, default=str).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a cursor string back into its payload dict."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        return json.loads(raw)
    except Exception as exc:
        raise ValueError(f"Invalid cursor: {exc}") from exc


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    prev_cursor: str | None = None
    total_count: int | None = None
    page_size: int = 50

    @property
    def has_next(self) -> bool:
        return self.next_cursor is not None


def paginate(
    items: list[T],
    limit: int,
    cursor: str | None,
    id_field: str = "id",
) -> Page[T]:
    """
    Paginate a pre-fetched list. In production this would be pushed to the DB query.
    cursor payload: {"after_id": <value>}
    """
    offset = 0
    if cursor:
        try:
            payload = decode_cursor(cursor)
            after_id = payload.get("after_id")
            if after_id is not None:
                for i, item in enumerate(items):
                    item_dict = item if isinstance(item, dict) else item.model_dump()
                    if str(item_dict.get(id_field)) == str(after_id):
                        offset = i + 1
                        break
        except ValueError:
            logger.warning("Ignoring malformed cursor")

    page_items = items[offset : offset + limit]
    next_cursor: str | None = None

    if offset + limit < len(items) and page_items:
        last = page_items[-1]
        last_dict = last if isinstance(last, dict) else last.model_dump()
        next_cursor = encode_cursor({"after_id": str(last_dict.get(id_field, ""))})

    prev_cursor: str | None = None
    if offset > 0 and page_items:
        first = page_items[0]
        first_dict = first if isinstance(first, dict) else first.model_dump()
        prev_cursor = encode_cursor({"before_id": str(first_dict.get(id_field, ""))})

    return Page(
        items=page_items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        total_count=len(items),
        page_size=limit,
    )
