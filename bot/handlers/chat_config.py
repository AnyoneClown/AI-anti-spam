from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from loguru import logger

from bot.middlewares.database import DatabaseMiddleware
from bot.services.chat_configs import is_captcha_enabled, set_captcha_enabled

if TYPE_CHECKING:
    from aiogram.types import Message
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router()
router.message.middleware(DatabaseMiddleware())

GROUP_CHAT_TYPES = {"group", "supergroup"}
ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


async def _is_group_admin(message: Message, bot: Bot) -> bool:
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        # Telegram uses sender_chat for administrators posting anonymously.
        return True
    if not message.from_user:
        return False

    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    except TelegramAPIError as error:
        logger.warning(
            f"Captcha Config (Admin Check Failed) chat={message.chat.id} user={message.from_user.id} error='{error}'"
        )
        return False

    return member.status in ADMIN_STATUSES


@router.message(Command("captcha"), F.chat.type.in_(GROUP_CHAT_TYPES))
async def configure_captcha(
    message: Message,
    bot: Bot,
    command: CommandObject,
    session: AsyncSession,
) -> None:
    if not await _is_group_admin(message, bot):
        await message.answer("Лише адміністратор групи може змінювати налаштування капчі.")
        return

    action = (command.args or "status").strip().lower()
    if action == "status":
        enabled = await is_captcha_enabled(session, message.chat.id)
        status = "увімкнена" if enabled else "вимкнена"
        await message.answer(f"Капча зараз {status}.")
        return

    if action not in {"on", "off"}:
        await message.answer(
            "Використання: /captcha on, /captcha off або /captcha status"  # noqa: RUF001
        )
        return

    enabled = action == "on"
    await set_captcha_enabled(session, message.chat.id, enabled=enabled)
    logger.info(
        f"Captcha Config (Changed) chat={message.chat.id} "
        f"enabled={enabled} user={message.from_user.id if message.from_user else 'anonymous'}"
    )
    result = "увімкнено" if enabled else "вимкнено"
    await message.answer(f"Капчу {result} для цієї групи.")
