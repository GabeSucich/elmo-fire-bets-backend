"""add team_played to season_pick_weeks

Revision ID: c4a1e77b2f30
Revises: 9b52c6f801e7
Create Date: 2026-09-10

`played` conflates two different weeks: one the player missed while the team played, and
one where there was no game at all. Both recorded played=False, so season progress counted
a bye and an injury the same way and left an injured player with phantom games in hand.

Nullable with no backfill on purpose. False would claim every existing row was a bye and
True would claim none of them were; null says "not known", which is what is true of a row
written before the sync began fetching schedules. The next sync fills them in.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4a1e77b2f30'
down_revision: Union[str, Sequence[str], None] = '9b52c6f801e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'season_pick_weeks',
        sa.Column('team_played', sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('season_pick_weeks', 'team_played')
