"""Add agent run snapshots and prediction evidence.

Revision ID: 20260426_0003
Revises: 20260426_0002
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260426_0003"
down_revision = "20260426_0002"
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


def upgrade() -> None:
    if not _table_exists("agent_runs"):
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("mode", sa.String(length=40), nullable=False),
            sa.Column("llm_provider", sa.String(length=40), nullable=False),
            sa.Column("llm_base_url", sa.String(length=255), nullable=True),
            sa.Column("llm_model", sa.String(length=120), nullable=True),
            sa.Column("max_symbols", sa.Integer(), nullable=True),
            sa.Column("requested_symbols", sa.JSON(), nullable=True),
            sa.Column("selected_symbols", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("summary", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        op.create_index("ix_agent_runs_id", "agent_runs", ["id"])
        op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
        op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    if not _table_exists("research_snapshots"):
        op.create_table(
            "research_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("exchange", sa.String(length=20), nullable=False),
            sa.Column("symbol", sa.String(length=50), nullable=False),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("source_data_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("row_count", sa.Integer(), nullable=True),
            sa.Column("data_status", sa.JSON(), nullable=True),
            sa.Column("signal", sa.JSON(), nullable=True),
            sa.Column("snapshot", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        op.create_index("ix_research_snapshots_id", "research_snapshots", ["id"])
        op.create_index("ix_research_snapshots_user_id", "research_snapshots", ["user_id"])
        op.create_index("ix_research_snapshots_run_id", "research_snapshots", ["run_id"])
        op.create_index("ix_research_snapshots_exchange", "research_snapshots", ["exchange"])
        op.create_index("ix_research_snapshots_symbol", "research_snapshots", ["symbol"])

    if not _table_exists("agent_predictions"):
        op.create_table(
            "agent_predictions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), nullable=False),
            sa.Column("exchange", sa.String(length=20), nullable=False),
            sa.Column("symbol", sa.String(length=50), nullable=False),
            sa.Column("horizon_minutes", sa.Integer(), nullable=True),
            sa.Column("predicted_path", sa.JSON(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
            sa.ForeignKeyConstraint(["snapshot_id"], ["research_snapshots.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        op.create_index("ix_agent_predictions_id", "agent_predictions", ["id"])
        op.create_index("ix_agent_predictions_user_id", "agent_predictions", ["user_id"])
        op.create_index("ix_agent_predictions_run_id", "agent_predictions", ["run_id"])
        op.create_index("ix_agent_predictions_snapshot_id", "agent_predictions", ["snapshot_id"])
        op.create_index("ix_agent_predictions_exchange", "agent_predictions", ["exchange"])
        op.create_index("ix_agent_predictions_symbol", "agent_predictions", ["symbol"])

    new_columns = (
        ("run_id", sa.Column("run_id", sa.Integer(), nullable=True)),
        ("snapshot_id", sa.Column("snapshot_id", sa.Integer(), nullable=True)),
        ("prediction_id", sa.Column("prediction_id", sa.Integer(), nullable=True)),
        ("evidence_json", sa.Column("evidence_json", sa.JSON(), nullable=True)),
        ("backtest_summary", sa.Column("backtest_summary", sa.JSON(), nullable=True)),
        ("execution_decision", sa.Column("execution_decision", sa.Text(), nullable=True)),
    )
    for column_name, column in new_columns:
        if not _column_exists("agent_recommendations", column_name):
            op.add_column("agent_recommendations", column)

    for index_name, column_name in (
        ("ix_agent_recommendations_run_id", "run_id"),
        ("ix_agent_recommendations_snapshot_id", "snapshot_id"),
        ("ix_agent_recommendations_prediction_id", "prediction_id"),
    ):
        if not _index_exists("agent_recommendations", index_name):
            op.create_index(index_name, "agent_recommendations", [column_name])

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect != "sqlite":
        constraints = (
            ("fk_agent_recommendations_run_id_agent_runs", "run_id", "agent_runs"),
            ("fk_agent_recommendations_snapshot_id_research_snapshots", "snapshot_id", "research_snapshots"),
            ("fk_agent_recommendations_prediction_id_agent_predictions", "prediction_id", "agent_predictions"),
        )
        for name, column_name, ref_table in constraints:
            op.create_foreign_key(name, "agent_recommendations", ref_table, [column_name], ["id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        for name in (
            "fk_agent_recommendations_prediction_id_agent_predictions",
            "fk_agent_recommendations_snapshot_id_research_snapshots",
            "fk_agent_recommendations_run_id_agent_runs",
        ):
            op.drop_constraint(name, "agent_recommendations", type_="foreignkey")

    for index_name in (
        "ix_agent_recommendations_prediction_id",
        "ix_agent_recommendations_snapshot_id",
        "ix_agent_recommendations_run_id",
    ):
        if _index_exists("agent_recommendations", index_name):
            op.drop_index(index_name, table_name="agent_recommendations")

    for column_name in (
        "execution_decision",
        "backtest_summary",
        "evidence_json",
        "prediction_id",
        "snapshot_id",
        "run_id",
    ):
        if _column_exists("agent_recommendations", column_name):
            op.drop_column("agent_recommendations", column_name)

    if _table_exists("agent_predictions"):
        for index_name in (
            "ix_agent_predictions_symbol",
            "ix_agent_predictions_exchange",
            "ix_agent_predictions_snapshot_id",
            "ix_agent_predictions_run_id",
            "ix_agent_predictions_user_id",
            "ix_agent_predictions_id",
        ):
            op.drop_index(index_name, table_name="agent_predictions")
        op.drop_table("agent_predictions")

    if _table_exists("research_snapshots"):
        for index_name in (
            "ix_research_snapshots_symbol",
            "ix_research_snapshots_exchange",
            "ix_research_snapshots_run_id",
            "ix_research_snapshots_user_id",
            "ix_research_snapshots_id",
        ):
            op.drop_index(index_name, table_name="research_snapshots")
        op.drop_table("research_snapshots")

    if _table_exists("agent_runs"):
        for index_name in ("ix_agent_runs_status", "ix_agent_runs_user_id", "ix_agent_runs_id"):
            op.drop_index(index_name, table_name="agent_runs")
        op.drop_table("agent_runs")
