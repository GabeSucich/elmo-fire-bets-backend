"""add rushing and receiving TD prop types

Revision ID: 515b5d6d8025
Revises: ab3d44bb7c94
Create Date: 2026-09-07 13:54:14.409205

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '515b5d6d8025'
down_revision: Union[str, Sequence[str], None] = 'ab3d44bb7c94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ENUM_NAME = "propbettype"
# SQLAlchemy persists enum member names, so these are the stored labels.
NEW_VALUES = ["RUSHING_TDS", "RECEIVING_TDS"]

# The labels as they stood before this revision, in declaration order, for the downgrade.
PREVIOUS_VALUES = [
    "TARGETS", "FGS", "LONGEST_RUSH", "PASS_ATTEMPTS", "RUSH_YDS", "REC_YDS",
    "RUSH_ATTEMPTS", "TACKLES_ASSISTS", "RUSH_REC_YDS", "LONGEST_RECEPTION",
    "LONGEST_TD", "PASSING_TDS", "PASSING_INTS", "PASSING_YDS", "TDS",
    "RECEPTIONS", "LONGEST_COMPLETION", "PASS_COMPLETIONS", "SACKS",
]


def upgrade() -> None:
    """Upgrade schema."""
    # Placed after TDS so the database ordering matches the Python enum. Postgres 12+
    # allows ADD VALUE inside a transaction as long as the value is not used in it.
    op.execute(f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS 'RUSHING_TDS' AFTER 'TDS'")
    op.execute(f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS 'RECEIVING_TDS' AFTER 'RUSHING_TDS'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres cannot drop an enum value, so the type is rebuilt without them. This fails
    # rather than discarding rows if any pick already uses one.
    labels = ", ".join(f"'{v}'" for v in PREVIOUS_VALUES)
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO {ENUM_NAME}_old")
    op.execute(f"CREATE TYPE {ENUM_NAME} AS ENUM ({labels})")
    for table, column in (("picks", "prop_type"), ("season_picks", "prop_type")):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE {ENUM_NAME} USING {column}::text::{ENUM_NAME}"
        )
    op.execute(f"DROP TYPE {ENUM_NAME}_old")
