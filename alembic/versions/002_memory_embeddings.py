"""Add memory_embeddings table for semantic retrieval.

Revision ID: 002_memory_embeddings
Revises: 001_initial
Create Date: 2026-08-21 00:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_memory_embeddings"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_embeddings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id", name="uq_memory_embeddings_memory_id"),
    )
    op.create_index(
        "ix_memory_embeddings_memory_id",
        "memory_embeddings",
        ["memory_id"],
    )
    op.create_index(
        "ix_memory_embeddings_provider_model",
        "memory_embeddings",
        ["provider", "model_name", "dimension"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_embeddings_provider_model", table_name="memory_embeddings")
    op.drop_index("ix_memory_embeddings_memory_id", table_name="memory_embeddings")
    op.drop_table("memory_embeddings")
