"""add main_character_id to user

Revision ID: f1a435c12bb6
Revises: e651cd9d26dd
Create Date: 2026-03-06 20:06:18.131339

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a435c12bb6"
down_revision = "e651cd9d26dd"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("main_character_id", sa.BigInteger(), nullable=True)
        )

    # Backfill: each existing user becomes their own main
    op.execute(
        "UPDATE user SET main_character_id = character_id WHERE main_character_id IS NULL"
    )

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column("main_character_id", nullable=False)


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("main_character_id")
