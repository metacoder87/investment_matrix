"""Add tick storage tables and Timescale policies.

Revision ID: 20260106_0001
Revises: 914acf3ec5eb
Create Date: 2026-01-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260106_0001"
down_revision = "914acf3ec5eb"
branch_labels = None
depends_on = None


def _create_continuous_aggregate(view_name: str, bucket: str) -> str:
    return f"""
    CREATE MATERIALIZED VIEW {view_name}
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


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("base", sa.String(length=20), nullable=False),
        sa.Column("quote", sa.String(length=20), nullable=False),
        sa.Column("tick_precision", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("exchange", "symbol", name="uq_assets_exchange_symbol"),
    )
    op.create_index("ix_assets_symbol", "assets", ["symbol"])
    op.create_index("ix_assets_exchange", "assets", ["exchange"])

    op.create_table(
        "ticks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=True),
        sa.Column("exchange_trade_id", sa.String(length=64), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingest_source", sa.String(length=32), nullable=True),
        sa.Column("is_aggregated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("owner_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("time", "id"),
    )
    op.create_index("ix_ticks_time", "ticks", ["time"])
    op.create_index("ix_ticks_asset_id", "ticks", ["asset_id"])
    op.create_index("ix_ticks_asset_time", "ticks", ["asset_id", "time"])
    op.create_index("ix_ticks_trade_id", "ticks", ["exchange_trade_id"])

    op.create_table(
        "ticks_focus",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=True),
        sa.Column("exchange_trade_id", sa.String(length=64), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingest_source", sa.String(length=32), nullable=True),
        sa.Column("focus_reason", sa.String(length=64), nullable=True),
        sa.Column("focus_score", sa.Float(), nullable=True),
        sa.Column("owner_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("time", "id"),
    )
    op.create_index("ix_ticks_focus_time", "ticks_focus", ["time"])
    op.create_index("ix_ticks_focus_asset_id", "ticks_focus", ["asset_id"])
    op.create_index("ix_ticks_focus_asset_time", "ticks_focus", ["asset_id", "time"])
    op.create_index("ix_ticks_focus_trade_id", "ticks_focus", ["exchange_trade_id"])

    if not is_postgres:
        return

    # 1. Create Hypertables
    op.execute(
        sa.text("SELECT create_hypertable('ticks', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);")
    )
    op.execute(
        sa.text("SELECT create_hypertable('ticks_focus', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);")
    )

    # 2. Configure Compression
    op.execute(
        sa.text("ALTER TABLE ticks SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'asset_id', "
        "timescaledb.compress_orderby = 'time');")
    )
    op.execute(
        sa.text("ALTER TABLE ticks_focus SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'asset_id', "
        "timescaledb.compress_orderby = 'time');")
    )
    op.execute(sa.text("SELECT add_compression_policy('ticks', INTERVAL '3 days');"))
    op.execute(sa.text("SELECT add_compression_policy('ticks_focus', INTERVAL '3 days');"))
    op.execute(sa.text("SELECT add_retention_policy('ticks', INTERVAL '3 years');"))

    # 3. Create Continuous Aggregates (Views)
    op.execute(sa.text(_create_continuous_aggregate("ticks_1s", "1 second")))
    op.execute(sa.text(_create_continuous_aggregate("ticks_3s", "3 seconds")))
    op.execute(sa.text(_create_continuous_aggregate("ticks_5s", "5 seconds")))
    op.execute(sa.text(_create_continuous_aggregate("ticks_7s", "7 seconds")))

    # 4. Add Refresh Policies (MUST BE BEFORE COMPRESSION POLICY)
    op.execute(
        sa.text("SELECT add_continuous_aggregate_policy("
        "'ticks_1s', INTERVAL '5 years', INTERVAL '3 years', INTERVAL '1 day');")
    )
    op.execute(
        sa.text("SELECT add_continuous_aggregate_policy("
        "'ticks_3s', INTERVAL '7 years', INTERVAL '5 years', INTERVAL '1 day');")
    )
    op.execute(
        sa.text("SELECT add_continuous_aggregate_policy("
        "'ticks_5s', INTERVAL '10 years', INTERVAL '7 years', INTERVAL '1 day');")
    )
    op.execute(
        sa.text("SELECT add_continuous_aggregate_policy("
        "'ticks_7s', INTERVAL '15 years', INTERVAL '10 years', INTERVAL '1 day');")
    )

    # 5. Configure Compression for CAGGs
    op.execute(
        sa.text("ALTER MATERIALIZED VIEW ticks_1s SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'asset_id', "
        "timescaledb.compress_orderby = 'bucket');")
    )
    op.execute(
        sa.text("ALTER MATERIALIZED VIEW ticks_3s SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'asset_id', "
        "timescaledb.compress_orderby = 'bucket');")
    )
    op.execute(
        sa.text("ALTER MATERIALIZED VIEW ticks_5s SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'asset_id', "
        "timescaledb.compress_orderby = 'bucket');")
    )
    op.execute(
        sa.text("ALTER MATERIALIZED VIEW ticks_7s SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'asset_id', "
        "timescaledb.compress_orderby = 'bucket');")
    )

    # 6. Add Compression Policies for CAGGs
    op.execute(sa.text("SELECT add_compression_policy('ticks_1s', INTERVAL '3 days');"))
    op.execute(sa.text("SELECT add_compression_policy('ticks_3s', INTERVAL '3 days');"))
    op.execute(sa.text("SELECT add_compression_policy('ticks_5s', INTERVAL '3 days');"))
    op.execute(sa.text("SELECT add_compression_policy('ticks_7s', INTERVAL '3 days');"))

    # 7. Add Retention Policies for CAGGs
    op.execute(sa.text("SELECT add_retention_policy('ticks_1s', INTERVAL '5 years');"))
    op.execute(sa.text("SELECT add_retention_policy('ticks_3s', INTERVAL '7 years');"))
    op.execute(sa.text("SELECT add_retention_policy('ticks_5s', INTERVAL '10 years');"))
    op.execute(sa.text("SELECT add_retention_policy('ticks_7s', INTERVAL '15 years');"))


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS ticks_7s;"))
        op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS ticks_5s;"))
        op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS ticks_3s;"))
        op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS ticks_1s;"))

    op.drop_index("ix_ticks_focus_trade_id", table_name="ticks_focus")
    op.drop_index("ix_ticks_focus_asset_time", table_name="ticks_focus")
    op.drop_index("ix_ticks_focus_asset_id", table_name="ticks_focus")
    op.drop_index("ix_ticks_focus_time", table_name="ticks_focus")
    op.drop_table("ticks_focus")

    op.drop_index("ix_ticks_trade_id", table_name="ticks")
    op.drop_index("ix_ticks_asset_time", table_name="ticks")
    op.drop_index("ix_ticks_asset_id", table_name="ticks")
    op.drop_index("ix_ticks_time", table_name="ticks")
    op.drop_table("ticks")

    op.drop_index("ix_assets_exchange", table_name="assets")
    op.drop_index("ix_assets_symbol", table_name="assets")
    op.drop_table("assets")
