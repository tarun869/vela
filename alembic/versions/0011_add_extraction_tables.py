"""Add extraction tables (extracted_assets, obligations)

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Assets onboarded via the m39_extraction PDF/contract pipeline.
    op.create_table(
        "extracted_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("rated_mw", sa.Float(), nullable=False),
        sa.Column("rated_mwh", sa.Float(), nullable=True),
        sa.Column("iso_node", sa.String(64), nullable=True),
        sa.Column("qse_name", sa.String(128), nullable=True),
        sa.Column("chemistry", sa.String(16), nullable=True),
        sa.Column("warranty_cycles", sa.Integer(), nullable=True),
        sa.Column("warranty_years", sa.Integer(), nullable=True),
        sa.Column("capacity_guarantee_pct", sa.Float(), nullable=True),
        sa.Column("commissioned_date", sa.Date(), nullable=True),
        sa.Column("soh_pct", sa.Float(), nullable=False, server_default="100.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("asset_id", name="uq_extracted_assets_asset_id"),
    )
    op.create_index("ix_extracted_assets_asset_id", "extracted_assets", ["asset_id"])

    # Commercial obligations extracted from contract documents.
    op.create_table(
        "obligations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("obligation_type", sa.String(32), nullable=False),
        sa.Column("committed_mw", sa.Float(), nullable=False),
        sa.Column("delivery_windows", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("penalty_linear_per_mwh", sa.Float(), nullable=True),
        sa.Column("penalty_escalation_threshold_mwh", sa.Float(), nullable=True),
        sa.Column("penalty_escalation_multiplier", sa.Float(), nullable=True),
        sa.Column("contract_start", sa.Date(), nullable=True),
        sa.Column("contract_end", sa.Date(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("obligations")
    op.drop_index("ix_extracted_assets_asset_id", table_name="extracted_assets")
    op.drop_table("extracted_assets")
