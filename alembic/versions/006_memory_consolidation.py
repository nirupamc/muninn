"""Add memory_consolidations and memory_consolidation_sources tables.

Revision ID: 006_memory_consolidation
Revises: 005_memory_temporal
Create Date: 2026-08-21 04:00:00.000000

Consolidation is compression of related memories into a derived summary.
Source memories are NEVER deleted — they remain active and queryable.
The derived (consolidated) memory is a new row in the memories table
linked back to its sources via memory_consolidation_sources.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_memory_consolidation"
down_revision: Union[str, None] = "005_memory_temporal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Consolidation audit: one row per consolidation operation
    op.create_table(
        "memory_consolidations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("namespace", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("created_memory_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("provider_model", sa.String(length=255), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_memory_id"], ["memories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_consolidations_namespace",
        "memory_consolidations",
        ["namespace"],
    )
    op.create_index(
        "ix_memory_consolidations_created_memory_id",
        "memory_consolidations",
        ["created_memory_id"],
    )
    op.create_index(
        "ix_memory_consolidations_created_at",
        "memory_consolidations",
        ["created_at"],
    )

    # Source links: many-to-many between consolidation and source memories
    op.create_table(
        "memory_consolidation_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("consolidation_id", sa.String(length=36), nullable=False),
        sa.Column("source_memory_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["consolidation_id"],
            ["memory_consolidations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_memory_id"], ["memories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_consolidation_sources_consolidation_id",
        "memory_consolidation_sources",
        ["consolidation_id"],
    )
    op.create_index(
        "ix_memory_consolidation_sources_source_memory_id",
        "memory_consolidation_sources",
        ["source_memory_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_consolidation_sources_source_memory_id",
        table_name="memory_consolidation_sources",
    )
    op.drop_index(
        "ix_memory_consolidation_sources_consolidation_id",
        table_name="memory_consolidation_sources",
    )
    op.drop_table("memory_consolidation_sources")

    op.drop_index(
        "ix_memory_consolidations_created_at",
        table_name="memory_consolidations",
    )
    op.drop_index(
        "ix_memory_consolidations_created_memory_id",
        table_name="memory_consolidations",
    )
    op.drop_index(
        "ix_memory_consolidations_namespace",
        table_name="memory_consolidations",
    )
    op.drop_table("memory_consolidations")
