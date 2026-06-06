"""Add settlement tables

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settlement_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("portfolio_id", sa.String(64), nullable=True),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="preliminary"),
        sa.Column("statement_id", sa.String(128), nullable=True),
        sa.Column("total_gross_revenue_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("total_imbalance_charges_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("total_net_revenue_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("revenue_by_product", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_settlement_records_market_date", "settlement_records", ["market", "settlement_date"])
    op.create_index("ix_settlement_records_status", "settlement_records", ["status"])

    op.create_table(
        "settlement_intervals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("record_id", sa.String(64), sa.ForeignKey("settlement_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_mwh", sa.Float(), nullable=True),
        sa.Column("actual_mwh", sa.Float(), nullable=False),
        sa.Column("settlement_price_usd_per_mwh", sa.Numeric(12, 4), nullable=False),
        sa.Column("gross_revenue_usd", sa.Numeric(18, 4), nullable=False),
        sa.Column("imbalance_mwh", sa.Float(), nullable=True),
        sa.Column("imbalance_charge_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("net_revenue_usd", sa.Numeric(18, 4), nullable=False),
    )
    op.create_index("ix_settlement_intervals_record_id", "settlement_intervals", ["record_id"])
    op.create_index("ix_settlement_intervals_asset_interval", "settlement_intervals", ["asset_id", "interval_start"])

    # Market bids table
    op.create_table(
        "market_bids",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("bid_type", sa.String(32), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offer_curve", postgresql.JSONB(), nullable=False),
        sa.Column("min_quantity_mw", sa.Float(), nullable=True),
        sa.Column("max_quantity_mw", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("cleared_quantity_mw", sa.Float(), nullable=True),
        sa.Column("clearing_price_usd_per_mwh", sa.Numeric(12, 4), nullable=True),
        sa.Column("awarded_revenue_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("external_bid_id", sa.String(128), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_market_bids_asset_interval", "market_bids", ["asset_id", "interval_start"])
    op.create_index("ix_market_bids_market_status", "market_bids", ["market", "status"])

    # LMP prices cache
    op.create_table(
        "lmp_prices",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_type", sa.String(16), nullable=False),  # DAM, RTM, HASP
        sa.Column("lmp_usd_per_mwh", sa.Numeric(12, 4), nullable=False),
        sa.Column("energy_component", sa.Numeric(12, 4), nullable=True),
        sa.Column("congestion_component", sa.Numeric(12, 4), nullable=True),
        sa.Column("loss_component", sa.Numeric(12, 4), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_unique_constraint(
        "uq_lmp_prices_node_market_interval",
        "lmp_prices",
        ["node_id", "market", "interval_start", "interval_type"]
    )
    op.create_index("ix_lmp_prices_node_interval", "lmp_prices", ["node_id", "interval_start"])


def downgrade() -> None:
    op.drop_table("lmp_prices")
    op.drop_table("market_bids")
    op.drop_table("settlement_intervals")
    op.drop_table("settlement_records")
