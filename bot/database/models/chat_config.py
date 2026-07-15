from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, true
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.models.base import Base


class ChatConfigModel(Base):
    __tablename__ = "chat_configs"

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
    )
    captcha_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
    )
