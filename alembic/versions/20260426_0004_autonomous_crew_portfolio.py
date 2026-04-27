"""Add autonomous crew portfolio tables.

Revision ID: 20260426_0004
Revises: 20260426_0003
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260426_0004"
down_revision = "20260426_0003"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _add_guardrail_column(column_name: str, column: sa.Column) -> None:
    if not _column_exists("agent_guardrail_profiles", column_name):
        op.add_column("agent_guardrail_profiles", column)


def upgrade() -> None:
    _add_guardrail_column("research_enabled", sa.Column("research_enabled", sa.Boolean(), nullable=True))
    _add_guardrail_column("trigger_monitor_enabled", sa.Column("trigger_monitor_enabled", sa.Boolean(), nullable=True))
    _add_guardrail_column("research_interval_seconds", sa.Column("research_interval_seconds", sa.Integer(), nullable=True))
    _add_guardrail_column("bankroll_reset_drawdown_pct", sa.Column("bankroll_reset_drawdown_pct", sa.Float(), nullable=True))
    _add_guardrail_column("default_starting_bankroll", sa.Column("default_starting_bankroll", sa.Float(), nullable=True))
    _add_guardrail_column("ai_paper_account_id", sa.Column("ai_paper_account_id", sa.Integer(), nullable=True))
    if not _index_exists("agent_guardrail_profiles", "ix_agent_guardrail_profiles_ai_paper_account_id"):
        op.create_index(
            "ix_agent_guardrail_profiles_ai_paper_account_id",
            "agent_guardrail_profiles",
            ["ai_paper_account_id"],
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE agent_guardrail_profiles
            SET
                research_enabled = COALESCE(research_enabled, false),
                trigger_monitor_enabled = COALESCE(trigger_monitor_enabled, false),
                research_interval_seconds = COALESCE(research_interval_seconds, 1800),
                max_position_pct = COALESCE(max_position_pct, 0.35),
                max_daily_loss_pct = COALESCE(max_daily_loss_pct, 0.10),
                max_open_positions = COALESCE(max_open_positions, 12),
                max_trades_per_day = COALESCE(max_trades_per_day, 40),
                bankroll_reset_drawdown_pct = COALESCE(bankroll_reset_drawdown_pct, 0.95),
                default_starting_bankroll = COALESCE(default_starting_bankroll, 10000.0)
            """
        )
    )

    if not _table_exists("agent_research_theses"):
        op.create_table(
            "agent_research_theses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("snapshot_id", sa.Integer(), nullable=True),
            sa.Column("recommendation_id", sa.Integer(), nullable=True),
            sa.Column("exchange", sa.String(length=20), nullable=False),
            sa.Column("symbol", sa.String(length=50), nullable=False),
            sa.Column("strategy_name", sa.String(length=100), nullable=False),
            sa.Column("strategy_params", sa.JSON(), nullable=True),
            sa.Column("side", sa.String(length=20), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("thesis", sa.Text(), nullable=False),
            sa.Column("risk_notes", sa.Text(), nullable=True),
            sa.Column("entry_condition", sa.String(length=30), nullable=False),
            sa.Column("entry_target", sa.Float(), nullable=True),
            sa.Column("take_profit_target", sa.Float(), nullable=True),
            sa.Column("stop_loss_target", sa.Float(), nullable=True),
            sa.Column("latest_observed_price", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lessons_used", sa.JSON(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["paper_accounts.id"]),
            sa.ForeignKeyConstraint(["recommendation_id"], ["agent_recommendations.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
            sa.ForeignKeyConstraint(["snapshot_id"], ["research_snapshots.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        for index_name, column_name in (
            ("ix_agent_research_theses_id", "id"),
            ("ix_agent_research_theses_user_id", "user_id"),
            ("ix_agent_research_theses_account_id", "account_id"),
            ("ix_agent_research_theses_run_id", "run_id"),
            ("ix_agent_research_theses_snapshot_id", "snapshot_id"),
            ("ix_agent_research_theses_recommendation_id", "recommendation_id"),
            ("ix_agent_research_theses_exchange", "exchange"),
            ("ix_agent_research_theses_symbol", "symbol"),
            ("ix_agent_research_theses_status", "status"),
            ("ix_agent_research_theses_expires_at", "expires_at"),
        ):
            op.create_index(index_name, "agent_research_theses", [column_name])

    if not _table_exists("agent_portfolio_snapshots"):
        op.create_table(
            "agent_portfolio_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("cash_balance", sa.Float(), nullable=True),
            sa.Column("invested_value", sa.Float(), nullable=True),
            sa.Column("equity", sa.Float(), nullable=True),
            sa.Column("realized_pnl", sa.Float(), nullable=True),
            sa.Column("unrealized_pnl", sa.Float(), nullable=True),
            sa.Column("all_time_pnl", sa.Float(), nullable=True),
            sa.Column("current_cycle_pnl", sa.Float(), nullable=True),
            sa.Column("drawdown_pct", sa.Float(), nullable=True),
            sa.Column("exposure_pct", sa.Float(), nullable=True),
            sa.Column("open_positions", sa.Integer(), nullable=True),
            sa.Column("reset_count", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["paper_accounts.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        for index_name, column_name in (
            ("ix_agent_portfolio_snapshots_id", "id"),
            ("ix_agent_portfolio_snapshots_user_id", "user_id"),
            ("ix_agent_portfolio_snapshots_account_id", "account_id"),
            ("ix_agent_portfolio_snapshots_created_at", "created_at"),
        ):
            op.create_index(index_name, "agent_portfolio_snapshots", [column_name])

    if not _table_exists("agent_bankroll_resets"):
        op.create_table(
            "agent_bankroll_resets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("reset_number", sa.Integer(), nullable=False),
            sa.Column("starting_bankroll", sa.Float(), nullable=False),
            sa.Column("equity_before_reset", sa.Float(), nullable=False),
            sa.Column("cash_before_reset", sa.Float(), nullable=True),
            sa.Column("invested_before_reset", sa.Float(), nullable=True),
            sa.Column("drawdown_pct", sa.Float(), nullable=False),
            sa.Column("realized_pnl", sa.Float(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("lessons", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["paper_accounts.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        for index_name, column_name in (
            ("ix_agent_bankroll_resets_id", "id"),
            ("ix_agent_bankroll_resets_user_id", "user_id"),
            ("ix_agent_bankroll_resets_account_id", "account_id"),
            ("ix_agent_bankroll_resets_created_at", "created_at"),
        ):
            op.create_index(index_name, "agent_bankroll_resets", [column_name])

    if not _table_exists("agent_lessons"):
        op.create_table(
            "agent_lessons",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=True),
            sa.Column("thesis_id", sa.Integer(), nullable=True),
            sa.Column("recommendation_id", sa.Integer(), nullable=True),
            sa.Column("symbol", sa.String(length=50), nullable=True),
            sa.Column("strategy_name", sa.String(length=100), nullable=True),
            sa.Column("outcome", sa.String(length=50), nullable=False),
            sa.Column("return_pct", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("lesson", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["paper_accounts.id"]),
            sa.ForeignKeyConstraint(["recommendation_id"], ["agent_recommendations.id"]),
            sa.ForeignKeyConstraint(["thesis_id"], ["agent_research_theses.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        for index_name, column_name in (
            ("ix_agent_lessons_id", "id"),
            ("ix_agent_lessons_user_id", "user_id"),
            ("ix_agent_lessons_account_id", "account_id"),
            ("ix_agent_lessons_thesis_id", "thesis_id"),
            ("ix_agent_lessons_recommendation_id", "recommendation_id"),
            ("ix_agent_lessons_symbol", "symbol"),
            ("ix_agent_lessons_strategy_name", "strategy_name"),
            ("ix_agent_lessons_outcome", "outcome"),
            ("ix_agent_lessons_created_at", "created_at"),
        ):
            op.create_index(index_name, "agent_lessons", [column_name])

    if bind.dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_agent_guardrail_profiles_ai_paper_account_id_paper_accounts",
            "agent_guardrail_profiles",
            "paper_accounts",
            ["ai_paper_account_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "fk_agent_guardrail_profiles_ai_paper_account_id_paper_accounts",
            "agent_guardrail_profiles",
            type_="foreignkey",
        )

    for table_name, indexes in (
        (
            "agent_lessons",
            (
                "ix_agent_lessons_created_at",
                "ix_agent_lessons_outcome",
                "ix_agent_lessons_strategy_name",
                "ix_agent_lessons_symbol",
                "ix_agent_lessons_recommendation_id",
                "ix_agent_lessons_thesis_id",
                "ix_agent_lessons_account_id",
                "ix_agent_lessons_user_id",
                "ix_agent_lessons_id",
            ),
        ),
        (
            "agent_bankroll_resets",
            (
                "ix_agent_bankroll_resets_created_at",
                "ix_agent_bankroll_resets_account_id",
                "ix_agent_bankroll_resets_user_id",
                "ix_agent_bankroll_resets_id",
            ),
        ),
        (
            "agent_portfolio_snapshots",
            (
                "ix_agent_portfolio_snapshots_created_at",
                "ix_agent_portfolio_snapshots_account_id",
                "ix_agent_portfolio_snapshots_user_id",
                "ix_agent_portfolio_snapshots_id",
            ),
        ),
        (
            "agent_research_theses",
            (
                "ix_agent_research_theses_expires_at",
                "ix_agent_research_theses_status",
                "ix_agent_research_theses_symbol",
                "ix_agent_research_theses_exchange",
                "ix_agent_research_theses_recommendation_id",
                "ix_agent_research_theses_snapshot_id",
                "ix_agent_research_theses_run_id",
                "ix_agent_research_theses_account_id",
                "ix_agent_research_theses_user_id",
                "ix_agent_research_theses_id",
            ),
        ),
    ):
        if _table_exists(table_name):
            for index_name in indexes:
                if _index_exists(table_name, index_name):
                    op.drop_index(index_name, table_name=table_name)
            op.drop_table(table_name)

    if _index_exists("agent_guardrail_profiles", "ix_agent_guardrail_profiles_ai_paper_account_id"):
        op.drop_index("ix_agent_guardrail_profiles_ai_paper_account_id", table_name="agent_guardrail_profiles")

    for column_name in (
        "ai_paper_account_id",
        "default_starting_bankroll",
        "bankroll_reset_drawdown_pct",
        "research_interval_seconds",
        "trigger_monitor_enabled",
        "research_enabled",
    ):
        if _column_exists("agent_guardrail_profiles", column_name):
            op.drop_column("agent_guardrail_profiles", column_name)
