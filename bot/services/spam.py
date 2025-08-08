from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytz
from aiogram.types import Message
from google import genai
from loguru import logger

from bot.core.config import settings
from bot.services.users import ban_user, get_user_details
from bot.utils.notify import notify_admin

if TYPE_CHECKING:
    from aiogram.types import User
    from sqlalchemy.ext.asyncio import AsyncSession

PROMPT_TEMPLATE = """
You are a spam detection system that differentiates between legitimate messages and spam.

SPAM characteristics: unsolicited mass messaging, deceptive offers, misleading claims, requests for money without proper context, political content or discussions

NOT SPAM characteristics: personal messages, legitimate business inquiries, normal conversation, inquiries about products when context suggests prior communication, programming questions, code discussions, technical advice, requests for programming help, technology discussions

Note: Technical, programming, or code-related messages are NOT spam unless they contain unsolicited advertising or scams.
Note: Offensive, rude, or obscene messages are NOT spam unless they contain advertising, scams, or political content.

Examples:
"Click here to claim your $1000 prize now!!!" - SPAM
"Would you be interested in our new product line?" - NOT SPAM (legitimate business communication)
"Can I sell you something?" - NOT SPAM (simply offering to sell is not automatically spam)
"Well, I see he gave out the credentials" - NOT SPAM (Looks like spam or a phishing attempt, but that's not spam and it's not promoting anything)
"Selling cryptocurrency courses, DM me" - SPAM (It's out of context, but it's promoting paid courses of their company. In most cases it's SCAM.)
"Do you want to earn money online in your free time? Everything is legal and remote. Message me in DM — I'll tell you everything." - SPAM
"Inviting you to the team: income from $100 per day, suitable even without experience, I teach everything for free, you only need a phone or PC." - SPAM
"Suitable even for people 60+, the direction is legal, without risks, earnings from $400 per week — message: NATALIA." - SPAM
"I got access to your wallet" - NOT SPAM (You can't understand latest logic because context of this message is too small.)

Rules:
- If text is extremely short or looks like random characters with no offer/ask (e.g., 1–2 chars or keyboard mash), classify as NOT spam with low confidence.
- If in doubt, classify as NOT spam.
- If the message contains political content or discussions, set "isPolitic": true.

Respond ONLY with a single JSON object (no markdown fences, no prose):
{{
    "isSpam": true/false,
    "isPolitic": true/false,
    "confidence": 0.0-1.0,
    "reason": "brief explanation"
}}

Text:
"{text}"
"""

client = genai.Client(api_key=settings.GEMINI_API_KEY)


def detect_spam(text: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(text=text)
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                properties={
                    "isSpam": genai.types.Schema(type=genai.types.Type.BOOLEAN),
                    "isPolitic": genai.types.Schema(type=genai.types.Type.BOOLEAN),
                    "confidence": genai.types.Schema(type=genai.types.Type.NUMBER),
                    "reason": genai.types.Schema(type=genai.types.Type.STRING),
                },
                required=["isSpam", "isPolitic", "confidence", "reason"],
            ),
            temperature=0,
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
        ),
    )
    try:
        return json.loads(response.text)
    except Exception:
        return {
            "isSpam": None,
            "isPolitic": None,
            "confidence": 0.0,
            "reason": "Failed to parse Gemini response",
        }


async def _delete_message_safe(bot, message: Message) -> None:
    try:
        if bot:
            await bot.delete_message(
                chat_id=message.chat.id, message_id=message.message_id
            )
    except Exception as e:
        logger.warning(
            f"failed to delete message | chat_id: {message.chat.id} | msg_id: {message.message_id} | err: {e}"
        )


async def _ban_if_group_safe(
    bot, session: AsyncSession, message: Message, user_id: int
) -> None:
    try:
        if bot and message.chat.type in ("group", "supergroup"):
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=user_id)
            await ban_user(session, user_id)
    except Exception as e:
        logger.warning(
            f"failed to ban user | chat_id: {message.chat.id} | user_id: {user_id} | err: {e}"
        )


async def _notify_politic_safe(bot, message: Message, username: str) -> None:
    notify_text = f"Message from {username} is deleted: reason - politic is not allowed except Friday"
    try:
        if bot:
            await bot.send_message(chat_id=message.chat.id, text=notify_text)
    except Exception as e:
        logger.warning(
            f"failed to notify chat about political message | chat_id: {message.chat.id} | err: {e}"
        )


async def handle_politics(
    bot, message: Message, message_info: dict, username: str
) -> bool:
    """Handles political messages. Returns True if handled."""
    reason = message_info.get("reason")
    kyiv_time = datetime.now(pytz.timezone("Europe/Kyiv"))

    if message_info.get("isPolitic") and kyiv_time.weekday() != 4:  # 4 is Friday
        await _delete_message_safe(bot, message)
        await _notify_politic_safe(bot, message, username)

        log_text = f"Politics Action (Deleted)\nUser: {username} ({message.from_user.id})\nChat: {message.chat.id}\nReason: {reason}\nMessage: {message.text}"
        logger.info(log_text.replace("\n", " | "))
        return True
    return False


async def _is_user_exempt_from_spam(session: AsyncSession, user_id: int) -> bool:
    """Checks if a user is exempt from spam moderation (admin or old account)."""
    user_details = await get_user_details(session, user_id)
    if not user_details:
        return False

    if user_details.is_admin:
        return True

    account_age = datetime.now(pytz.utc) - user_details.created_at.replace(
        tzinfo=pytz.utc
    )
    if account_age > timedelta(days=5):
        return True

    return False


async def handle_spam(
    bot,
    session: AsyncSession,
    message: Message,
    message_info: dict,
    user: "User",
    username: str,
) -> bool:
    """Handles spam messages. Returns True if handled."""
    if not message_info.get("isSpam"):
        return False

    is_exempt = await _is_user_exempt_from_spam(session, user.id)
    if not is_exempt:
        reason = message_info.get("reason")
        await _delete_message_safe(bot, message)
        await _ban_if_group_safe(bot, session, message, user.id)
        log_text = f"Spam Action (Banned)\nUser: {username} ({user.id})\nChat: {message.chat.id}\nReason: {reason}\nMessage: {message.text}"
        logger.info(log_text.replace("\n", " | "))
        await notify_admin(bot, log_text)

    return True


async def process_moderation(
    bot, session: AsyncSession, message: Message, message_info: dict
) -> bool:
    """
    Returns True if the message was handled (deleted/acted on) and should stop propagation.
    """
    if not message_info or not message.from_user:
        return False

    user = message.from_user
    username = f"@{user.username}" if user.username else f"user {user.id}"

    if await handle_politics(bot, message, message_info, username):
        return True

    if await handle_spam(bot, session, message, message_info, user, username):
        return True

    return False
