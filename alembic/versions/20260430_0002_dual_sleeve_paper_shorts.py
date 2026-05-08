"""Add dual-sleeve paper short fields.

Revision ID: 20260430_0002
Revises: 20260430_0001
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260430_0002"
down_revision = "20260430_0001"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _table_exists(table_name) and _column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE paperorderside ADD VALUE IF NOT EXISTS 'short'")
        op.execute("ALTER TYPE paperorderside ADD VALUE IF NOT EXISTS 'cover'")

    _add_column_if_missing("paper_positions", sa.Column("side", sa.String(length=20), nullable=False, server_default="long"))
    _add_column_if_missing("paper_positions", sa.Column("reserved_collateral", sa.Float(), nullable=False, server_default="0"))
    _add_column_if_missing("paper_positions", sa.Column("take_profit", sa.Float(), nullable=True))
    _add_column_if_missing("paper_positions", sa.Column("stop_loss", sa.Float(), nullable=True))
    _add_column_if_missing("paper_positions", sa.Column("trailing_peak", sa.Float(), nullable=True))
    _add_column_if_missing("paper_positions", sa.Column("trailing_trough", sa.Float(), nullable=True))

    _add_column_if_missing("agent_recommendations", sa.Column("side", sa.String(length=20), nullable=False, server_default="long"))
    _add_column_if_missing("agent_recommendations", sa.Column("sleeve", sa.String(length=20), nullable=True))
    _add_column_if_missing("agent_recommendations", sa.Column("entry_score", sa.Float(), nullable=True))
    _add_column_if_missing("agent_recommendations", sa.Column("exit_score", sa.Float(), nullable=True))
    _add_column_if_missing("agent_recommendations", sa.Column("formula_inputs", sa.JSON(), nullable=True))
    _add_column_if_missing("agent_recommendations", sa.Column("formula_outputs", sa.JSON(), nullable=True))
    _add_column_if_missing("agent_recommendations", sa.Column("strategy_version", sa.String(length=40), nullable=True))

    _add_column_if_missing("agent_research_theses", sa.Column("sleeve", sa.String(length=20), nullable=True))
    _add_column_if_missing("agent_research_theses", sa.Column("entry_score", sa.Float(), nullable=True))
    _add_column_if_missing("agent_research_theses", sa.Column("exit_score", sa.Float(), nullable=True))
    _add_column_if_missing("agent_research_theses", sa.Column("formula_inputs", sa.JSON(), nullable=True))
    _add_column_if_missing("agent_research_theses", sa.Column("formula_outputs", sa.JSON(), nullable=True))
    _add_column_if_missing("agent_research_theses", sa.Column("strategy_version", sa.String(length=40), nullable=True))

    if _table_exists("backtest_trades") and bind.dialect.name != "sqlite":
        op.alter_column("backtest_trades", "side", existing_type=sa.String(length=4), type_=sa.String(length=10))


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists("backtest_trades") and bind.dialect.name != "sqlite":
        op.alter_column("backtest_trades", "side", existing_type=sa.String(length=10), type_=sa.String(length=4))

    for column in ("strategy_version", "formula_outputs", "formula_inputs", "exit_score", "entry_score", "sleeve"):
        _drop_column_if_exists("agent_research_theses", column)

    for column in ("strategy_version", "formula_outputs", "formula_inputs", "exit_score", "entry_score", "sleeve", "side"):
        _drop_column_if_exists("agent_recommendations", column)

    for column in ("trailing_trough", "trailing_peak", "stop_loss", "take_profit", "reserved_collateral", "side"):
        _drop_column_if_exists("paper_positions", column)

