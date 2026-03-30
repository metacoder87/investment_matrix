"""Add market data fields to coins.

Revision ID: 20260124_0001
Revises: 20260119_0007
Create Date: 2026-01-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260124_0001"
down_revision = "20260119_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("coins", sa.Column("market_cap", sa.Numeric(), nullable=True))
    op.add_column("coins", sa.Column("current_price", sa.Numeric(), nullable=True))
    op.add_column("coins", sa.Column("price_change_percentage_24h", sa.Float(), nullable=True))
    op.add_column("coins", sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("coins", "last_updated")
    op.drop_column("coins", "price_change_percentage_24h")
    op.drop_column("coins", "current_price")
    op.drop_column("coins", "market_cap")
