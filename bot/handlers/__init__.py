from aiogram import Router


def get_handlers_router() -> Router:
    from . import capcha, chat_config

    router = Router()
    router.include_router(chat_config.router)
    router.include_router(capcha.router)

    return router
