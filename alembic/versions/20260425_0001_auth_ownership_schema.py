"""Add auth and ownership schema.

Revision ID: 20260425_0001
Revises: 20260124_0001
Create Date: 2026-04-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260425_0001"
down_revision = "20260124_0001"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in inspect(op.get_bind()).get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(idx["name"] == index_name for idx in inspect(op.get_bind()).get_indexes(table_name))


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(
        constraint["name"] == constraint_name
        for constraint in inspect(op.get_bind()).get_unique_constraints(table_name)
    )


def _foreign_key_exists(table_name: str, constraint_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(
        constraint["name"] == constraint_name
        for constraint in inspect(op.get_bind()).get_foreign_keys(table_name)
    )


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _create_fk_if_missing(
    constraint_name: str,
    source_table: str,
    referent_table: str,
    local_cols: list[str],
    remote_cols: list[str],
) -> None:
    if not _foreign_key_exists(source_table, constraint_name):
        op.create_foreign_key(
            constraint_name,
            source_table,
            referent_table,
            local_cols,
            remote_cols,
            ondelete="SET NULL",
        )


def upgrade() -> None:
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("hashed_password", sa.String(), nullable=False),
            sa.Column("full_name", sa.String(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("totp_secret", sa.String(), nullable=True),
        )
        op.create_index("ix_users_id", "users", ["id"], unique=False)
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    _add_column_if_missing("portfolios", sa.Column("user_id", sa.Integer(), nullable=True))
    _add_column_if_missing(
        "portfolios",
        sa.Column("is_paper", sa.Boolean(), nullable=True, server_default=sa.text("true")),
    )
    _add_column_if_missing(
        "portfolios",
        sa.Column("auto_trade_enabled", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    _add_column_if_missing(
        "portfolios",
        sa.Column("balance_cash", sa.Float(), nullable=True, server_default="0"),
    )
    _add_column_if_missing("portfolios", sa.Column("encrypted_api_key", sa.String(), nullable=True))
    _add_column_if_missing("portfolios", sa.Column("encrypted_api_secret", sa.String(), nullable=True))
    _create_index_if_missing("ix_portfolios_user_id", "portfolios", ["user_id"])
    _create_fk_if_missing("fk_portfolios_user_id_users", "portfolios", "users", ["user_id"], ["id"])
    _drop_index_if_exists("ix_portfolios_name", "portfolios")
    _create_index_if_missing("ix_portfolios_name", "portfolios", ["name"])
    if not _unique_constraint_exists("portfolios", "uq_portfolios_user_name"):
        op.create_unique_constraint("uq_portfolios_user_name", "portfolios", ["user_id", "name"])

    if not _table_exists("transactions"):
        op.create_table(
            "transactions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("portfolio_id", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column(
                "type",
                sa.Enum("DEPOSIT", "WITHDRAWAL", name="transactiontype"),
                nullable=False,
            ),
            sa.Column("timestamp", sa.DateTime(), nullable=True),
            sa.Column("description", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        )
        op.create_index("ix_transactions_id", "transactions", ["id"], unique=False)

    _add_column_if_missing("paper_accounts", sa.Column("user_id", sa.Integer(), nullable=True))
    _create_index_if_missing("ix_paper_accounts_user_id", "paper_accounts", ["user_id"])
    _create_fk_if_missing("fk_paper_accounts_user_id_users", "paper_accounts", "users", ["user_id"], ["id"])
    _drop_index_if_exists("ix_paper_accounts_name", "paper_accounts")
    _create_index_if_missing("ix_paper_accounts_name", "paper_accounts", ["name"])
    if not _unique_constraint_exists("paper_accounts", "uq_paper_accounts_user_name"):
        op.create_unique_constraint("uq_paper_accounts_user_name", "paper_accounts", ["user_id", "name"])

    _add_column_if_missing("backtest_runs", sa.Column("user_id", sa.Integer(), nullable=True))
    _create_index_if_missing("ix_backtest_runs_user_id", "backtest_runs", ["user_id"])
    _create_fk_if_missing("fk_backtest_runs_user_id_users", "backtest_runs", "users", ["user_id"], ["id"])

    _add_column_if_missing("backtest_reports", sa.Column("user_id", sa.Integer(), nullable=True))
    _create_index_if_missing("ix_backtest_reports_user_id", "backtest_reports", ["user_id"])
    _create_fk_if_missing("fk_backtest_reports_user_id_users", "backtest_reports", "users", ["user_id"], ["id"])


def downgrade() -> None:
    if _foreign_key_exists("backtest_reports", "fk_backtest_reports_user_id_users"):
        op.drop_constraint("fk_backtest_reports_user_id_users", "backtest_reports", type_="foreignkey")
    if _index_exists("backtest_reports", "ix_backtest_reports_user_id"):
        op.drop_index("ix_backtest_reports_user_id", table_name="backtest_reports")
    if _column_exists("backtest_reports", "user_id"):
        op.drop_column("backtest_reports", "user_id")

    if _foreign_key_exists("backtest_runs", "fk_backtest_runs_user_id_users"):
        op.drop_constraint("fk_backtest_runs_user_id_users", "backtest_runs", type_="foreignkey")
    if _index_exists("backtest_runs", "ix_backtest_runs_user_id"):
        op.drop_index("ix_backtest_runs_user_id", table_name="backtest_runs")
    if _column_exists("backtest_runs", "user_id"):
        op.drop_column("backtest_runs", "user_id")

    if _unique_constraint_exists("paper_accounts", "uq_paper_accounts_user_name"):
        op.drop_constraint("uq_paper_accounts_user_name", "paper_accounts", type_="unique")
    if _foreign_key_exists("paper_accounts", "fk_paper_accounts_user_id_users"):
        op.drop_constraint("fk_paper_accounts_user_id_users", "paper_accounts", type_="foreignkey")
    if _index_exists("paper_accounts", "ix_paper_accounts_user_id"):
        op.drop_index("ix_paper_accounts_user_id", table_name="paper_accounts")
    if _index_exists("paper_accounts", "ix_paper_accounts_name"):
        op.drop_index("ix_paper_accounts_name", table_name="paper_accounts")
    op.create_index("ix_paper_accounts_name", "paper_accounts", ["name"], unique=True)
    if _column_exists("paper_accounts", "user_id"):
        op.drop_column("paper_accounts", "user_id")

    if _table_exists("transactions"):
        op.drop_index("ix_transactions_id", table_name="transactions")
        op.drop_table("transactions")

    if _unique_constraint_exists("portfolios", "uq_portfolios_user_name"):
        op.drop_constraint("uq_portfolios_user_name", "portfolios", type_="unique")
    if _foreign_key_exists("portfolios", "fk_portfolios_user_id_users"):
        op.drop_constraint("fk_portfolios_user_id_users", "portfolios", type_="foreignkey")
    if _index_exists("portfolios", "ix_portfolios_user_id"):
        op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    if _index_exists("portfolios", "ix_portfolios_name"):
        op.drop_index("ix_portfolios_name", table_name="portfolios")
    op.create_index("ix_portfolios_name", "portfolios", ["name"], unique=True)
    for column_name in (
        "encrypted_api_secret",
        "encrypted_api_key",
        "balance_cash",
        "auto_trade_enabled",
        "is_paper",
        "user_id",
    ):
        if _column_exists("portfolios", column_name):
            op.drop_column("portfolios", column_name)

    if _table_exists("users"):
        op.drop_index("ix_users_email", table_name="users")
        op.drop_index("ix_users_id", table_name="users")
        op.drop_table("users")
