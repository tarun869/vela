"""Initial schema — assets, dispatch_plans, telemetry

Revision ID: 0001
Revises:
Create Date: 2024-01-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Assets table
    op.create_table(
        "assets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("capacity_mwh", sa.Float(), nullable=False),
        sa.Column("power_mw", sa.Float(), nullable=False),
        sa.Column("soc_min", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("soc_max", sa.Float(), nullable=False, server_default="0.95"),
        sa.Column("round_trip_efficiency", sa.Float(), nullable=False, server_default="0.88"),
        sa.Column("ramp_rate_mw_per_min", sa.Float(), nullable=True),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("status", sa.String(32), nullable=False, server_default="offline"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_assets_market", "assets", ["market"])
    op.create_index("ix_assets_status", "assets", ["status"])
    op.create_index("ix_assets_asset_type", "assets", ["asset_type"])

    # Portfolios table
    op.create_table(
        "portfolios",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("optimization_objective", sa.String(64), nullable=False, server_default="max_revenue"),
        sa.Column("constraints", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # Portfolio-Asset association
    op.create_table(
        "portfolio_assets",
        sa.Column("portfolio_id", sa.String(64), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.String(64), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("portfolio_id", "asset_id"),
    )

    # Dispatch plans table
    op.create_table(
        "dispatch_plans",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("portfolio_id", sa.String(64), sa.ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("horizon_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("objective_value_usd", sa.Float(), nullable=True),
        sa.Column("mip_gap_pct", sa.Float(), nullable=True),
        sa.Column("solve_time_seconds", sa.Float(), nullable=True),
        sa.Column("solver_status", sa.String(32), nullable=True),
        sa.Column("intervals", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_dispatch_plans_portfolio_id", "dispatch_plans", ["portfolio_id"])
    op.create_index("ix_dispatch_plans_horizon_start", "dispatch_plans", ["horizon_start"])

    # Dispatch commands table
    op.create_table(
        "dispatch_commands",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("asset_id", sa.String(64), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("dispatch_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("power_mw", sa.Float(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_for_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("issued_by", sa.String(64), nullable=False, server_default="orchestrator"),
        sa.Column("is_emergency", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("acked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_power_mw", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_dispatch_commands_asset_id", "dispatch_commands", ["asset_id"])
    op.create_index("ix_dispatch_commands_effective_at", "dispatch_commands", ["effective_at"])

    # Telemetry table (will be partitioned in migration 0009)
    op.create_table(
        "telemetry",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="scada"),
        sa.Column("measurements", postgresql.JSONB(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_telemetry_asset_id_timestamp", "telemetry", ["asset_id", "timestamp"])
    op.create_index("ix_telemetry_timestamp", "telemetry", ["timestamp"])

    # Asset state snapshots
    op.create_table(
        "asset_states",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("soc_pct", sa.Float(), nullable=True),
        sa.Column("power_mw", sa.Float(), nullable=True),
        sa.Column("temperature_celsius", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_asset_states_asset_id_timestamp", "asset_states", ["asset_id", "timestamp"])


def downgrade() -> None:
    op.drop_table("asset_states")
    op.drop_table("telemetry")
    op.drop_table("dispatch_commands")
    op.drop_table("dispatch_plans")
    op.drop_table("portfolio_assets")
    op.drop_table("portfolios")
    op.drop_table("assets")
