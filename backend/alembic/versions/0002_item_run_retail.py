"""item_run.retail: retail price lookup, stored apart from result

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('item_run', schema=None) as batch_op:
        batch_op.add_column(sa.Column('retail', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('item_run', schema=None) as batch_op:
        batch_op.drop_column('retail')
