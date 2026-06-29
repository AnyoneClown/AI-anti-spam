from aiogram import Router


def get_handlers_router() -> Router:
    from . import capcha

    router = Router()
    router.include_router(capcha.router)

    return router
