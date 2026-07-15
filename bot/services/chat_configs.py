from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy import select

from bot.database.models import ChatConfigModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def is_captcha_enabled(session: AsyncSession, chat_id: int) -> bool:
    query = select(ChatConfigModel.captcha_enabled).where(ChatConfigModel.chat_id == chat_id)
    result = await session.execute(query)
    enabled = result.scalar_one_or_none()

    # Chats without an explicit configuration use the safe default.
    return True if enabled is None else enabled


async def set_captcha_enabled(
    session: AsyncSession,
    chat_id: int,
    *,
    enabled: bool,
) -> None:
    config = await session.get(ChatConfigModel, chat_id)
    if config is None:
        session.add(ChatConfigModel(chat_id=chat_id, captcha_enabled=enabled))
    else:
        config.captcha_enabled = enabled

    await session.commit()
