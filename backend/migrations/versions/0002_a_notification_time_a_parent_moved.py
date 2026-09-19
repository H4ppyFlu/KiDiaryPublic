"""The first Diary day a Parent's notification time counts on.

Nullable, and null for the two seeded rows: the time they were seeded with has counted
since the first evening and there is no day to name. It is filled in from the moment a
Parent moves their own time, which is the only thing that can make "when" and "from
when" two different questions.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parents", sa.Column("notification_time_from", sa.Date, nullable=True))


def downgrade() -> None:
    op.drop_column("parents", "notification_time_from")
