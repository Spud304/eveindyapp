"""add adjusted_price to cached_market_data

Revision ID: 504a1768cdd1
Revises: 
Create Date: 2026-03-04 16:03:12.103003

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '504a1768cdd1'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cached_market_data', schema=None) as batch_op:
        batch_op.add_column(sa.Column('adjusted_price', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('cached_market_data', schema=None) as batch_op:
        batch_op.drop_column('adjusted_price')
