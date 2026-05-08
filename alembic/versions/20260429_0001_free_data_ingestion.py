"""Add free data ingestion source and stream target tables.

Revision ID: 20260429_0001
Revises: 20260427_0006
Create Date: 2026-04-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260429_0001"
down_revision = "20260427_0006"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _create_index(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    if not _table_exists("data_source_health"):
        op.create_table(
            "data_source_health",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.String(length=40), nullable=False),
            sa.Column("source_type", sa.String(length=20), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=True),
            sa.Column("websocket_supported", sa.Boolean(), nullable=True),
            sa.Column("rest_supported", sa.Boolean(), nullable=True),
            sa.Column("quote_supported", sa.Boolean(), nullable=True),
            sa.Column("recent_trades_supported", sa.Boolean(), nullable=True),
            sa.Column("ohlcv_supported", sa.Boolean(), nullable=True),
            sa.Column("rate_limit_profile", sa.String(length=120), nullable=True),
            sa.Column("reconnect_count", sa.Integer(), nullable=True),
            sa.Column("messages_per_second", sa.Float(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("source", name="uq_data_source_health_source"),
        )
        for index_name, column_name in (
            ("ix_data_source_health_id", "id"),
            ("ix_data_source_health_source", "source"),
            ("ix_data_source_health_source_type", "source_type"),
            ("ix_data_source_health_enabled", "enabled"),
            ("ix_data_source_health_last_event_at", "last_event_at"),
            ("ix_data_source_health_last_success_at", "last_success_at"),
            ("ix_data_source_health_last_error_at", "last_error_at"),
        ):
            _create_index(index_name, "data_source_health", [column_name])

    if not _table_exists("stream_targets"):
        op.create_table(
            "stream_targets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exchange", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=80), nullable=False),
            sa.Column("base", sa.String(length=30), nullable=False),
            sa.Column("quote", sa.String(length=30), nullable=False),
            sa.Column("source_type", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=True),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=True),
            sa.Column("user_preference", sa.String(length=20), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("score_details_json", sa.JSON(), nullable=True),
            sa.Column("last_selected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("exchange", "symbol", name="uq_stream_targets_exchange_symbol"),
        )
        for index_name, column_name in (
            ("ix_stream_targets_id", "id"),
            ("ix_stream_targets_exchange", "exchange"),
            ("ix_stream_targets_symbol", "symbol"),
            ("ix_stream_targets_base", "base"),
            ("ix_stream_targets_quote", "quote"),
            ("ix_stream_targets_source_type", "source_type"),
            ("ix_stream_targets_status", "status"),
            ("ix_stream_targets_rank", "rank"),
            ("ix_stream_targets_score", "score"),
            ("ix_stream_targets_active", "active"),
            ("ix_stream_targets_user_preference", "user_preference"),
            ("ix_stream_targets_last_selected_at", "last_selected_at"),
            ("ix_stream_targets_last_evaluated_at", "last_evaluated_at"),
        ):
            _create_index(index_name, "stream_targets", [column_name])
        _create_index(
            "ix_stream_targets_exchange_status_rank",
            "stream_targets",
            ["exchange", "status", "rank"],
        )

    if not _table_exists("market_quotes"):
        op.create_table(
            "market_quotes",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("exchange", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=80), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("receipt_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("bid", sa.Float(), nullable=True),
            sa.Column("ask", sa.Float(), nullable=True),
            sa.Column("bid_size", sa.Float(), nullable=True),
            sa.Column("ask_size", sa.Float(), nullable=True),
            sa.Column("mid", sa.Float(), nullable=True),
            sa.Column("spread_bps", sa.Float(), nullable=True),
            sa.Column("source", sa.String(length=40), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
        )
        for index_name, columns in (
            ("ix_market_quotes_exchange", ["exchange"]),
            ("ix_market_quotes_symbol", ["symbol"]),
            ("ix_market_quotes_timestamp", ["timestamp"]),
            ("ix_market_quotes_exchange_symbol_timestamp", ["exchange", "symbol", "timestamp"]),
        ):
            _create_index(index_name, "market_quotes", columns)

    if not _table_exists("dex_pools"):
        op.create_table(
            "dex_pools",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.String(length=40), nullable=False),
            sa.Column("chain_id", sa.String(length=40), nullable=False),
            sa.Column("dex_id", sa.String(length=80), nullable=True),
            sa.Column("pool_address", sa.String(length=140), nullable=False),
            sa.Column("base_symbol", sa.String(length=40), nullable=True),
            sa.Column("quote_symbol", sa.String(length=40), nullable=True),
            sa.Column("base_token_address", sa.String(length=140), nullable=True),
            sa.Column("quote_token_address", sa.String(length=140), nullable=True),
            sa.Column("liquidity_usd", sa.Float(), nullable=True),
            sa.Column("volume_24h", sa.Float(), nullable=True),
            sa.Column("price_usd", sa.Float(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("source", "chain_id", "pool_address", name="uq_dex_pools_source_chain_pool"),
        )
        for index_name, column_name in (
            ("ix_dex_pools_id", "id"),
            ("ix_dex_pools_source", "source"),
            ("ix_dex_pools_chain_id", "chain_id"),
            ("ix_dex_pools_dex_id", "dex_id"),
            ("ix_dex_pools_pool_address", "pool_address"),
            ("ix_dex_pools_base_symbol", "base_symbol"),
            ("ix_dex_pools_quote_symbol", "quote_symbol"),
            ("ix_dex_pools_base_token_address", "base_token_address"),
            ("ix_dex_pools_quote_token_address", "quote_token_address"),
            ("ix_dex_pools_last_seen_at", "last_seen_at"),
        ):
            _create_index(index_name, "dex_pools", [column_name])


def downgrade() -> None:
    for table_name, indexes in (
        (
            "dex_pools",
            (
                "ix_dex_pools_last_seen_at",
                "ix_dex_pools_quote_token_address",
                "ix_dex_pools_base_token_address",
                "ix_dex_pools_quote_symbol",
                "ix_dex_pools_base_symbol",
                "ix_dex_pools_pool_address",
                "ix_dex_pools_dex_id",
                "ix_dex_pools_chain_id",
                "ix_dex_pools_source",
                "ix_dex_pools_id",
            ),
        ),
        (
            "market_quotes",
            (
                "ix_market_quotes_exchange_symbol_timestamp",
                "ix_market_quotes_timestamp",
                "ix_market_quotes_symbol",
                "ix_market_quotes_exchange",
            ),
        ),
        (
            "stream_targets",
            (
                "ix_stream_targets_exchange_status_rank",
                "ix_stream_targets_last_evaluated_at",
                "ix_stream_targets_last_selected_at",
                "ix_stream_targets_user_preference",
                "ix_stream_targets_active",
                "ix_stream_targets_score",
                "ix_stream_targets_rank",
                "ix_stream_targets_status",
                "ix_stream_targets_source_type",
                "ix_stream_targets_quote",
                "ix_stream_targets_base",
                "ix_stream_targets_symbol",
                "ix_stream_targets_exchange",
                "ix_stream_targets_id",
            ),
        ),
        (
            "data_source_health",
            (
                "ix_data_source_health_last_error_at",
                "ix_data_source_health_last_success_at",
                "ix_data_source_health_last_event_at",
                "ix_data_source_health_enabled",
                "ix_data_source_health_source_type",
                "ix_data_source_health_source",
                "ix_data_source_health_id",
            ),
        ),
    ):
        if _table_exists(table_name):
            for index_name in indexes:
                if _index_exists(table_name, index_name):
                    op.drop_index(index_name, table_name=table_name)
            op.drop_table(table_name)
