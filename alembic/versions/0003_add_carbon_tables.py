"""Add carbon intensity and emissions tracking tables

Revision ID: 0003
Revises: 0002
Create Date: 2024-02-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Grid carbon intensity by region/time
    op.create_table(
        "grid_carbon_intensity",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("region", sa.String(32), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("carbon_intensity_kg_per_mwh", sa.Float(), nullable=False),
        sa.Column("marginal_carbon_kg_per_mwh", sa.Float(), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),  # electricitymap, watttime, etc.
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_grid_carbon_region_interval", "grid_carbon_intensity", ["region", "interval_start"])
    op.create_unique_constraint(
        "uq_grid_carbon_region_market_interval",
        "grid_carbon_intensity",
        ["region", "market", "interval_start"]
    )

    # Asset emissions tracking
    op.create_table(
        "asset_emissions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("energy_discharged_mwh", sa.Float(), nullable=False),
        sa.Column("energy_charged_mwh", sa.Float(), nullable=False),
        sa.Column("net_carbon_kg", sa.Float(), nullable=False),  # Negative = carbon avoided
        sa.Column("carbon_intensity_kg_per_mwh", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_asset_emissions_asset_interval", "asset_emissions", ["asset_id", "interval_start"])

    # Carbon targets and offsets
    op.create_table(
        "carbon_targets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),  # annual, monthly, daily
        sa.Column("target_period_start", sa.Date(), nullable=False),
        sa.Column("target_period_end", sa.Date(), nullable=False),
        sa.Column("target_net_carbon_kg", sa.Float(), nullable=False),
        sa.Column("actual_net_carbon_kg", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("carbon_targets")
    op.drop_table("asset_emissions")
    op.drop_table("grid_carbon_intensity")
