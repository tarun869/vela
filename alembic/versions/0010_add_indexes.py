"""Add performance indexes for common query patterns

Revision ID: 0010
Revises: 0009
Create Date: 2024-05-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- LMP prices — most queried by node+time range ---
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lmp_prices_node_market_interval_type
        ON lmp_prices (node_id, market, interval_start, interval_type)
    """)
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lmp_prices_market_interval
        ON lmp_prices (market, interval_start)
    """)

    # --- Market bids — query by asset+time for dashboard ---
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_market_bids_asset_market_interval
        ON market_bids (asset_id, market, interval_start DESC)
    """)
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_market_bids_cleared_at
        ON market_bids (cleared_at)
        WHERE cleared_at IS NOT NULL
    """)

    # --- Settlement records — common reporting queries ---
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_settlement_records_portfolio_market_date
        ON settlement_records (portfolio_id, market, settlement_date DESC)
    """)

    # --- Dispatch plans — recent plans by portfolio ---
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dispatch_plans_portfolio_created
        ON dispatch_plans (portfolio_id, created_at DESC)
    """)

    # --- Asset states — most recent state per asset ---
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_asset_states_asset_timestamp_desc
        ON asset_states (asset_id, timestamp DESC)
    """)

    # --- Domain events — query by correlation_id for tracing ---
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_domain_events_aggregate_occurred
        ON domain_events (aggregate_type, aggregate_id, occurred_at DESC)
    """)

    # --- Portfolio performance — dashboard time series ---
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_portfolio_performance_date_market
        ON portfolio_performance (date DESC, market)
    """)

    # --- BRIN index on telemetry for time-range scans ---
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_telemetry_asset_brin
        ON telemetry USING BRIN (asset_id, timestamp)
        WITH (pages_per_range = 128)
    """)

    # --- Full-text search on compliance report notes ---
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_compliance_reports_notes_fts
        ON compliance_reports USING GIN (to_tsvector('english', COALESCE(notes, '')))
    """)


def downgrade() -> None:
    indexes = [
        ("lmp_prices", "ix_lmp_prices_node_market_interval_type"),
        ("lmp_prices", "ix_lmp_prices_market_interval"),
        ("market_bids", "ix_market_bids_asset_market_interval"),
        ("market_bids", "ix_market_bids_cleared_at"),
        ("settlement_records", "ix_settlement_records_portfolio_market_date"),
        ("dispatch_plans", "ix_dispatch_plans_portfolio_created"),
        ("asset_states", "ix_asset_states_asset_timestamp_desc"),
        ("domain_events", "ix_domain_events_aggregate_occurred"),
        ("portfolio_performance", "ix_portfolio_performance_date_market"),
        ("telemetry", "ix_telemetry_asset_brin"),
        ("compliance_reports", "ix_compliance_reports_notes_fts"),
    ]
    for _table, idx in indexes:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {idx}")
