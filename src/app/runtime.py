from dataclasses import dataclass

from aiogram import Bot, Dispatcher

from src.config import Settings
from src.handlers import build_router
from src.infrastructure.api_client import TelescanAPIClient
from src.infrastructure.telegram import create_bot
from src.services import ConfirmationService, LinkCodeService


@dataclass(slots=True)
class Runtime:
    settings: Settings
    bot: Bot
    dispatcher: Dispatcher
    api: TelescanAPIClient
    confirmations: ConfirmationService


def build_runtime(settings: Settings) -> Runtime:
    bot = create_bot(settings)
    api = TelescanAPIClient(
        settings.api_base_url,
        settings.bot_service_secret,
        settings.api_timeout_seconds,
    )
    confirmations = ConfirmationService(bot, api)
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_router(LinkCodeService(bot, api), confirmations)
    )
    return Runtime(settings, bot, dispatcher, api, confirmations)
