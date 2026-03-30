"""Add exchange to prices.

Revision ID: 20260113_0006
Revises: 20260109_0005
Create Date: 2026-01-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260113_0006"
down_revision = "20260109_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prices",
        sa.Column("exchange", sa.String(length=20), server_default="coinbase", nullable=False),
    )
    op.create_index("ix_prices_exchange", "prices", ["exchange"])
    op.create_index("ix_prices_exchange_symbol_time", "prices", ["exchange", "symbol", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_prices_exchange_symbol_time", table_name="prices")
    op.drop_index("ix_prices_exchange", table_name="prices")
    op.drop_column("prices", "exchange")
