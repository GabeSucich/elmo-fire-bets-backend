"""add pick lists

Revision ID: 695e90f09d8b
Revises: d8f3c21a4e60
Create Date: 2026-09-14 15:43:42.160480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '695e90f09d8b'
down_revision: Union[str, Sequence[str], None] = 'd8f3c21a4e60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Same as the season-long picks migration: only picklisttype is new, and the other two are
# already in the database from the picks table. Referencing those with create_type=False is
# what stops create_table emitting a second CREATE TYPE and dying on "already exists".
pick_list_type = postgresql.ENUM("BAN", name="picklisttype", create_type=False)
existing_prop_bet_type = postgresql.ENUM(name="propbettype", create_type=False)
existing_prop_bet_direction = postgresql.ENUM(name="propbetdirection", create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    pick_list_type.create(op.get_bind(), checkfirst=True)
    op.create_table('pick_lists',
    sa.Column('gambling_season_id', sa.Integer(), nullable=False),
    sa.Column('list_type', pick_list_type, nullable=False),
    sa.Column('display_name', sa.String(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['gambling_season_id'], ['gambling_seasons.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('gambling_season_id', 'list_type', name='uq_pick_list_season_type')
    )
    op.create_table('pick_list_items',
    sa.Column('pick_list_id', sa.Integer(), nullable=False),
    sa.Column('gambler_id', sa.Integer(), nullable=False),
    sa.Column('prop_bet_target_id', sa.Integer(), nullable=False),
    sa.Column('prop_type', existing_prop_bet_type, nullable=True),
    sa.Column('direction', existing_prop_bet_direction, nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['gambler_id'], ['gamblers.id'], ),
    sa.ForeignKeyConstraint(['pick_list_id'], ['pick_lists.id'], ),
    sa.ForeignKeyConstraint(['prop_bet_target_id'], ['prop_bet_targets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # Every read of a list goes through its entries, and the parlay badge index reads the
    # whole season's in one go — both of which hit this column and nothing else.
    op.create_index('ix_pick_list_items_pick_list_id', 'pick_list_items', ['pick_list_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_pick_list_items_pick_list_id', table_name='pick_list_items')
    op.drop_table('pick_list_items')
    op.drop_table('pick_lists')
    # Dropping a table leaves its enum type behind, which would break the next upgrade.
    pick_list_type.drop(op.get_bind(), checkfirst=True)
