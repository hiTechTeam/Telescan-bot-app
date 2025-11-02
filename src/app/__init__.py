import logging
from src.core.bots import bot, dp
from src.app.routers.users import router
from src.core.log import conf_logging
from beanie import init_beanie
from src.core.db import mongo_client
from src.core.db.models import User
from src.core.conf import settings as s


__all__ = ["app"]

log = logging.getLogger(__name__)


async def app():
    await init_beanie(
        database=mongo_client[s.mongo_client_name],
        document_models=[User],
    )
    conf_logging(level=logging.INFO)
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        log.error(e)
