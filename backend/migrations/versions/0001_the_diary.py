"""The Diary's schema: Child, Parents, Prompt bank, Answers, Skips, Deliveries and
push subscriptions.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "children",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("birthdate", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "parents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("position", sa.SmallInteger, nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("notification_time", sa.Time, nullable=False),
        sa.CheckConstraint("position in (1, 2)", name="ck_parents_position"),
    )

    op.create_table(
        "prompts",
        sa.Column("id", sa.Integer, primary_key=True),
        # Unique, so re-running the seed re-offers a Prompt rather than copying it.
        sa.Column("text", sa.Text, nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "answers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("parents.id"), nullable=False),
        sa.Column("prompt_id", sa.Integer, sa.ForeignKey("prompts.id"), nullable=False),
        sa.Column("diary_day", sa.Date, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # A Prompt answered today is not drawn again today, so it cannot be answered twice.
        sa.UniqueConstraint("parent_id", "prompt_id", "diary_day", name="uq_answers_parent_prompt_day"),
    )
    op.create_index("ix_answers_diary_day", "answers", ["diary_day"])

    op.create_table(
        "skips",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("parents.id"), nullable=False),
        sa.Column("prompt_id", sa.Integer, sa.ForeignKey("prompts.id"), nullable=False),
        sa.Column("diary_day", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("parent_id", "prompt_id", "diary_day", name="uq_skips_parent_prompt_day"),
    )
    op.create_index("ix_skips_diary_day", "skips", ["diary_day"])

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("parents.id"), nullable=False),
        sa.Column("prompt_id", sa.Integer, sa.ForeignKey("prompts.id"), nullable=False),
        sa.Column("diary_day", sa.Date, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        # At most one notification per Parent per evening, restarts included.
        sa.UniqueConstraint("parent_id", "diary_day", name="uq_deliveries_parent_day"),
    )

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("parents.id"), nullable=False),
        sa.Column("endpoint", sa.Text, nullable=False, unique=True),
        sa.Column("p256dh_key", sa.Text, nullable=False),
        sa.Column("auth_key", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("push_subscriptions")
    op.drop_table("deliveries")
    op.drop_table("skips")
    op.drop_table("answers")
    op.drop_table("prompts")
    op.drop_table("parents")
    op.drop_table("children")
