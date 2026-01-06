"""Add TimescaleDB compression policies

Revision ID: 2cddc5d8135a
Revises: 20251215_0002
Create Date: 2026-01-02 12:36:09.070539

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '2cddc5d8135a'
down_revision = '20251215_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # Only run compression policies if we are on Postgres/TimescaleDB
    if is_postgres:
        # 1. Market Trades (High volume tick data)
        # Compress by exchange+symbol, ordered by time
        op.execute("""
            ALTER TABLE market_trades SET (
                timescaledb.compress, 
                timescaledb.compress_segmentby = 'exchange,symbol', 
                timescaledb.compress_orderby = 'timestamp'
            );
        """)
        # Policy: Compress chunks older than 7 days
        op.execute("SELECT add_compression_policy('market_trades', INTERVAL '7 days');")

        # 2. Prices (OHLCV)
        # Compress by symbol
        op.execute("""
            ALTER TABLE prices SET (
                timescaledb.compress, 
                timescaledb.compress_segmentby = 'symbol', 
                timescaledb.compress_orderby = 'timestamp'
            );
        """)
        op.execute("SELECT add_compression_policy('prices', INTERVAL '14 days');")

        # 3. Indicators
        op.execute("""
            ALTER TABLE indicators SET (
                timescaledb.compress, 
                timescaledb.compress_segmentby = 'symbol', 
                timescaledb.compress_orderby = 'timestamp'
            );
        """)
        op.execute("SELECT add_compression_policy('indicators', INTERVAL '14 days');")


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        # Remove policies and disable compression
        op.execute("SELECT remove_compression_policy('market_trades', if_exists => TRUE);")
        op.execute("ALTER TABLE market_trades SET (timescaledb.compress = false);")
        
        op.execute("SELECT remove_compression_policy('prices', if_exists => TRUE);")
        op.execute("ALTER TABLE prices SET (timescaledb.compress = false);")

        op.execute("SELECT remove_compression_policy('indicators', if_exists => TRUE);")
        op.execute("ALTER TABLE indicators SET (timescaledb.compress = false);")
