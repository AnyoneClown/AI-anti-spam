from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from bot.core.config import settings

if TYPE_CHECKING:
    from aiogram import Bot


async def notify_admin(bot: Bot | None, text: str) -> None:
    """Sends a notification message to the admin."""
    if not bot:
        logger.warning("Bot instance not available, cannot send admin notification.")
        return

    admin_id = settings.ADMIN_CHAT_ID
    if not admin_id:
        logger.warning("ADMIN_USER_ID not set in config, cannot send notification.")
        return

    try:
        await bot.send_message(
            chat_id=admin_id,
            text=text,
        )
    except Exception as e:
        logger.error(f"Failed to send notification to admin {admin_id}: {e}")