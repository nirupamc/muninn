"""add gist and summary fields for hierarchical representation (M10)

Revision ID: c8d1a0f2e3b4
Revises: a7c1f0d9e2b4
Create Date: 2026-08-28 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d1a0f2e3b4'
down_revision: Union[str, None] = 'a7c1f0d9e2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add gist (L0) and summary (L1) columns to memories table.

    Both are nullable Text columns. Existing rows will have NULL for both,
    which is the expected backward-compatible state.
    """
    with op.batch_alter_table('memories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('gist', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('summary', sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove gist and summary columns."""
    with op.batch_alter_table('memories', schema=None) as batch_op:
        batch_op.drop_column('summary')
        batch_op.drop_column('gist')
