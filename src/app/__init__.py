import logging
from src.core.bots import bot, dp
from src.app.routers.users import router
from src.core.log import conf_logging

__all__ = ["app"]

log = logging.getLogger(__name__)


async def app():
    conf_logging(level=logging.INFO)
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        log.error(e)
