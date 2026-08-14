import logging

from src.app import app_webhook, build_runtime
from src.config import Settings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app_webhook(build_runtime(Settings()))
