"""add live progress to picks

Revision ID: d8f3c21a4e60
Revises: c4a1e77b2f30
Create Date: 2026-09-11

An open parlay could only say what was bet, never how it was going. These four columns
hold what a sync read off the live boxscore: the stat so far, ESPN's own reading of the
game, the human form of it, and when it was last asked.

All nullable with no backfill. A pick that has never been synced has no progress, which
is a different thing from a progress of zero — and the columns are deliberately separate
from `result`, which stays hand-entered because void, push and bozo are judgements no
feed can make.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd8f3c21a4e60'
down_revision: Union[str, Sequence[str], None] = 'c4a1e77b2f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('picks', sa.Column('live_value', sa.Float(), nullable=True))
    op.add_column('picks', sa.Column('live_state', sa.String(), nullable=True))
    op.add_column('picks', sa.Column('live_detail', sa.String(), nullable=True))
    op.add_column('picks', sa.Column('live_synced_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('picks', 'live_synced_at')
    op.drop_column('picks', 'live_detail')
    op.drop_column('picks', 'live_state')
    op.drop_column('picks', 'live_value')
