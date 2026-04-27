"""Add market data status and agent audit tables.

Revision ID: 20260426_0002
Revises: 20260425_0001
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260426_0002"
down_revision = "20260425_0001"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("asset_data_status"):
        op.create_table(
            "asset_data_status",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exchange", sa.String(length=20), nullable=False),
            sa.Column("symbol", sa.String(length=50), nullable=False),
            sa.Column("base_symbol", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("is_supported", sa.Boolean(), nullable=True),
            sa.Column("is_analyzable", sa.Boolean(), nullable=True),
            sa.Column("row_count", sa.Integer(), nullable=True),
            sa.Column("latest_candle_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_backfill_task_id", sa.String(length=100), nullable=True),
            sa.Column("last_backfill_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_backfill_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_backfill_failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_failure_reason", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("exchange", "symbol", name="uq_asset_data_status_exchange_symbol"),
        )
        op.create_index("ix_asset_data_status_id", "asset_data_status", ["id"])
        op.create_index("ix_asset_data_status_exchange", "asset_data_status", ["exchange"])
        op.create_index("ix_asset_data_status_symbol", "asset_data_status", ["symbol"])
        op.create_index("ix_asset_data_status_base_symbol", "asset_data_status", ["base_symbol"])
        op.create_index("ix_asset_data_status_status", "asset_data_status", ["status"])

    if not _table_exists("agent_guardrail_profiles"):
        op.create_table(
            "agent_guardrail_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("autonomous_enabled", sa.Boolean(), nullable=True),
            sa.Column("max_position_pct", sa.Float(), nullable=True),
            sa.Column("max_daily_loss_pct", sa.Float(), nullable=True),
            sa.Column("max_open_positions", sa.Integer(), nullable=True),
            sa.Column("max_trades_per_day", sa.Integer(), nullable=True),
            sa.Column("min_data_freshness_seconds", sa.Integer(), nullable=True),
            sa.Column("min_backtest_return_pct", sa.Float(), nullable=True),
            sa.Column("min_backtest_sharpe", sa.Float(), nullable=True),
            sa.Column("allowed_symbols", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.UniqueConstraint("user_id", name="uq_agent_guardrail_profiles_user_id"),
        )
        op.create_index("ix_agent_guardrail_profiles_id", "agent_guardrail_profiles", ["id"])
        op.create_index("ix_agent_guardrail_profiles_user_id", "agent_guardrail_profiles", ["user_id"])

    if not _table_exists("agent_recommendations"):
        op.create_table(
            "agent_recommendations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("agent_name", sa.String(length=100), nullable=False),
            sa.Column("strategy_name", sa.String(length=100), nullable=False),
            sa.Column("exchange", sa.String(length=20), nullable=False),
            sa.Column("symbol", sa.String(length=50), nullable=False),
            sa.Column("action", sa.String(length=20), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("thesis", sa.Text(), nullable=False),
            sa.Column("risk_notes", sa.Text(), nullable=True),
            sa.Column("source_data_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("backtest_run_id", sa.Integer(), nullable=True),
            sa.Column("paper_account_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("execution_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
            sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        op.create_index("ix_agent_recommendations_id", "agent_recommendations", ["id"])
        op.create_index("ix_agent_recommendations_user_id", "agent_recommendations", ["user_id"])
        op.create_index("ix_agent_recommendations_exchange", "agent_recommendations", ["exchange"])
        op.create_index("ix_agent_recommendations_symbol", "agent_recommendations", ["symbol"])
        op.create_index("ix_agent_recommendations_backtest_run_id", "agent_recommendations", ["backtest_run_id"])
        op.create_index("ix_agent_recommendations_paper_account_id", "agent_recommendations", ["paper_account_id"])
        op.create_index("ix_agent_recommendations_status", "agent_recommendations", ["status"])

    if not _table_exists("agent_audit_logs"):
        op.create_table(
            "agent_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("recommendation_id", sa.Integer(), nullable=True),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["recommendation_id"], ["agent_recommendations.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        op.create_index("ix_agent_audit_logs_id", "agent_audit_logs", ["id"])
        op.create_index("ix_agent_audit_logs_user_id", "agent_audit_logs", ["user_id"])
        op.create_index("ix_agent_audit_logs_recommendation_id", "agent_audit_logs", ["recommendation_id"])
        op.create_index("ix_agent_audit_logs_event_type", "agent_audit_logs", ["event_type"])
        op.create_index("ix_agent_audit_logs_created_at", "agent_audit_logs", ["created_at"])


def downgrade() -> None:
    for index_name in (
        "ix_agent_audit_logs_created_at",
        "ix_agent_audit_logs_event_type",
        "ix_agent_audit_logs_recommendation_id",
        "ix_agent_audit_logs_user_id",
        "ix_agent_audit_logs_id",
    ):
        op.drop_index(index_name, table_name="agent_audit_logs")
    op.drop_table("agent_audit_logs")

    for index_name in (
        "ix_agent_recommendations_status",
        "ix_agent_recommendations_paper_account_id",
        "ix_agent_recommendations_backtest_run_id",
        "ix_agent_recommendations_symbol",
        "ix_agent_recommendations_exchange",
        "ix_agent_recommendations_user_id",
        "ix_agent_recommendations_id",
    ):
        op.drop_index(index_name, table_name="agent_recommendations")
    op.drop_table("agent_recommendations")

    op.drop_index("ix_agent_guardrail_profiles_user_id", table_name="agent_guardrail_profiles")
    op.drop_index("ix_agent_guardrail_profiles_id", table_name="agent_guardrail_profiles")
    op.drop_table("agent_guardrail_profiles")

    for index_name in (
        "ix_asset_data_status_status",
        "ix_asset_data_status_base_symbol",
        "ix_asset_data_status_symbol",
        "ix_asset_data_status_exchange",
        "ix_asset_data_status_id",
    ):
        op.drop_index(index_name, table_name="asset_data_status")
    op.drop_table("asset_data_status")
