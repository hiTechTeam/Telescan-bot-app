import asyncio
import logging

from src.app import app_polling, build_runtime
from src.config import Settings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(app_polling(build_runtime(Settings())))
    except KeyboardInterrupt:
        pass
