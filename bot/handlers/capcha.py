import asyncio
import json
import random

from aiogram import Bot, F, Router
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from loguru import logger

from bot.core.loader import redis_client

router = Router()

# --- Helper function to create a captcha ---
def generate_captcha():
    """Generates a simple math question and answer options."""
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    correct_answer = a + b
    # Ensure answers are unique
    answers = {correct_answer}
    while len(answers) < 3:
        # Avoid zero or negative answers if possible
        answers.add(correct_answer + random.randint(-5, 5) or 1)

    shuffled_answers = random.sample(list(answers), len(answers))
    
    question = f"To continue, please solve this: {a} + {b} = ?"
    
    buttons = [
        InlineKeyboardButton(text=str(ans), callback_data=f"captcha_{ans}_{correct_answer}")
        for ans in shuffled_answers
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    
    return question, keyboard, correct_answer

# --- Handler for a new user joining the chat ---
# Corrected Filter: Use F-object to check old and new member statuses.
@router.chat_member(
    F.chat.type.in_({"group", "supergroup"})
    & (F.new_chat_member.status == ChatMemberStatus.MEMBER)
)
async def on_user_joined(event: ChatMemberUpdated, bot: Bot):
    user = event.new_chat_member.user
    chat_id = event.chat.id
    if user.is_bot:
        return # Ignore other bots

    logger.info(f"New user {user.full_name} ({user.id}) joined chat {chat_id}. Starting verification.")

    # Restrict user permissions immediately
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions() # Empty permissions object disallows everything
        )
    except Exception as e:
        logger.error(f"Failed to restrict user {user.id} in chat {chat_id}: {e}")
        return

    question, keyboard, correct_answer = generate_captcha()
    
    message = await bot.send_message(
        chat_id=chat_id,
        text=f"Welcome, {user.full_name}!\n\n{question}",
        reply_markup=keyboard
    )

    # Store verification data in Redis with a TTL (Time To Live)
    redis_key = f"captcha:{user.id}"
    verification_data = {
        "chat_id": chat_id,
        "message_id": message.message_id,
        "correct_answer": correct_answer
    }
    # Set TTL to 65 seconds to be safe
    await redis_client.set(redis_key, json.dumps(verification_data), ex=65)

    # Schedule a task to check for timeout, instead of blocking with sleep
    asyncio.create_task(check_verification_timeout(bot, chat_id, user.id, message.message_id))

async def check_verification_timeout(bot: Bot, chat_id: int, user_id: int, message_id: int):
    """Checks if the user has solved the captcha in time."""
    await asyncio.sleep(60)
    
    redis_key = f"captcha:{user_id}"
    if await redis_client.exists(redis_key):
        logger.warning(f"User {user_id} failed verification (timeout). Banning.")
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.error(f"Error during timeout ban for user {user_id}: {e}")
        finally:
            await redis_client.delete(redis_key)

# --- Callback handler for the captcha answer ---
@router.callback_query(F.data.startswith("captcha_"))
async def process_captcha_callback(query: CallbackQuery, bot: Bot):
    user_id = query.from_user.id
    redis_key = f"captcha:{user_id}"

    raw_data = await redis_client.get(redis_key)

    if not raw_data:
        await query.answer("This check is not for you or has expired.", show_alert=True)
        return

    data = json.loads(raw_data)
    chat_id = data["chat_id"]
    message_id = data["message_id"]
    
    _, selected_answer, correct_answer = query.data.split("_")

    # Delete the key from Redis immediately to prevent multiple attempts
    await redis_client.delete(redis_key)

    # Delete the captcha message in any case
    await bot.delete_message(chat_id=chat_id, message_id=message_id)

    if int(selected_answer) == int(correct_answer):
        logger.info(f"User {user_id} passed verification in chat {chat_id}.")
        # Correctly restore standard user permissions
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            )
        )
        await query.answer("Verification passed!", show_alert=False)
    else:
        logger.warning(f"User {user_id} failed verification (wrong answer). Banning.")
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await query.answer("Incorrect answer. You have been banned.", show_alert=True)