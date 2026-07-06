import asyncio
import json
import random

from aiogram import Bot, F, Router
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.loader import redis_client
from bot.database.database import sessionmaker
from bot.middlewares.database import DatabaseMiddleware
from bot.services.users import ban_user
from bot.utils.notify import notify_admin

router = Router()
router.callback_query.middleware(DatabaseMiddleware())

CAPTCHA_TTL = 65
CAPTCHA_STARTED_TTL = 90


def _captcha_key(chat_id: int, user_id: int) -> str:
    return f"captcha:{chat_id}:{user_id}"


async def _remember_join_message(
    chat_id: int, user_id: int, join_message_id: int
) -> None:
    redis_key = _captcha_key(chat_id, user_id)
    raw_data = await redis_client.get(redis_key)
    if not raw_data:
        return

    data = json.loads(raw_data)
    data["join_message_id"] = join_message_id
    await redis_client.set(redis_key, json.dumps(data), ex=CAPTCHA_TTL)


async def _delete_message_safe(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def generate_captcha():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    correct_answer = a + b
    answers = {correct_answer}
    while len(answers) < 3:
        answers.add(correct_answer + random.randint(-5, 5) or 1)
    shuffled_answers = random.sample(list(answers), len(answers))
    buttons = [
        InlineKeyboardButton(
            text=str(ans), callback_data=f"captcha_{ans}_{correct_answer}"
        )
        for ans in shuffled_answers
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    question = f"Щоб продовжити, розв'яжіть приклад: {a} + {b} = ?"
    return question, keyboard, correct_answer


async def start_captcha(
    bot: Bot, chat_id: int, user, join_message_id: int | None = None
):
    if user.is_bot:
        return

    # Dedupe (avoid double trigger from message + chat_member)
    started_key = f"captcha_started:{chat_id}:{user.id}"
    if await redis_client.get(started_key):
        if join_message_id:
            await _remember_join_message(chat_id, user.id, join_message_id)
        return
    await redis_client.set(started_key, 1, ex=CAPTCHA_STARTED_TTL)

    logger.info(
        f"Captcha Action (Start) user={user.id} chat={chat_id} name='{user.full_name}'"
    )

    # Restrict (ignore errors but continue)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(),  # no rights
        )
    except Exception as e:
        logger.warning(
            f"Captcha Action (Warn) user={user.id} chat={chat_id} step=restrict error='{e}'"
        )

    question, keyboard, correct_answer = generate_captcha()
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=f"Вітаємо, {user.full_name}!\n\n{question}",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(
            f"Captcha Action (Error) user={user.id} chat={chat_id} step=send_message error='{e}'"
        )
        return

    redis_key = _captcha_key(chat_id, user.id)
    await redis_client.set(
        redis_key,
        json.dumps(
            {
                "chat_id": chat_id,
                "message_id": message.message_id,
                "correct_answer": correct_answer,
                "join_message_id": join_message_id,
            }
        ),
        ex=CAPTCHA_TTL,
    )

    asyncio.create_task(
        check_verification_timeout(bot, chat_id, user.id, message.message_id)
    )


@router.chat_member(
    F.chat.type.in_({"group", "supergroup"})
    & F.new_chat_member.status.in_(
        {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED}
    )
    & (F.old_chat_member.status != F.new_chat_member.status)
)
async def on_user_joined(event: ChatMemberUpdated, bot: Bot):
    # Log raw statuses for debugging
    logger.debug(
        f"ChatMemberUpdate received chat={event.chat.id} old={event.old_chat_member.status} new={event.new_chat_member.status} user={event.new_chat_member.user.id}"
    )
    await start_captcha(bot, event.chat.id, event.new_chat_member.user)


# Fallback: message-based (covers ordinary joins/invites)
@router.message(F.new_chat_members)
async def on_new_members_message(message: Message, bot: Bot):
    for user in message.new_chat_members:
        await start_captcha(bot, message.chat.id, user, message.message_id)


@router.chat_join_request()
async def on_join_request(req: ChatJoinRequest, bot: Bot):
    try:
        await bot.approve_chat_join_request(req.chat.id, req.from_user.id)
    except Exception as e:
        logger.error(
            f"JoinRequest approve failed chat={req.chat.id} user={req.from_user.id} error='{e}'"
        )
        return
    await start_captcha(bot, req.chat.id, req.from_user)


async def check_verification_timeout(
    bot: Bot, chat_id: int, user_id: int, message_id: int
):
    await asyncio.sleep(60)
    redis_key = _captcha_key(chat_id, user_id)
    raw_data = await redis_client.get(redis_key)
    if raw_data:
        data = json.loads(raw_data)
        logger.warning(
            f"Captcha Action (Banned) user={user_id} chat={chat_id} reason=timeout"
        )
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await _delete_message_safe(bot, chat_id, data.get("message_id", message_id))
            await _delete_message_safe(bot, chat_id, data.get("join_message_id"))
            await notify_admin(
                bot,
                f"Captcha Action (Banned)\nUser: {user_id}\nChat: {chat_id}\nReason: timeout",
            )
            async with sessionmaker() as session:
                await ban_user(session, user_id)
        except Exception as e:
            logger.error(
                f"Captcha Action (Error) user={user_id} chat={chat_id} step=timeout_ban error='{e}'"
            )
        finally:
            await redis_client.delete(redis_key)


@router.callback_query(F.data.startswith("captcha_"))
async def process_captcha_callback(
    query: CallbackQuery, bot: Bot, session: AsyncSession
):
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    redis_key = _captcha_key(chat_id, user_id)

    raw_data = await redis_client.get(redis_key)
    if not raw_data:
        await query.answer("Капча застаріла або належить не вам.", show_alert=True)
        return

    data = json.loads(raw_data)
    message_id = data["message_id"]
    join_message_id = data.get("join_message_id")
    _, selected_answer, correct_answer = query.data.split("_")

    await redis_client.delete(redis_key)
    await _delete_message_safe(bot, chat_id, message_id)

    if int(selected_answer) == int(correct_answer):
        logger.info(f"Captcha Action (Passed) user={user_id} chat={chat_id}")
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await query.answer("Перевірку пройдено!")
    else:
        logger.warning(
            f"Captcha Action (Banned) user={user_id} chat={chat_id} reason=wrong_answer"
        )
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await _delete_message_safe(bot, chat_id, join_message_id)
        await notify_admin(
            bot,
            f"Captcha Action (Banned)\nUser: {user_id}\nChat: {chat_id}\nReason: wrong_answer",
        )
        await ban_user(session, user_id)
        await query.answer("Неправильна відповідь. Вас заблоковано.", show_alert=True)
