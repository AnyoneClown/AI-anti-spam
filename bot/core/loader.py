from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from aiohttp import web
from redis.asyncio import ConnectionPool, Redis

from bot.core.config import settings

app = web.Application()

token = settings.BOT_TOKEN

bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

redis_client = Redis(
    connection_pool=ConnectionPool(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASS,
        db=0,
    ),
)

storage = RedisStorage(
    redis=redis_client,
    key_builder=DefaultKeyBuilder(with_bot_id=True),
)

dp = Dispatcher(storage=storage)

DEBUG = settings.DEBUG
