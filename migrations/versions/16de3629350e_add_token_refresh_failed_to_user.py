"""add token_refresh_failed to user

Revision ID: 16de3629350e
Revises: abbdfb594ac1
Create Date: 2026-03-09 23:59:17.390927

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '16de3629350e'
down_revision = 'abbdfb594ac1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('token_refresh_failed', sa.Boolean(), server_default='0', nullable=False))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('token_refresh_failed')
