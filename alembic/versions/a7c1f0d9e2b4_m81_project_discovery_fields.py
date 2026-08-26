"""M8.1 project discovery fields

Revision ID: a7c1f0d9e2b4
Revises: bd4354d33248
Create Date: 2026-08-26 03:30:00.000000

Adds workstation-discovery truth fields to the projects table:
discovery_source, discovery_evidence_json, ignored, last_discovered_at.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c1f0d9e2b4'
down_revision: Union[str, None] = 'bd4354d33248'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_discovered_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('ignored', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('discovery_source', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('discovery_evidence_json', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.create_index('ix_projects_ignored', ['ignored'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_index('ix_projects_ignored')
        batch_op.drop_column('discovery_evidence_json')
        batch_op.drop_column('discovery_source')
        batch_op.drop_column('ignored')
        batch_op.drop_column('last_discovered_at')
