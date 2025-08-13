import asyncio
import json
import random

from aiogram import Bot, F, Router
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.loader import redis_client
from bot.middlewares.database import DatabaseMiddleware
from bot.services.users import ban_user
from bot.utils.notify import notify_admin

router = Router()
router.message.middleware(DatabaseMiddleware())
router.callback_query.middleware(DatabaseMiddleware())
router.chat_member.middleware(DatabaseMiddleware())

CAPTCHA_TTL = 65


def _captcha_key(chat_id: int, user_id: int) -> str:
    return f"captcha:{chat_id}:{user_id}"


def generate_captcha():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    correct_answer = a + b
    answers = {correct_answer}
    while len(answers) < 3:
        answers.add(correct_answer + random.randint(-5, 5) or 1)
    shuffled_answers = random.sample(list(answers), len(answers))
    question = f"To continue, please solve this: {a} + {b} = ?"
    buttons = [
        InlineKeyboardButton(
            text=str(ans), callback_data=f"captcha_{ans}_{correct_answer}"
        )
        for ans in shuffled_answers
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    return question, keyboard, correct_answer


@router.chat_member(
    F.chat.type.in_({"group", "supergroup"})
    & (F.old_chat_member.is_member == False)
    & (F.new_chat_member.is_member == True)
    & F.new_chat_member.status.in_(
        {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED}
    )
)
async def on_user_joined(event: ChatMemberUpdated, bot: Bot, session: AsyncSession):
    user = event.new_chat_member.user
    chat_id = event.chat.id
    if user.is_bot:
        return

    logger.info(
        f"Captcha Action (Start) user={user.id} chat={chat_id} name='{user.full_name}' status={event.new_chat_member.status}"
    )

    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(),
        )
    except Exception as e:
        logger.error(
            f"Captcha Action (Error) user={user.id} chat={chat_id} step=restrict error='{e}'"
        )
        return

    question, keyboard, correct_answer = generate_captcha()
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=f"Welcome, {user.full_name}!\n\n{question}",
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
            }
        ),
        ex=CAPTCHA_TTL,
    )

    asyncio.create_task(
        check_verification_timeout(bot, chat_id, user.id, message.message_id, session)
    )


async def check_verification_timeout(
    bot: Bot, chat_id: int, user_id: int, message_id: int, session: AsyncSession
):
    await asyncio.sleep(60)
    redis_key = _captcha_key(chat_id, user_id)
    if await redis_client.exists(redis_key):
        logger.warning(
            f"Captcha Action (Banned) user={user_id} chat={chat_id} reason=timeout"
        )
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            await notify_admin(
                bot,
                f"Captcha Action (Banned)\nUser: {user_id}\nChat: {chat_id}\nReason: timeout",
            )
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
        await query.answer("Captcha expired or not yours.", show_alert=True)
        return

    data = json.loads(raw_data)
    message_id = data["message_id"]
    _, selected_answer, correct_answer = query.data.split("_")

    await redis_client.delete(redis_key)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

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
        await notify_admin(
            bot,
            f"Captcha Action (Passed)\nUser: {user_id}\nChat: {chat_id}",
        )
        await query.answer("Verification passed!")
    else:
        logger.warning(
            f"Captcha Action (Banned) user={user_id} chat={chat_id} reason=wrong_answer"
        )
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await notify_admin(
            bot,
            f"Captcha Action (Banned)\nUser: {user_id}\nChat: {chat_id}\nReason: wrong_answer",
        )
        await ban_user(session, user_id)
        await query.answer("Incorrect answer. You have been banned.", show_alert=True)
