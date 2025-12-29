"""Initial schema (Timescale-ready).

Revision ID: 20251215_0001
Revises:
Create Date: 2025-12-15

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251215_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    op.create_table(
        "coins",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("market_cap_rank", sa.Integer(), nullable=True),
        sa.Column("image", sa.String(), nullable=True),
    )
    op.create_index("ix_coins_symbol", "coins", ["symbol"])

    op.create_table(
        "prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("open", sa.Numeric(), nullable=True),
        sa.Column("high", sa.Numeric(), nullable=True),
        sa.Column("low", sa.Numeric(), nullable=True),
        sa.Column("close", sa.Numeric(), nullable=True),
        sa.Column("volume", sa.Numeric(), nullable=True),
    )
    op.create_index("ix_prices_symbol", "prices", ["symbol"])
    op.create_index("ix_prices_timestamp", "prices", ["timestamp"])

    op.create_table(
        "indicators",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("rsi", sa.Numeric(), nullable=True),
        sa.Column("macd", sa.Numeric(), nullable=True),
    )
    op.create_index("ix_indicators_symbol", "indicators", ["symbol"])
    op.create_index("ix_indicators_timestamp", "indicators", ["timestamp"])

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=4), nullable=False),
        sa.Column("qty", sa.Numeric(), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("fee", sa.Numeric(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_trades_user_id", "trades", ["user_id"])

    op.create_table(
        "wallets",
        sa.Column("user_id", sa.UUID(), primary_key=True),
        sa.Column("encrypted_mnemonic", sa.Text(), nullable=False),
        sa.Column("addresses", sa.JSON(), nullable=True),
    )

    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False, unique=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )

    if is_postgres:
        op.execute("SELECT create_hypertable('prices', 'timestamp', if_not_exists => TRUE);")
        op.execute("SELECT create_hypertable('indicators', 'timestamp', if_not_exists => TRUE);")


def downgrade() -> None:
    op.drop_table("news_articles")
    op.drop_table("wallets")
    op.drop_index("ix_trades_user_id", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_indicators_timestamp", table_name="indicators")
    op.drop_index("ix_indicators_symbol", table_name="indicators")
    op.drop_table("indicators")
    op.drop_index("ix_prices_timestamp", table_name="prices")
    op.drop_index("ix_prices_symbol", table_name="prices")
    op.drop_table("prices")
    op.drop_index("ix_coins_symbol", table_name="coins")
    op.drop_table("coins")
