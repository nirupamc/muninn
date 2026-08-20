"""Add memory_admissions audit table.

Revision ID: 003_memory_admissions
Revises: 002_memory_embeddings
Create Date: 2026-08-21 01:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_memory_admissions"
down_revision: Union[str, None] = "002_memory_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_admissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_content", sa.Text(), nullable=True),
        sa.Column("memory_type", sa.String(length=50), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("admission_score", sa.Float(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("future_utility", sa.Float(), nullable=True),
        sa.Column("stability", sa.Float(), nullable=True),
        sa.Column("specificity", sa.Float(), nullable=True),
        sa.Column("explicitness", sa.Float(), nullable=True),
        sa.Column("triviality", sa.Float(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("created_memory_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_memory_id"], ["memories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_admissions_event_id", "memory_admissions", ["event_id"])
    op.create_index("ix_memory_admissions_created_at", "memory_admissions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_memory_admissions_created_at", table_name="memory_admissions")
    op.drop_index("ix_memory_admissions_event_id", table_name="memory_admissions")
    op.drop_table("memory_admissions")
