"""Add ML model registry tables

Revision ID: 0005
Revises: 0004
Create Date: 2024-03-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_models",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("model_type", sa.String(64), nullable=False),  # xgboost, lgbm, etc.
        sa.Column("task", sa.String(64), nullable=False),         # price_spike, load_forecast, etc.
        sa.Column("stage", sa.String(32), nullable=False, server_default="staging"),  # staging, production, archived
        sa.Column("artifact_uri", sa.String(512), nullable=True),
        sa.Column("mlflow_run_id", sa.String(64), nullable=True),
        sa.Column("training_metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("validation_metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("feature_importances", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("hyperparameters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("training_data_start", sa.Date(), nullable=True),
        sa.Column("training_data_end", sa.Date(), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_ml_models_task_stage", "ml_models", ["task", "stage"])
    op.create_unique_constraint("uq_ml_models_name_version", "ml_models", ["name", "version"])

    # Model prediction log for drift detection
    op.create_table(
        "ml_prediction_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.String(64), sa.ForeignKey("ml_models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model_task", sa.String(64), nullable=False),
        sa.Column("input_features", postgresql.JSONB(), nullable=True),
        sa.Column("prediction", sa.Float(), nullable=False),
        sa.Column("actual", sa.Float(), nullable=True),          # Filled in after outcome known
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market", sa.String(32), nullable=True),
        sa.Column("node_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_ml_prediction_log_task_time", "ml_prediction_log", ["model_task", "predicted_at"])


def downgrade() -> None:
    op.drop_table("ml_prediction_log")
    op.drop_table("ml_models")
