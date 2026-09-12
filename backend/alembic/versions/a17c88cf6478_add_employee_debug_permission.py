"""add employee debug permission

Revision ID: a17c88cf6478
Revises: 59deee17c4c7
Create Date: 2026-09-12 06:58:27.454256

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a17c88cf6478'
down_revision: Union[str, None] = '59deee17c4c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("can_debug", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("employees", "can_debug", server_default=None)


def downgrade() -> None:
    op.drop_column("employees", "can_debug")
