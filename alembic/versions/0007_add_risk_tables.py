"""Add risk management tables (VaR, CVaR, exposure limits)

Revision ID: 0007
Revises: 0006
Create Date: 2024-04-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Risk metrics snapshots
    op.create_table(
        "risk_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_hours", sa.Integer(), nullable=False),
        sa.Column("var_95_usd", sa.Numeric(18, 4), nullable=True),  # 95% Value at Risk
        sa.Column("var_99_usd", sa.Numeric(18, 4), nullable=True),  # 99% VaR
        sa.Column("cvar_95_usd", sa.Numeric(18, 4), nullable=True), # Conditional VaR
        sa.Column("expected_revenue_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("revenue_std_dev_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("sharpe_ratio", sa.Float(), nullable=True),
        sa.Column("n_scenarios", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_risk_metrics_portfolio_time", "risk_metrics", ["portfolio_id", "calculated_at"])

    # Market exposure limits
    op.create_table(
        "exposure_limits",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("market", sa.String(32), nullable=True),   # NULL = applies to all
        sa.Column("product", sa.String(32), nullable=True),
        sa.Column("limit_type", sa.String(32), nullable=False),  # max_revenue, max_volume, max_var
        sa.Column("limit_value", sa.Float(), nullable=False),
        sa.Column("warning_threshold", sa.Float(), nullable=True),  # Warn at X% of limit
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # Scenario analysis results
    op.create_table(
        "scenario_results",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("scenario_name", sa.String(128), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcomes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("summary_stats", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_scenario_results_portfolio_time", "scenario_results", ["portfolio_id", "run_at"])


def downgrade() -> None:
    op.drop_table("scenario_results")
    op.drop_table("exposure_limits")
    op.drop_table("risk_metrics")
