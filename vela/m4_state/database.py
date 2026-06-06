"""SQLAlchemy async engine setup and ORM models for Vela persistence."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all Vela ORM models."""
    pass


class AssetModel(Base):
    """Persistent asset registration record."""
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    site_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    capacity_mw: Mapped[float] = mapped_column(Float, nullable=False)
    energy_capacity_mwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    protocol: Mapped[str] = mapped_column(String(32), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    port: Mapped[int] = mapped_column(Integer, default=502)
    unit_id: Mapped[int] = mapped_column(Integer, default=1)
    metering_id: Mapped[str] = mapped_column(String(64), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TelemetryModel(Base):
    """Time-series telemetry storage (partitioned by day in production)."""
    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    quality: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_telemetry_asset_metric_ts", "asset_id", "metric", "timestamp"),
    )


class MarketPriceModel(Base):
    """Persisted market price history."""
    __tablename__ = "market_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(32), default="energy")
    price_usd_per_mwh: Mapped[float] = mapped_column(Float, nullable=False)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_market_prices_market_node_ts", "market", "node", "interval_start"),
        UniqueConstraint("market", "node", "service", "interval_start", name="uq_market_interval"),
    )


class DispatchModel(Base):
    """Persisted dispatch command and outcome records."""
    __tablename__ = "dispatches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    service: Mapped[str] = mapped_column(String(32), default="energy")
    scheduled_power_mw: Mapped[float] = mapped_column(Float, nullable=False)
    actual_power_mw: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_hours: Mapped[float] = mapped_column(Float, nullable=False)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    revenue_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SettlementModel(Base):
    """Persisted settlement records."""
    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(32), nullable=False)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_mwh: Mapped[float] = mapped_column(Float, nullable=False)
    metered_mwh: Mapped[float] = mapped_column(Float, nullable=False)
    price_usd_per_mwh: Mapped[float] = mapped_column(Float, nullable=False)
    revenue_usd: Mapped[float] = mapped_column(Float, nullable=False)
    imbalance_usd: Mapped[float] = mapped_column(Float, default=0.0)
    settled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ForecastModel(Base):
    """Stored forecast snapshots for backtesting and validation."""
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    forecast_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    values: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)   # [{ts, value, uncertainty}]
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)


class EventLogModel(Base):
    """Persistent event log for audit trail and replay."""
    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default="system")
    correlation_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


# --- Engine Factory ---

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(database_url: str, echo: bool = False, **kwargs: Any) -> AsyncEngine:
    """Create and return the SQLAlchemy async engine."""
    global _engine, _session_factory
    _engine = create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=kwargs.get("pool_size", 10),
        max_overflow=kwargs.get("max_overflow", 20),
    )
    _session_factory = async_sessionmaker(
        _engine, expire_on_commit=False, class_=AsyncSession
    )
    logger.info("Database engine created: %s", database_url.split("@")[-1])
    return _engine


async def create_tables(engine: AsyncEngine | None = None) -> None:
    """Create all database tables (idempotent)."""
    eng = engine or _engine
    if eng is None:
        raise RuntimeError("Engine not initialized. Call create_engine() first.")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection helper for FastAPI route handlers."""
    if _session_factory is None:
        raise RuntimeError("Session factory not initialized. Call create_engine() first.")
    async with _session_factory() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the module-level session factory."""
    if _session_factory is None:
        raise RuntimeError("Session factory not initialized. Call create_engine() first.")
    return _session_factory
