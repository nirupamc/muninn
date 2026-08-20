"""Add memory_temporal_decisions audit table.

Revision ID: 005_memory_temporal
Revises: 004_memory_deduplication
Create Date: 2026-08-21 03:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_memory_temporal"
down_revision: Union[str, None] = "004_memory_deduplication"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_temporal_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("admission_id", sa.String(length=36), nullable=True),
        sa.Column("dedup_decision_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_content", sa.Text(), nullable=False),
        sa.Column("candidate_memory_type", sa.String(length=50), nullable=False),
        sa.Column("matched_memory_id", sa.String(length=36), nullable=True),
        sa.Column("created_memory_id", sa.String(length=36), nullable=True),
        sa.Column("relationship", sa.String(length=32), nullable=False),
        sa.Column("relationship_confidence", sa.Float(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_old_status", sa.String(length=32), nullable=True),
        sa.Column("old_valid_until_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("old_valid_until_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("new_valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["admission_id"], ["memory_admissions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["dedup_decision_id"],
            ["memory_deduplication_decisions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["matched_memory_id"], ["memories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_memory_id"], ["memories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_temporal_decisions_event_id",
        "memory_temporal_decisions",
        ["event_id"],
    )
    op.create_index(
        "ix_memory_temporal_decisions_admission_id",
        "memory_temporal_decisions",
        ["admission_id"],
    )
    op.create_index(
        "ix_memory_temporal_decisions_matched_memory_id",
        "memory_temporal_decisions",
        ["matched_memory_id"],
    )
    op.create_index(
        "ix_memory_temporal_decisions_created_at",
        "memory_temporal_decisions",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_temporal_decisions_created_at",
        table_name="memory_temporal_decisions",
    )
    op.drop_index(
        "ix_memory_temporal_decisions_matched_memory_id",
        table_name="memory_temporal_decisions",
    )
    op.drop_index(
        "ix_memory_temporal_decisions_admission_id",
        table_name="memory_temporal_decisions",
    )
    op.drop_index(
        "ix_memory_temporal_decisions_event_id",
        table_name="memory_temporal_decisions",
    )
    op.drop_table("memory_temporal_decisions")
