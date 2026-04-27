"""Add Crew model routing and model invocation audit.

Revision ID: 20260427_0006
Revises: 20260427_0005
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260427_0006"
down_revision = "20260427_0005"
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


def _create_index(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _add_column(table_name: str, column: sa.Column) -> None:
    if not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    for column_name in (
        "default_llm_model",
        "research_llm_model",
        "thesis_llm_model",
        "risk_llm_model",
        "trade_llm_model",
    ):
        _add_column("agent_guardrail_profiles", sa.Column(column_name, sa.String(length=255), nullable=True))

    for table_name in ("agent_recommendations", "agent_research_theses", "agent_trace_events"):
        _add_column(table_name, sa.Column("model_role", sa.String(length=40), nullable=True))
        _add_column(table_name, sa.Column("llm_model", sa.String(length=255), nullable=True))

    _add_column("agent_recommendations", sa.Column("trade_decision_model", sa.String(length=255), nullable=True))
    _add_column("agent_recommendations", sa.Column("trade_decision_status", sa.String(length=40), nullable=True))

    if not _table_exists("agent_model_invocations"):
        op.create_table(
            "agent_model_invocations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("recommendation_id", sa.Integer(), nullable=True),
            sa.Column("thesis_id", sa.Integer(), nullable=True),
            sa.Column("snapshot_id", sa.Integer(), nullable=True),
            sa.Column("paper_order_id", sa.Integer(), nullable=True),
            sa.Column("role", sa.String(length=100), nullable=False),
            sa.Column("action_type", sa.String(length=80), nullable=False),
            sa.Column("llm_provider", sa.String(length=40), nullable=False),
            sa.Column("llm_base_url", sa.String(length=255), nullable=True),
            sa.Column("llm_model", sa.String(length=255), nullable=False),
            sa.Column("exchange", sa.String(length=20), nullable=True),
            sa.Column("symbol", sa.String(length=50), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("timeout_seconds", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("validation_error", sa.Text(), nullable=True),
            sa.Column("response_summary", sa.Text(), nullable=True),
            sa.Column("raw_model_json", sa.JSON(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["paper_order_id"], ["paper_orders.id"]),
            sa.ForeignKeyConstraint(["recommendation_id"], ["agent_recommendations.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
            sa.ForeignKeyConstraint(["snapshot_id"], ["research_snapshots.id"]),
            sa.ForeignKeyConstraint(["thesis_id"], ["agent_research_theses.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )

    for index_name, column_name in (
        ("ix_agent_model_invocations_id", "id"),
        ("ix_agent_model_invocations_user_id", "user_id"),
        ("ix_agent_model_invocations_run_id", "run_id"),
        ("ix_agent_model_invocations_recommendation_id", "recommendation_id"),
        ("ix_agent_model_invocations_thesis_id", "thesis_id"),
        ("ix_agent_model_invocations_snapshot_id", "snapshot_id"),
        ("ix_agent_model_invocations_paper_order_id", "paper_order_id"),
        ("ix_agent_model_invocations_role", "role"),
        ("ix_agent_model_invocations_action_type", "action_type"),
        ("ix_agent_model_invocations_llm_model", "llm_model"),
        ("ix_agent_model_invocations_exchange", "exchange"),
        ("ix_agent_model_invocations_symbol", "symbol"),
        ("ix_agent_model_invocations_status", "status"),
        ("ix_agent_model_invocations_started_at", "started_at"),
        ("ix_agent_model_invocations_completed_at", "completed_at"),
        ("ix_agent_model_invocations_created_at", "created_at"),
    ):
        _create_index(index_name, "agent_model_invocations", [column_name])


def downgrade() -> None:
    if _table_exists("agent_model_invocations"):
        for index_name in (
            "ix_agent_model_invocations_created_at",
            "ix_agent_model_invocations_completed_at",
            "ix_agent_model_invocations_started_at",
            "ix_agent_model_invocations_status",
            "ix_agent_model_invocations_symbol",
            "ix_agent_model_invocations_exchange",
            "ix_agent_model_invocations_llm_model",
            "ix_agent_model_invocations_action_type",
            "ix_agent_model_invocations_role",
            "ix_agent_model_invocations_paper_order_id",
            "ix_agent_model_invocations_snapshot_id",
            "ix_agent_model_invocations_thesis_id",
            "ix_agent_model_invocations_recommendation_id",
            "ix_agent_model_invocations_run_id",
            "ix_agent_model_invocations_user_id",
            "ix_agent_model_invocations_id",
        ):
            if _index_exists("agent_model_invocations", index_name):
                op.drop_index(index_name, table_name="agent_model_invocations")
        op.drop_table("agent_model_invocations")

    for column_name in ("trade_decision_status", "trade_decision_model"):
        if _column_exists("agent_recommendations", column_name):
            op.drop_column("agent_recommendations", column_name)

    for table_name in ("agent_trace_events", "agent_research_theses", "agent_recommendations"):
        for column_name in ("llm_model", "model_role"):
            if _column_exists(table_name, column_name):
                op.drop_column(table_name, column_name)

    for column_name in (
        "trade_llm_model",
        "risk_llm_model",
        "thesis_llm_model",
        "research_llm_model",
        "default_llm_model",
    ):
        if _column_exists("agent_guardrail_profiles", column_name):
            op.drop_column("agent_guardrail_profiles", column_name)
