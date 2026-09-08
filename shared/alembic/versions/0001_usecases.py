"""usecases, usecase_versions, agentcore_agents, usecase_agents

Revision ID: 0001
Revises:
Create Date: 2026-09-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns() -> list[sa.Column]:
    """Cột kế thừa từ `BaseTableModel` (mục 4 design doc) — lặp lại tường
    minh ở mỗi `create_table` vì Alembic không có khái niệm "abstract base
    table" runtime."""
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "usecases",
        *_base_columns(),
        sa.Column("usecase_key", sa.String(128), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("default_max_iterations", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("max_iterations_cap", sa.Integer(), nullable=False, server_default="30"),
    )
    op.create_unique_constraint("uq_usecases_usecase_key", "usecases", ["usecase_key"])

    op.create_table(
        "usecase_versions",
        *_base_columns(),
        sa.Column("usecase_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usecases.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
    )
    op.create_unique_constraint(
        "uq_usecase_versions_usecase_id_version_number",
        "usecase_versions",
        ["usecase_id", "version_number"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_usecase_versions_one_latest_per_usecase "
        "ON usecase_versions (usecase_id) WHERE is_latest"
    )

    op.create_table(
        "agentcore_agents",
        *_base_columns(),
        sa.Column("agent_key", sa.String(128), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("agentcore_agent_arn", sa.String(512), nullable=True),
        sa.Column("local_tool_ref", sa.String(256), nullable=True),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("secrets", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("default_timeout_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("default_retry_policy", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("agent_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_unique_constraint("uq_agentcore_agents_agent_key", "agentcore_agents", ["agent_key"])
    op.create_check_constraint(
        "exactly_one_of_arn_or_local_tool_ref",
        "agentcore_agents",
        "(agentcore_agent_arn IS NOT NULL) != (local_tool_ref IS NOT NULL)",
    )

    op.create_table(
        "usecase_agents",
        *_base_columns(),
        sa.Column(
            "usecase_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usecase_versions.id"),
            nullable=False,
        ),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agentcore_agents.id"), nullable=False),
        sa.Column("agent_name", sa.String(256), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("retry_policy", postgresql.JSONB(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_usecase_agents_usecase_version_id_agent_name",
        "usecase_agents",
        ["usecase_version_id", "agent_name"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_usecase_agents_one_orchestrator_per_version "
        "ON usecase_agents (usecase_version_id) WHERE kind = 'orchestrator'"
    )


def downgrade() -> None:
    op.drop_table("usecase_agents")
    op.drop_table("agentcore_agents")
    op.drop_table("usecase_versions")
    op.drop_table("usecases")
