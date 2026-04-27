"""Add agent trace events and exchange market discovery.

Revision ID: 20260427_0005
Revises: 20260426_0004
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260427_0005"
down_revision = "20260426_0004"
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


def _fk_exists(table_name: str, fk_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return fk_name in {fk["name"] for fk in inspect(op.get_bind()).get_foreign_keys(table_name)}


def _create_index(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()

    if not _column_exists("agent_guardrail_profiles", "trade_cadence_mode"):
        op.add_column(
            "agent_guardrail_profiles",
            sa.Column("trade_cadence_mode", sa.String(length=40), nullable=True),
        )
    bind.execute(
        sa.text(
            """
            UPDATE agent_guardrail_profiles
            SET trade_cadence_mode = COALESCE(trade_cadence_mode, 'aggressive_paper')
            """
        )
    )

    if not _table_exists("exchange_markets"):
        op.create_table(
            "exchange_markets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exchange", sa.String(length=20), nullable=False),
            sa.Column("ccxt_symbol", sa.String(length=80), nullable=False),
            sa.Column("db_symbol", sa.String(length=80), nullable=False),
            sa.Column("base", sa.String(length=30), nullable=False),
            sa.Column("quote", sa.String(length=30), nullable=False),
            sa.Column("spot", sa.Boolean(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=True),
            sa.Column("is_analyzable", sa.Boolean(), nullable=True),
            sa.Column("min_order_amount", sa.Float(), nullable=True),
            sa.Column("min_order_cost", sa.Float(), nullable=True),
            sa.Column("precision_json", sa.JSON(), nullable=True),
            sa.Column("limits_json", sa.JSON(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("exchange", "db_symbol", name="uq_exchange_markets_exchange_db_symbol"),
        )
        for index_name, column_name in (
            ("ix_exchange_markets_id", "id"),
            ("ix_exchange_markets_exchange", "exchange"),
            ("ix_exchange_markets_ccxt_symbol", "ccxt_symbol"),
            ("ix_exchange_markets_db_symbol", "db_symbol"),
            ("ix_exchange_markets_base", "base"),
            ("ix_exchange_markets_quote", "quote"),
            ("ix_exchange_markets_spot", "spot"),
            ("ix_exchange_markets_active", "active"),
            ("ix_exchange_markets_is_analyzable", "is_analyzable"),
            ("ix_exchange_markets_last_seen_at", "last_seen_at"),
        ):
            _create_index(index_name, "exchange_markets", [column_name])

    if not _table_exists("agent_trace_events"):
        op.create_table(
            "agent_trace_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("recommendation_id", sa.Integer(), nullable=True),
            sa.Column("thesis_id", sa.Integer(), nullable=True),
            sa.Column("snapshot_id", sa.Integer(), nullable=True),
            sa.Column("role", sa.String(length=100), nullable=False),
            sa.Column("exchange", sa.String(length=20), nullable=True),
            sa.Column("symbol", sa.String(length=50), nullable=True),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("public_summary", sa.Text(), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("blocker_reason", sa.Text(), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column("prompt", sa.Text(), nullable=True),
            sa.Column("raw_model_json", sa.JSON(), nullable=True),
            sa.Column("validation_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["recommendation_id"], ["agent_recommendations.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
            sa.ForeignKeyConstraint(["snapshot_id"], ["research_snapshots.id"]),
            sa.ForeignKeyConstraint(["thesis_id"], ["agent_research_theses.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        for index_name, column_name in (
            ("ix_agent_trace_events_id", "id"),
            ("ix_agent_trace_events_user_id", "user_id"),
            ("ix_agent_trace_events_run_id", "run_id"),
            ("ix_agent_trace_events_recommendation_id", "recommendation_id"),
            ("ix_agent_trace_events_thesis_id", "thesis_id"),
            ("ix_agent_trace_events_snapshot_id", "snapshot_id"),
            ("ix_agent_trace_events_exchange", "exchange"),
            ("ix_agent_trace_events_symbol", "symbol"),
            ("ix_agent_trace_events_event_type", "event_type"),
            ("ix_agent_trace_events_status", "status"),
            ("ix_agent_trace_events_created_at", "created_at"),
        ):
            _create_index(index_name, "agent_trace_events", [column_name])

    if bind.dialect.name != "sqlite" and not _fk_exists(
        "agent_guardrail_profiles",
        "fk_agent_guardrail_profiles_ai_paper_account_id_paper_accounts",
    ):
        op.create_foreign_key(
            "fk_agent_guardrail_profiles_ai_paper_account_id_paper_accounts",
            "agent_guardrail_profiles",
            "paper_accounts",
            ["ai_paper_account_id"],
            ["id"],
        )


def downgrade() -> None:
    if _table_exists("agent_trace_events"):
        for index_name in (
            "ix_agent_trace_events_created_at",
            "ix_agent_trace_events_status",
            "ix_agent_trace_events_event_type",
            "ix_agent_trace_events_symbol",
            "ix_agent_trace_events_exchange",
            "ix_agent_trace_events_snapshot_id",
            "ix_agent_trace_events_thesis_id",
            "ix_agent_trace_events_recommendation_id",
            "ix_agent_trace_events_run_id",
            "ix_agent_trace_events_user_id",
            "ix_agent_trace_events_id",
        ):
            if _index_exists("agent_trace_events", index_name):
                op.drop_index(index_name, table_name="agent_trace_events")
        op.drop_table("agent_trace_events")

    if _table_exists("exchange_markets"):
        for index_name in (
            "ix_exchange_markets_last_seen_at",
            "ix_exchange_markets_is_analyzable",
            "ix_exchange_markets_active",
            "ix_exchange_markets_spot",
            "ix_exchange_markets_quote",
            "ix_exchange_markets_base",
            "ix_exchange_markets_db_symbol",
            "ix_exchange_markets_ccxt_symbol",
            "ix_exchange_markets_exchange",
            "ix_exchange_markets_id",
        ):
            if _index_exists("exchange_markets", index_name):
                op.drop_index(index_name, table_name="exchange_markets")
        op.drop_table("exchange_markets")

    if _column_exists("agent_guardrail_profiles", "trade_cadence_mode"):
        op.drop_column("agent_guardrail_profiles", "trade_cadence_mode")
