"""Convert telemetry table to time-based partitioning

Revision ID: 0009
Revises: 0008
Create Date: 2024-05-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename existing table
    op.rename_table("telemetry", "telemetry_old")

    # Create new partitioned table
    op.execute("""
        CREATE TABLE telemetry (
            id          BIGSERIAL,
            asset_id    VARCHAR(64)              NOT NULL,
            timestamp   TIMESTAMPTZ              NOT NULL,
            source      VARCHAR(32)              NOT NULL DEFAULT 'scada',
            measurements JSONB                   NOT NULL,
            tags        JSONB                    NOT NULL DEFAULT '{}',
            ingested_at TIMESTAMPTZ              NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, timestamp)
        ) PARTITION BY RANGE (timestamp)
    """)

    # Create monthly partitions for the next 12 months
    op.execute("""
        DO $$
        DECLARE
            start_date DATE := DATE_TRUNC('month', NOW());
            end_date   DATE;
            part_name  TEXT;
        BEGIN
            FOR i IN 0..11 LOOP
                start_date := DATE_TRUNC('month', NOW() + (i || ' months')::INTERVAL);
                end_date   := start_date + INTERVAL '1 month';
                part_name  := 'telemetry_' || TO_CHAR(start_date, 'YYYY_MM');
                EXECUTE FORMAT(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF telemetry
                     FOR VALUES FROM (%L) TO (%L)',
                    part_name, start_date, end_date
                );
            END LOOP;
        END $$;
    """)

    # Create indexes on partitioned table
    op.execute("CREATE INDEX ix_telemetry_asset_timestamp ON telemetry (asset_id, timestamp)")
    op.execute("CREATE INDEX ix_telemetry_timestamp ON telemetry (timestamp)")

    # Migrate data
    op.execute("""
        INSERT INTO telemetry (id, asset_id, timestamp, source, measurements, tags, ingested_at)
        SELECT id, asset_id, timestamp, source, measurements, tags, ingested_at
        FROM telemetry_old
    """)

    # Drop old table
    op.drop_table("telemetry_old")

    # Create auto-partition function for future months
    op.execute("""
        CREATE OR REPLACE FUNCTION create_telemetry_partition_for_month(target_month DATE)
        RETURNS VOID AS $$
        DECLARE
            part_name  TEXT;
            start_date DATE;
            end_date   DATE;
        BEGIN
            start_date := DATE_TRUNC('month', target_month);
            end_date   := start_date + INTERVAL '1 month';
            part_name  := 'telemetry_' || TO_CHAR(start_date, 'YYYY_MM');
            EXECUTE FORMAT(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF telemetry
                 FOR VALUES FROM (%L) TO (%L)',
                part_name, start_date, end_date
            );
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # Reverse: collect all partitioned data back into unpartitioned table
    op.execute("""
        CREATE TABLE telemetry_old (
            id          BIGSERIAL PRIMARY KEY,
            asset_id    VARCHAR(64)  NOT NULL,
            timestamp   TIMESTAMPTZ  NOT NULL,
            source      VARCHAR(32)  NOT NULL DEFAULT 'scada',
            measurements JSONB       NOT NULL,
            tags        JSONB        NOT NULL DEFAULT '{}',
            ingested_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("INSERT INTO telemetry_old SELECT * FROM telemetry")
    op.execute("DROP TABLE telemetry CASCADE")
    op.rename_table("telemetry_old", "telemetry")
    op.execute("CREATE INDEX ix_telemetry_asset_id_timestamp ON telemetry (asset_id, timestamp)")
    op.execute("DROP FUNCTION IF EXISTS create_telemetry_partition_for_month(DATE)")
