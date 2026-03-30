"""Add unique index for tick idempotency.

Revision ID: 20260109_0003
Revises: 20260106_0002
Create Date: 2026-01-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260109_0003"
down_revision = "20260106_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ux_ticks_asset_trade_time",
            "ticks",
            ["asset_id", "exchange_trade_id", "time"],
            unique=True,
            postgresql_where=sa.text("exchange_trade_id IS NOT NULL"),
        )
        return

    op.create_index(
        "ux_ticks_asset_trade_time",
        "ticks",
        ["asset_id", "exchange_trade_id", "time"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_ticks_asset_trade_time", table_name="ticks")
