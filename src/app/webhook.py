import os
import logging
from beanie import init_beanie
from aiogram import Bot  # noqa
from aiohttp import web  # noqa
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler,  # noqa
    setup_application,  # noqa
)
from src.core.db.models import User
from src.core.db import mongo_client
from src.core.bots import dp, bot
from src.app.routers import router
from src.core.conf import settings as s


from dotenv import load_dotenv

load_dotenv()

LOCAL_WEBAPP_HOST = "0.0.0.0"
LOCAL_WEBAPP_PORT = 8080
WEBHOOK_PATH = "/bot/telescanbot/webhook/"
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")


log = logging.getLogger(__name__)


async def on_bot_startup(bot: Bot) -> None:
    me = await bot.get_me()
    log.warning("Starting bot %s", me.username)

    wh_info = await bot.get_webhook_info()
    current_url = wh_info.url or ""

    desired_url = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"

    await init_beanie(
        database=mongo_client[s.mongo_client_name],
        document_models=[User],
    )

    if current_url != desired_url:
        if current_url:
            log.info("Deleting old webhook: %s", current_url)
            await bot.delete_webhook(drop_pending_updates=False)

        log.info("Setting new webhook: %s", desired_url)
        await bot.set_webhook(
            url=desired_url,
            secret_token=WEBHOOK_SECRET_TOKEN,
        )
        wh_info = await bot.get_webhook_info()
        log.info("Webhook successfully set: %s", wh_info)
    else:
        log.info("Webhook is already up-to-date: %s", current_url)


def create_prepared_web_app() -> web.Application:
    dp.include_router(router)
    dp.startup.register(on_bot_startup)

    app = web.Application()

    aiogram_webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET_TOKEN,
        handle_in_background=False,
    )
    aiogram_webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    return app


def app_webhook() -> None:
    logging.basicConfig(level=logging.INFO)
    app = create_prepared_web_app()
    web.run_app(
        app,
        host=LOCAL_WEBAPP_HOST,
        port=LOCAL_WEBAPP_PORT,
    )
