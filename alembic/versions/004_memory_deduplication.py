"""Add memory_deduplication_decisions and memory_reinforcements tables.

Revision ID: 004_memory_deduplication
Revises: 003_memory_admissions
Create Date: 2026-08-21 02:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_memory_deduplication"
down_revision: Union[str, None] = "003_memory_admissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_deduplication_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("admission_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_content", sa.Text(), nullable=False),
        sa.Column("candidate_memory_type", sa.String(length=50), nullable=False),
        sa.Column("matched_memory_id", sa.String(length=36), nullable=True),
        sa.Column("relationship", sa.String(length=32), nullable=False),
        sa.Column("relationship_confidence", sa.Float(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("created_memory_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["admission_id"], ["memory_admissions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["matched_memory_id"], ["memories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_memory_id"], ["memories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_dedup_decisions_event_id",
        "memory_deduplication_decisions",
        ["event_id"],
    )
    op.create_index(
        "ix_memory_dedup_decisions_admission_id",
        "memory_deduplication_decisions",
        ["admission_id"],
    )
    op.create_index(
        "ix_memory_dedup_decisions_created_at",
        "memory_deduplication_decisions",
        ["created_at"],
    )

    op.create_table(
        "memory_reinforcements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("source_event_id", sa.String(length=36), nullable=False),
        sa.Column("admission_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_content", sa.Text(), nullable=False),
        sa.Column("relationship_confidence", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["admission_id"], ["memory_admissions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_reinforcements_memory_id",
        "memory_reinforcements",
        ["memory_id"],
    )
    op.create_index(
        "ix_memory_reinforcements_source_event_id",
        "memory_reinforcements",
        ["source_event_id"],
    )
    op.create_index(
        "ix_memory_reinforcements_created_at",
        "memory_reinforcements",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_reinforcements_created_at", table_name="memory_reinforcements")
    op.drop_index(
        "ix_memory_reinforcements_source_event_id", table_name="memory_reinforcements"
    )
    op.drop_index("ix_memory_reinforcements_memory_id", table_name="memory_reinforcements")
    op.drop_table("memory_reinforcements")

    op.drop_index(
        "ix_memory_dedup_decisions_created_at",
        table_name="memory_deduplication_decisions",
    )
    op.drop_index(
        "ix_memory_dedup_decisions_admission_id",
        table_name="memory_deduplication_decisions",
    )
    op.drop_index(
        "ix_memory_dedup_decisions_event_id",
        table_name="memory_deduplication_decisions",
    )
    op.drop_table("memory_deduplication_decisions")
