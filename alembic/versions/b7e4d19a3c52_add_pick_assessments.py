"""add pick assessments

Revision ID: b7e4d19a3c52
Revises: 695e90f09d8b
Create Date: 2026-10-04

Two things a pick assessment needs. Game context on each pick — home or away, opponent,
kickoff, the market around the game — which nothing stored before, since a pick recorded
who the bet was on but never which fixture. And a table to keep the assessments in, keyed
by a hash of what the model was shown so the same input is never paid for twice.

The game columns are all nullable with no backfill here. backfill_game_context.py fills
the static ones for past picks; the market ones (spread, total, weather) ESPN stops
publishing at kickoff, so they can only be captured going forward.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b7e4d19a3c52'
down_revision: Union[str, Sequence[str], None] = '695e90f09d8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GAME_COLUMNS = [
    ('game_event_id', sa.String(length=32)),
    ('game_team', sa.String(length=8)),
    ('game_kickoff_at', sa.DateTime()),
    ('game_week', sa.Integer()),
    ('game_is_home', sa.Boolean()),
    ('game_opponent', sa.String(length=8)),
    ('game_indoor', sa.Boolean()),
    ('game_neutral_site', sa.Boolean()),
    ('game_team_score', sa.Integer()),
    ('game_opponent_score', sa.Integer()),
    ('game_team_spread', sa.Float()),
    ('game_total', sa.Float()),
    ('game_weather', sa.String()),
]


def upgrade() -> None:
    for name, type_ in GAME_COLUMNS:
        op.add_column('picks', sa.Column(name, type_, nullable=True))

    op.create_table(
        'assessments',
        sa.Column('parlay_id', sa.Integer(), nullable=False),
        sa.Column('pick_id', sa.Integer(), nullable=True),
        sa.Column('subject_hash', sa.String(length=64), nullable=False),
        sa.Column('input_hash', sa.String(length=64), nullable=False),
        sa.Column('subject_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('input_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('suggestions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('prompt_version', sa.String(length=32), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['parlay_id'], ['parlays.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pick_id'], ['picks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_assessments_parlay_id', 'assessments', ['parlay_id'])
    op.create_index(
        'uq_assessment_pick_input', 'assessments', ['parlay_id', 'pick_id', 'input_hash'],
        unique=True, postgresql_where=sa.text('pick_id IS NOT NULL'),
    )
    op.create_index(
        'uq_assessment_parlay_input', 'assessments', ['parlay_id', 'input_hash'],
        unique=True, postgresql_where=sa.text('pick_id IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_assessment_parlay_input', table_name='assessments')
    op.drop_index('uq_assessment_pick_input', table_name='assessments')
    op.drop_index('ix_assessments_parlay_id', table_name='assessments')
    op.drop_table('assessments')
    for name, _ in reversed(GAME_COLUMNS):
        op.drop_column('picks', name)
