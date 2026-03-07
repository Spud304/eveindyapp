"""add user_config table

Revision ID: e651cd9d26dd
Revises: 504a1768cdd1
Create Date: 2026-03-04 18:12:29.032774

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e651cd9d26dd"
down_revision = "504a1768cdd1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_config",
        sa.Column("character_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("character_id"),
    )


def downgrade():
    op.drop_table("user_config")
