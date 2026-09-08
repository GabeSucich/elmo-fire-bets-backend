"""feedback status

Revision ID: 1261d816f03b
Revises: 51247c0ad3b9
Create Date: 2026-09-07 20:28:44.912270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1261d816f03b'
down_revision: Union[str, Sequence[str], None] = '51247c0ad3b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace the resolved flag with a three-way status.

    A boolean could only say dealt-with or not. Retiring — considered and declined — is a
    third answer, and the one worth keeping a record of, so the same suggestion does not
    come back round every season with nobody remembering it was already refused.
    """
    status = sa.Enum("OPEN", "RESOLVED", "RETIRED", name="feedbackstatus")
    status.create(op.get_bind(), checkfirst=True)

    op.add_column("feedback", sa.Column("status", status, nullable=True))
    # Everything already marked addressed was resolved; there was no way to retire one.
    # Postgres will not coerce a bare string literal into the enum here, hence the cast.
    op.execute(
        "UPDATE feedback SET status = "
        "(CASE WHEN addressed THEN 'RESOLVED' ELSE 'OPEN' END)::feedbackstatus"
    )
    op.alter_column("feedback", "status", nullable=False, server_default="OPEN")
    op.drop_column("feedback", "addressed")


def downgrade() -> None:
    op.add_column("feedback", sa.Column("addressed", sa.Boolean(), nullable=True))
    # Retired collapses back into addressed: the old shape cannot tell the two apart.
    op.execute("UPDATE feedback SET addressed = (status <> 'OPEN'::feedbackstatus)")
    op.alter_column("feedback", "addressed", nullable=False, server_default="false")
    op.drop_column("feedback", "status")
    sa.Enum(name="feedbackstatus").drop(op.get_bind(), checkfirst=True)
