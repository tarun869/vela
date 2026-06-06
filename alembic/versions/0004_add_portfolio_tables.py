"""Add portfolio performance and analytics tables

Revision ID: 0004
Revises: 0003
Create Date: 2024-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Daily portfolio performance snapshots
    op.create_table(
        "portfolio_performance",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("total_revenue_usd", sa.Numeric(18, 4), nullable=False),
        sa.Column("energy_revenue_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("ancillary_revenue_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("capacity_revenue_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("imbalance_charges_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("total_energy_discharged_mwh", sa.Float(), nullable=True),
        sa.Column("total_energy_charged_mwh", sa.Float(), nullable=True),
        sa.Column("avg_dispatch_efficiency", sa.Float(), nullable=True),
        sa.Column("forecast_revenue_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("forecast_accuracy_pct", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_unique_constraint(
        "uq_portfolio_performance_portfolio_date_market",
        "portfolio_performance",
        ["portfolio_id", "date", "market"]
    )
    op.create_index("ix_portfolio_performance_portfolio_date", "portfolio_performance", ["portfolio_id", "date"])

    # Revenue forecasts
    op.create_table(
        "revenue_forecasts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("forecast_horizon_days", sa.Integer(), nullable=False),
        sa.Column("p10_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("p50_usd", sa.Numeric(18, 4), nullable=False),
        sa.Column("p90_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("model_name", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_revenue_forecasts_portfolio_date", "revenue_forecasts", ["portfolio_id", "forecast_date"])


def downgrade() -> None:
    op.drop_table("revenue_forecasts")
    op.drop_table("portfolio_performance")
