from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytz
from aiogram import BaseMiddleware
from aiogram.types import Message
from loguru import logger

from bot.services.spam import detect_spam, process_moderation
from bot.services.users import get_user_details

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram.types import TelegramObject
    from sqlalchemy.ext.asyncio import AsyncSession


class SpamMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        session: AsyncSession = data["session"]
        message: Message = event

        if not message.from_user:
            return await handler(event, data)

        message_info = detect_spam(message.text or message.caption)
        bot = data.get("bot") or getattr(message, "bot", None)

        handled = await process_moderation(bot, session, message, message_info)

        if handled:
            return

        return await handler(event, data)
