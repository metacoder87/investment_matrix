"""Add backtest reports and paper trading scheduler tables.

Revision ID: 20260109_0005
Revises: 20260109_0004
Create Date: 2026-01-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260109_0005"
down_revision = "20260109_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_accounts", sa.Column("last_equity", sa.Float(), server_default="0", nullable=True))
    op.add_column("paper_accounts", sa.Column("equity_peak", sa.Float(), server_default="0", nullable=True))
    op.add_column("paper_accounts", sa.Column("last_signal", sa.String(length=20), nullable=True))
    op.add_column("paper_accounts", sa.Column("last_step_at", sa.DateTime(), nullable=True))

    op.create_table(
        "paper_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("lookback", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("strategy_params", sa.JSON(), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("disabled_reason", sa.String(length=200), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_paper_schedules_account_id", "paper_schedules", ["account_id"])
    op.create_index("ix_paper_schedules_symbol", "paper_schedules", ["symbol"])

    op.create_table(
        "backtest_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_backtest_reports_symbol", "backtest_reports", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_backtest_reports_symbol", table_name="backtest_reports")
    op.drop_table("backtest_reports")

    op.drop_index("ix_paper_schedules_symbol", table_name="paper_schedules")
    op.drop_index("ix_paper_schedules_account_id", table_name="paper_schedules")
    op.drop_table("paper_schedules")

    op.drop_column("paper_accounts", "last_step_at")
    op.drop_column("paper_accounts", "last_signal")
    op.drop_column("paper_accounts", "equity_peak")
    op.drop_column("paper_accounts", "last_equity")
