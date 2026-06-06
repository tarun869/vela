"""FastAPI dependency injection: DB session, authentication, pagination."""
from __future__ import annotations

import logging
import os
from typing import Annotated, AsyncGenerator

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vela.api.auth import AuthenticationError, authenticate_request
from vela.api.auth_models import UserIdentity

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Database session (async SQLAlchemy)
# ---------------------------------------------------------------------------

try:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    _DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./vela_dev.db")
    _engine = create_async_engine(_DATABASE_URL, echo=False, pool_pre_ping=True)
    _SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
        _engine, expire_on_commit=False
    )

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with _SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

except ImportError:
    async def get_db() -> AsyncGenerator[None, None]:  # type: ignore[misc]
        """Stub when SQLAlchemy is not installed."""
        yield None  # type: ignore[misc]


DbSession = Annotated[object, Depends(get_db)]

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

KNOWN_API_KEY_HASHES: list[str] = []  # populated from DB/env at startup


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Header(default=None),
) -> UserIdentity:
    """Resolve either a Bearer JWT or X-Api-Key header to a UserIdentity."""
    token: str | None = credentials.credentials if credentials else None
    try:
        identity = authenticate_request(
            token=token,
            api_key=x_api_key,
            known_key_hashes=KNOWN_API_KEY_HASHES,
        )
        return UserIdentity(**identity)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )


CurrentUser = Annotated[UserIdentity, Depends(get_current_user)]


def require_role(*roles: str):
    """Factory that returns a dependency enforcing at least one of the given roles."""

    async def _check(user: CurrentUser) -> UserIdentity:
        if not any(r in user.roles for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {list(roles)}",
            )
        return user

    return Depends(_check)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class PaginationParams:
    def __init__(
        self,
        limit: int = Query(default=50, ge=1, le=500),
        cursor: str | None = Query(default=None, description="Opaque continuation cursor"),
    ) -> None:
        self.limit = limit
        self.cursor = cursor


Pagination = Annotated[PaginationParams, Depends(PaginationParams)]
