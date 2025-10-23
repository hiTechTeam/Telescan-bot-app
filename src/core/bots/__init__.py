import os
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv


load_dotenv()


__all__ = ["bot", "dp"]

bot = Bot(token=os.getenv("BOT_TOKEN"))  # type: ignore
dp = Dispatcher()
