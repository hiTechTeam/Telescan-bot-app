import logging
import asyncio
from src.app import app

log = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        asyncio.run(app())
    except KeyboardInterrupt:
        log.warning("KeyboardInterrupt and stop polling")
