"""Add exchange to holdings.

Revision ID: 20260119_0007
Revises: 20260113_0006
Create Date: 2026-01-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260119_0007"
down_revision = "20260113_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add exchange column
    op.add_column(
        "holdings",
        sa.Column("exchange", sa.String(), server_default="coinbase", nullable=False),
    )
    # Add index (might want to name it uniquely in postgres)
    op.create_index(op.f("ix_holdings_exchange"), "holdings", ["exchange"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_holdings_exchange"), table_name="holdings")
    op.drop_column("holdings", "exchange")
