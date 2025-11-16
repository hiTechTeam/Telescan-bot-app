import logging
import asyncio
from src.app import app_polling
from src.core.bots import bot

log = logging.getLogger(__name__)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await app_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("KeyboardInterrupt and stop polling")
