"""Add event sourcing tables

Revision ID: 0008
Revises: 0007
Create Date: 2024-04-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Main event store
    op.create_table(
        "domain_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False, unique=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("caused_by", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("kafka_topic", sa.String(128), nullable=True),
        sa.Column("kafka_offset", sa.BigInteger(), nullable=True),
        sa.Column("kafka_partition", sa.Integer(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_domain_events_aggregate", "domain_events", ["aggregate_type", "aggregate_id"])
    op.create_index("ix_domain_events_event_type", "domain_events", ["event_type"])
    op.create_index("ix_domain_events_occurred_at", "domain_events", ["occurred_at"])
    op.create_index("ix_domain_events_correlation_id", "domain_events", ["correlation_id"])

    # Aggregate snapshots for fast replay
    op.create_table(
        "aggregate_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_unique_constraint(
        "uq_aggregate_snapshots_id_version",
        "aggregate_snapshots",
        ["aggregate_id", "aggregate_type", "version"]
    )

    # Audit log (append-only)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_audit_log_user_time", "audit_log", ["user_id", "occurred_at"])
    op.create_index("ix_audit_log_resource", "audit_log", ["resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("aggregate_snapshots")
    op.drop_table("domain_events")
