"""Add market_trades hypertable for tick trades.

Revision ID: 20251215_0002
Revises: 20251215_0001
Create Date: 2025-12-15

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251215_0002"
down_revision = "20251215_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.create_table(
        "market_trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("receipt_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=True),
    )
    op.create_index("ix_market_trades_exchange", "market_trades", ["exchange"])
    op.create_index("ix_market_trades_symbol", "market_trades", ["symbol"])
    op.create_index("ix_market_trades_timestamp", "market_trades", ["timestamp"])

    if is_postgres:
        op.execute("SELECT create_hypertable('market_trades', 'timestamp', if_not_exists => TRUE);")


def downgrade() -> None:
    op.drop_index("ix_market_trades_timestamp", table_name="market_trades")
    op.drop_index("ix_market_trades_symbol", table_name="market_trades")
    op.drop_index("ix_market_trades_exchange", table_name="market_trades")
    op.drop_table("market_trades")
