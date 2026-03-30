"""Add backtesting and paper trading tables.

Revision ID: 20260109_0004
Revises: 20260109_0003
Create Date: 2026-01-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260109_0004"
down_revision = "20260109_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_cash", sa.Float(), nullable=False),
        sa.Column("fee_rate", sa.Float(), nullable=False),
        sa.Column("slippage_bps", sa.Float(), nullable=False),
        sa.Column("max_position_pct", sa.Float(), nullable=False),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("strategy_params", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("equity_curve", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_backtest_runs_symbol", "backtest_runs", ["symbol"])

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False),
        sa.Column("cash_balance", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_backtest_trades_run_id", "backtest_trades", ["run_id"])
    op.create_index("ix_backtest_trades_timestamp", "backtest_trades", ["timestamp"])

    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("base_currency", sa.String(length=10), nullable=True),
        sa.Column("cash_balance", sa.Float(), nullable=True),
        sa.Column("fee_rate", sa.Float(), nullable=True),
        sa.Column("slippage_bps", sa.Float(), nullable=True),
        sa.Column("max_position_pct", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_paper_accounts_name", "paper_accounts", ["name"], unique=True)

    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("avg_entry_price", sa.Float(), nullable=True),
        sa.Column("last_price", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_paper_positions_account_id", "paper_positions", ["account_id"])
    op.create_index("ix_paper_positions_symbol", "paper_positions", ["symbol"])

    from sqlalchemy.dialects.postgresql import ENUM

    paper_side = ENUM("buy", "sell", name="paperorderside", create_type=False)
    paper_status = ENUM("filled", "rejected", "skipped", name="paperorderstatus", create_type=False)
    
    bind = op.get_bind()
    
    # Safe Idempotent Creation using DO block
    bind.execute(sa.text("""
    DO $$ BEGIN
        CREATE TYPE paperorderside AS ENUM ('buy', 'sell');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """))
    
    bind.execute(sa.text("""
    DO $$ BEGIN
        CREATE TYPE paperorderstatus AS ENUM ('filled', 'rejected', 'skipped');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """))


    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("side", paper_side, nullable=False),
        sa.Column("status", paper_status, nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False),
        sa.Column("strategy", sa.String(length=50), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_paper_orders_account_id", "paper_orders", ["account_id"])
    op.create_index("ix_paper_orders_symbol", "paper_orders", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_paper_orders_symbol", table_name="paper_orders")
    op.drop_index("ix_paper_orders_account_id", table_name="paper_orders")
    op.drop_table("paper_orders")

    op.drop_index("ix_paper_positions_symbol", table_name="paper_positions")
    op.drop_index("ix_paper_positions_account_id", table_name="paper_positions")
    op.drop_table("paper_positions")

    op.drop_index("ix_paper_accounts_name", table_name="paper_accounts")
    op.drop_table("paper_accounts")

    op.drop_index("ix_backtest_trades_timestamp", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_run_id", table_name="backtest_trades")
    op.drop_table("backtest_trades")

    op.drop_index("ix_backtest_runs_symbol", table_name="backtest_runs")
    op.drop_table("backtest_runs")

    bind = op.get_bind()
    paper_side = sa.Enum("buy", "sell", name="paperorderside")
    paper_status = sa.Enum("filled", "rejected", "skipped", name="paperorderstatus")
    paper_status.drop(bind, checkfirst=True)
    paper_side.drop(bind, checkfirst=True)
