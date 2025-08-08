from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import TYPE_CHECKING
from loguru import logger
from google import genai
import pytz
from aiogram.types import Message
from bot.utils.notify import notify_admin

from bot.core.config import settings
from bot.services.users import ban_user, get_user_details

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
        model="gemini-2.0-flash-lite",
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
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except Exception as e:
        logger.warning(f"failed to delete message | chat_id: {message.chat.id} | msg_id: {message.message_id} | err: {e}")

async def _ban_if_group_safe(bot, session: AsyncSession, message: Message, user_id: int) -> None:
    try:
        print("1")
        if bot and message.chat.type in ("group", "supergroup"):
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=user_id)
            await ban_user(session, user_id)
    except Exception as e:
        logger.warning(f"failed to ban user | chat_id: {message.chat.id} | user_id: {user_id} | err: {e}")

async def _notify_politic_safe(bot, message: Message, username: str) -> None:
    notify_text = f"Message from {username} is deleted: reason - politic is not allowed except Friday"
    try:
        if bot:
            await bot.send_message(chat_id=message.chat.id, text=notify_text)
    except Exception as e:
        logger.warning(f"failed to notify chat about political message | chat_id: {message.chat.id} | err: {e}")

async def process_moderation(bot, session: AsyncSession, message: Message, message_info: dict) -> bool:
    """
    Returns True if the message was handled (deleted/acted on) and should stop propagation.
    """
    if not message_info:
        return False

    user = message.from_user
    if not user:
        return False

    username = f"@{user.username}" if user.username else f"user {user.id}"
    reason = message_info.get("reason")
    kyiv_time = datetime.now(pytz.timezone("Europe/Kyiv"))
    
    if message_info.get("isPolitic") and not kyiv_time.weekday() == 4:
        await _delete_message_safe(bot, message)
        await _notify_politic_safe(bot, message, username)

        log_text = f"Politics Action (Deleted)\nUser: {username} ({user.id})\nChat: {message.chat.id}\nReason: {reason}\nMessage: {message.text}"
        logger.info(log_text.replace("\n", " | "))
        await notify_admin(bot, log_text)
        return True

    if message_info.get("isSpam"):
        user_details = await get_user_details(session, user.id)
        is_exempt = False
        exemption_reason = ""

        if user_details:
            # Check if user is an admin
            if user_details.is_admin:
                is_exempt = True
                exemption_reason = "User is an admin"
            # Check if user account is older than 5 days
            elif (datetime.now(pytz.utc) - user_details.created_at.replace(tzinfo=pytz.utc)) > timedelta(days=5):
                is_exempt = True
                exemption_reason = "User account is older than 5 days"

        if is_exempt:
            # User is exempt from ban, just log and notify
            log_text = f"Spam Action (Deleted, Ban Exempt)\nUser: {username} ({user.id})\nChat: {message.chat.id}\nReason: {reason}\nExemption: {exemption_reason}\nMessage: {message.text}"
            logger.info(log_text.replace("\n", " | "))
            await notify_admin(bot, log_text)
        else:
            # User is not exempt, proceed with ban
            await _delete_message_safe(bot, message)
            await _ban_if_group_safe(bot, session, message, user.id)
            log_text = f"Spam Action (Banned)\nUser: {username} ({user.id})\nChat: {message.chat.id}\nReason: {reason}\nMessage: {message.text}"
            logger.info(log_text.replace("\n", " | "))
            await notify_admin(bot, log_text)
        
        return True

    if message_info.get("isPolitic") and not kyiv_time.weekday() == 4:
        await _delete_message_safe(bot, message)
        await _notify_politic_safe(bot, message, username)

        log_text = f"Politics Action (Deleted)\nUser: {username} ({user.id})\nChat: {message.chat.id}\nReason: {reason}\nMessage: {message.text}"
        logger.info(log_text.replace("\n", " | "))
        await notify_admin(bot, log_text)
        return True

    return False