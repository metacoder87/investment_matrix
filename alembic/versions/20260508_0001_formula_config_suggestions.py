"""Add deterministic formula config and suggestion tables.

Revision ID: 20260508_0001
Revises: 20260430_0002
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260508_0001"
down_revision = "20260430_0002"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if not _table_exists("agent_formula_configs"):
        op.create_table(
            "agent_formula_configs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("parameters_json", sa.JSON(), nullable=True),
            sa.Column("bounds_json", sa.JSON(), nullable=True),
            sa.Column("authority_mode", sa.String(length=40), nullable=False, server_default="approval_required"),
            sa.Column("created_by", sa.String(length=40), nullable=False, server_default="system"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("agent_formula_configs", "ix_agent_formula_configs_id"):
        op.create_index("ix_agent_formula_configs_id", "agent_formula_configs", ["id"])
    if not _index_exists("agent_formula_configs", "ix_agent_formula_configs_user_id"):
        op.create_index("ix_agent_formula_configs_user_id", "agent_formula_configs", ["user_id"])
    if not _index_exists("agent_formula_configs", "ix_agent_formula_configs_is_active"):
        op.create_index("ix_agent_formula_configs_is_active", "agent_formula_configs", ["is_active"])
    if not _index_exists("agent_formula_configs", "ix_agent_formula_configs_authority_mode"):
        op.create_index("ix_agent_formula_configs_authority_mode", "agent_formula_configs", ["authority_mode"])
    if not _index_exists("agent_formula_configs", "ix_agent_formula_configs_user_active"):
        op.create_index("ix_agent_formula_configs_user_active", "agent_formula_configs", ["user_id", "is_active"])

    if not _table_exists("agent_formula_suggestions"):
        op.create_table(
            "agent_formula_suggestions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("config_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
            sa.Column("source", sa.String(length=80), nullable=False, server_default="deterministic_optimizer"),
            sa.Column("proposed_parameters_json", sa.JSON(), nullable=True),
            sa.Column("deterministic_evidence_json", sa.JSON(), nullable=True),
            sa.Column("ai_notes", sa.Text(), nullable=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["config_id"], ["agent_formula_configs.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("agent_formula_suggestions", "ix_agent_formula_suggestions_id"):
        op.create_index("ix_agent_formula_suggestions_id", "agent_formula_suggestions", ["id"])
    if not _index_exists("agent_formula_suggestions", "ix_agent_formula_suggestions_user_id"):
        op.create_index("ix_agent_formula_suggestions_user_id", "agent_formula_suggestions", ["user_id"])
    if not _index_exists("agent_formula_suggestions", "ix_agent_formula_suggestions_config_id"):
        op.create_index("ix_agent_formula_suggestions_config_id", "agent_formula_suggestions", ["config_id"])
    if not _index_exists("agent_formula_suggestions", "ix_agent_formula_suggestions_status"):
        op.create_index("ix_agent_formula_suggestions_status", "agent_formula_suggestions", ["status"])
    if not _index_exists("agent_formula_suggestions", "ix_agent_formula_suggestions_user_status"):
        op.create_index("ix_agent_formula_suggestions_user_status", "agent_formula_suggestions", ["user_id", "status"])


def downgrade() -> None:
    for table_name, index_names in (
        (
            "agent_formula_suggestions",
            (
                "ix_agent_formula_suggestions_user_status",
                "ix_agent_formula_suggestions_status",
                "ix_agent_formula_suggestions_config_id",
                "ix_agent_formula_suggestions_user_id",
                "ix_agent_formula_suggestions_id",
            ),
        ),
        (
            "agent_formula_configs",
            (
                "ix_agent_formula_configs_user_active",
                "ix_agent_formula_configs_authority_mode",
                "ix_agent_formula_configs_is_active",
                "ix_agent_formula_configs_user_id",
                "ix_agent_formula_configs_id",
            ),
        ),
    ):
        for index_name in index_names:
            if _index_exists(table_name, index_name):
                op.drop_index(index_name, table_name=table_name)
        if _table_exists(table_name):
            op.drop_table(table_name)
