"""add per-chat captcha configuration

Revision ID: 20260715_chat_configs
Revises: 20260707_user_chat_id
Create Date: 2026-07-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260715_chat_configs"
down_revision: Union[str, None] = "20260707_user_chat_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_configs",
        sa.Column(
            "chat_id",
            sa.BigInteger(),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "captcha_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("chat_id"),
    )


def downgrade() -> None:
    op.drop_table("chat_configs")
