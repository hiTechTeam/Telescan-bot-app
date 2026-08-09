import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv

load_dotenv()

__all__ = ["bot", "dp"]

bot_token = os.getenv("BOT_TOKEN")
proxy_url = os.getenv("TELEGRAM_PROXY_URL")

if not bot_token:
    raise RuntimeError("Переменная BOT_TOKEN не задана")

if not proxy_url:
    raise RuntimeError("Переменная TELEGRAM_PROXY_URL не задана")

session = AiohttpSession(proxy=proxy_url)

bot = Bot(
    token=bot_token,
    session=session,
)

dp = Dispatcher()
