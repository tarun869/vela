"""Add compliance and regulatory reporting tables

Revision ID: 0006
Revises: 0005
Create Date: 2024-03-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Regulatory compliance reports
    op.create_table(
        "compliance_reports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("report_type", sa.String(64), nullable=False),  # nerc_bes, caiso_sqmd, ercot_qse, etc.
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("reporting_period_start", sa.Date(), nullable=False),
        sa.Column("reporting_period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_id", sa.String(128), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.String(64), nullable=True),
    )
    op.create_index("ix_compliance_reports_type_period", "compliance_reports", ["report_type", "reporting_period_start"])

    # Market performance obligations
    op.create_table(
        "performance_obligations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("obligation_type", sa.String(64), nullable=False),  # availability, performance, mileage
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("measurement_period", sa.String(32), nullable=False),  # hourly, daily, monthly
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # Obligation performance tracking
    op.create_table(
        "obligation_performance",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("obligation_id", sa.String(64), sa.ForeignKey("performance_obligations.id"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("required_value", sa.Float(), nullable=False),
        sa.Column("actual_value", sa.Float(), nullable=False),
        sa.Column("compliant", sa.Boolean(), nullable=False),
        sa.Column("penalty_usd", sa.Numeric(18, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_obligation_performance_obligation_period", "obligation_performance", ["obligation_id", "period_start"])


def downgrade() -> None:
    op.drop_table("obligation_performance")
    op.drop_table("performance_obligations")
    op.drop_table("compliance_reports")
