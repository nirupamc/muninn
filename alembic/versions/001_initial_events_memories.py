"""Initial events and memories tables.

Revision ID: 001_initial
Revises:
Create Date: 2026-08-21 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("namespace", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("agent_id", sa.String(length=255), nullable=True),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("role", sa.Enum(
            "user", "assistant", "system", "tool", "other",
            name="event_role",
            native_enum=False,
        ), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_namespace", "events", ["namespace"])
    op.create_index("ix_events_namespace_session", "events", ["namespace", "session_id"])
    op.create_index("ix_events_created_at", "events", ["created_at"])

    op.create_table(
        "memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("namespace", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("agent_id", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.Enum(
            "fact", "preference", "project", "goal", "decision",
            "event", "relationship", "procedure", "other",
            name="memory_type",
            native_enum=False,
        ), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.Enum(
            "active", "superseded", "invalidated", "archived",
            name="memory_status",
            native_enum=False,
        ), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_event_id", sa.String(length=36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["source_event_id"], ["events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memories_namespace", "memories", ["namespace"])
    op.create_index("ix_memories_namespace_status", "memories", ["namespace", "status"])
    op.create_index("ix_memories_created_at", "memories", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_memories_created_at", table_name="memories")
    op.drop_index("ix_memories_namespace_status", table_name="memories")
    op.drop_index("ix_memories_namespace", table_name="memories")
    op.drop_table("memories")
    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_index("ix_events_namespace_session", table_name="events")
    op.drop_index("ix_events_namespace", table_name="events")
    op.drop_table("events")
