"""Add capacity telemetry fields and Timescale quote/tick rollups.

Revision ID: 20260430_0001
Revises: 20260429_0001
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260430_0001"
down_revision = "20260429_0001"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _create_tick_cagg(view_name: str, bucket: str) -> str:
    return f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {view_name}
    WITH (timescaledb.continuous) AS
    SELECT
      time_bucket('{bucket}', time) AS bucket,
      asset_id,
      first(price, time) AS open,
      max(price) AS high,
      min(price) AS low,
      last(price, time) AS close,
      sum(volume) AS volume,
      count(*) AS trades
    FROM ticks
    GROUP BY bucket, asset_id
    WITH NO DATA;
    """


def _create_quote_cagg(view_name: str, bucket: str) -> str:
    return f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {view_name}
    WITH (timescaledb.continuous) AS
    SELECT
      time_bucket('{bucket}', timestamp) AS bucket,
      exchange,
      symbol,
      last(bid, timestamp) AS bid,
      last(ask, timestamp) AS ask,
      avg(bid_size) AS avg_bid_size,
      avg(ask_size) AS avg_ask_size,
      avg(mid) AS avg_mid,
      avg(spread_bps) AS avg_spread_bps,
      min(spread_bps) AS min_spread_bps,
      max(spread_bps) AS max_spread_bps,
      count(*) AS quotes
    FROM market_quotes
    GROUP BY bucket, exchange, symbol
    WITH NO DATA;
    """


def upgrade() -> None:
    _add_column_if_missing("data_source_health", sa.Column("redis_stream_length", sa.Integer(), nullable=True))
    _add_column_if_missing("data_source_health", sa.Column("redis_pending_messages", sa.Integer(), nullable=True))
    _add_column_if_missing("data_source_health", sa.Column("writer_lag_seconds", sa.Float(), nullable=True))
    _add_column_if_missing("data_source_health", sa.Column("writer_batch_latency_ms", sa.Float(), nullable=True))
    _add_column_if_missing("data_source_health", sa.Column("rows_per_second", sa.Float(), nullable=True))
    _add_column_if_missing("data_source_health", sa.Column("db_pressure", sa.Float(), nullable=True))
    _add_column_if_missing("data_source_health", sa.Column("last_telemetry_at", sa.DateTime(timezone=True), nullable=True))
    _create_index_if_missing("ix_data_source_health_last_telemetry_at", "data_source_health", ["last_telemetry_at"])

    _add_column_if_missing(
        "stream_targets",
        sa.Column("coverage_tier", sa.String(length=30), nullable=False, server_default="ohlcv_only"),
    )
    _add_column_if_missing(
        "stream_targets",
        sa.Column("capacity_state", sa.String(length=30), nullable=False, server_default="normal"),
    )
    _add_column_if_missing("stream_targets", sa.Column("expected_messages_per_second", sa.Float(), nullable=True))
    _create_index_if_missing("ix_stream_targets_coverage_tier", "stream_targets", ["coverage_tier"])
    _create_index_if_missing("ix_stream_targets_capacity_state", "stream_targets", ["capacity_state"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'market_quotes'::regclass
              AND conname = 'market_quotes_pkey'
          ) THEN
            ALTER TABLE market_quotes DROP CONSTRAINT market_quotes_pkey;
          END IF;
        EXCEPTION WHEN undefined_table THEN
          NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'market_quotes'::regclass
              AND conname = 'market_quotes_pkey'
          ) THEN
            ALTER TABLE market_quotes ADD CONSTRAINT market_quotes_pkey PRIMARY KEY (timestamp, id);
          END IF;
        EXCEPTION WHEN undefined_table THEN
          NULL;
        END $$;
        """
    )
    op.execute(
        """
        SELECT create_hypertable(
          'market_quotes',
          'timestamp',
          chunk_time_interval => INTERVAL '1 day',
          migrate_data => TRUE,
          if_not_exists => TRUE
        );
        """
    )
    op.execute(
        """
        ALTER TABLE market_quotes SET (
          timescaledb.compress,
          timescaledb.compress_segmentby = 'exchange,symbol',
          timescaledb.compress_orderby = 'timestamp'
        );
        """
    )
    op.execute("SELECT add_compression_policy('market_quotes', INTERVAL '3 days', if_not_exists => TRUE);")
    op.execute("SELECT add_retention_policy('market_quotes', INTERVAL '30 days', if_not_exists => TRUE);")

    op.execute(sa.text(_create_tick_cagg("ticks_1m", "1 minute")))
    op.execute(sa.text(_create_tick_cagg("ticks_5m", "5 minutes")))
    op.execute(sa.text(_create_quote_cagg("market_quotes_1m", "1 minute")))
    op.execute(sa.text(_create_quote_cagg("market_quotes_5m", "5 minutes")))

    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
          'ticks_1m',
          start_offset => INTERVAL '30 days',
          end_offset => INTERVAL '1 minute',
          schedule_interval => INTERVAL '1 minute',
          if_not_exists => TRUE
        );
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
          'ticks_5m',
          start_offset => INTERVAL '180 days',
          end_offset => INTERVAL '5 minutes',
          schedule_interval => INTERVAL '5 minutes',
          if_not_exists => TRUE
        );
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
          'market_quotes_1m',
          start_offset => INTERVAL '7 days',
          end_offset => INTERVAL '1 minute',
          schedule_interval => INTERVAL '1 minute',
          if_not_exists => TRUE
        );
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
          'market_quotes_5m',
          start_offset => INTERVAL '90 days',
          end_offset => INTERVAL '5 minutes',
          schedule_interval => INTERVAL '5 minutes',
          if_not_exists => TRUE
        );
        """
    )

    for view_name in ("ticks_1m", "ticks_5m"):
        op.execute(
            sa.text(
                f"""
                ALTER MATERIALIZED VIEW {view_name} SET (
                  timescaledb.compress,
                  timescaledb.compress_segmentby = 'asset_id',
                  timescaledb.compress_orderby = 'bucket'
                );
                """
            )
        )
        op.execute(sa.text(f"SELECT add_compression_policy('{view_name}', INTERVAL '3 days', if_not_exists => TRUE);"))

    for view_name in ("market_quotes_1m", "market_quotes_5m"):
        op.execute(
            sa.text(
                f"""
                ALTER MATERIALIZED VIEW {view_name} SET (
                  timescaledb.compress,
                  timescaledb.compress_segmentby = 'exchange,symbol',
                  timescaledb.compress_orderby = 'bucket'
                );
                """
            )
        )
        op.execute(sa.text(f"SELECT add_compression_policy('{view_name}', INTERVAL '3 days', if_not_exists => TRUE);"))

    op.execute("SELECT add_retention_policy('ticks_1m', INTERVAL '5 years', if_not_exists => TRUE);")
    op.execute("SELECT add_retention_policy('ticks_5m', INTERVAL '10 years', if_not_exists => TRUE);")
    op.execute("SELECT add_retention_policy('market_quotes_1m', INTERVAL '1 year', if_not_exists => TRUE);")
    op.execute("SELECT add_retention_policy('market_quotes_5m', INTERVAL '5 years', if_not_exists => TRUE);")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for view_name in ("market_quotes_5m", "market_quotes_1m", "ticks_5m", "ticks_1m"):
            op.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {view_name};"))
        op.execute("SELECT remove_retention_policy('market_quotes', if_exists => TRUE);")
        op.execute("SELECT remove_compression_policy('market_quotes', if_exists => TRUE);")
        op.execute("ALTER TABLE market_quotes SET (timescaledb.compress = false);")

    for index_name, table_name in (
        ("ix_stream_targets_capacity_state", "stream_targets"),
        ("ix_stream_targets_coverage_tier", "stream_targets"),
        ("ix_data_source_health_last_telemetry_at", "data_source_health"),
    ):
        if _index_exists(table_name, index_name):
            op.drop_index(index_name, table_name=table_name)

    for table_name, columns in (
        ("stream_targets", ("expected_messages_per_second", "capacity_state", "coverage_tier")),
        (
            "data_source_health",
            (
                "last_telemetry_at",
                "db_pressure",
                "rows_per_second",
                "writer_batch_latency_ms",
                "writer_lag_seconds",
                "redis_pending_messages",
                "redis_stream_length",
            ),
        ),
    ):
        for column_name in columns:
            if _column_exists(table_name, column_name):
                op.drop_column(table_name, column_name)
