"""add WNF slate type

Revision ID: 4e069622d8b9
Revises: 3090a68e02d4
Create Date: 2026-09-05 08:53:50.838077

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "4e069622d8b9"
down_revision: Union[str, Sequence[str], None] = "3090a68e02d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUM_NAME = "slatetype"
NEW_VALUE = "WNF"

# The labels as they stood before this revision, in order, for the downgrade.
PREVIOUS_VALUES = [
    "TNF", "FNF", "MORNING_SLATE", "AFTERNOON_SLATE", "TD", "SNF", "MNF",
    "INTERNATIONAL_GAME", "SATURDAY", "XMAS", "WILDCARD", "DIVISIONAL", "CONFERENCE",
]


def upgrade() -> None:
    # SQLAlchemy persists enum member NAMES, so the stored label is "WNF".
    # Placed after FNF to keep the database ordering aligned with the Python enum.
    # Postgres 12+ allows ADD VALUE inside a transaction as long as the new value
    # is not used in that same transaction, which is why no autocommit block is needed.
    op.execute(f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS '{NEW_VALUE}' AFTER 'FNF'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum, so the type is rebuilt without it.
    # This deliberately fails if any parlay still uses the value rather than
    # silently discarding those rows.
    labels = ", ".join(f"'{v}'" for v in PREVIOUS_VALUES)
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO {ENUM_NAME}_old")
    op.execute(f"CREATE TYPE {ENUM_NAME} AS ENUM ({labels})")
    op.execute(
        f"ALTER TABLE parlays ALTER COLUMN slate_type "
        f"TYPE {ENUM_NAME} USING slate_type::text::{ENUM_NAME}"
    )
    op.execute(f"DROP TYPE {ENUM_NAME}_old")
