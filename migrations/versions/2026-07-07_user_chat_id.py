"""user chat id

Revision ID: 20260707_user_chat_id
Revises: e4b7e8c165c1
Create Date: 2026-07-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260707_user_chat_id"
down_revision: Union[str, None] = "e4b7e8c165c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("chat_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "chat_id")
