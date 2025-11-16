import logging
from src.app import app_webhook

log = logging.getLogger(__name__)


if __name__ == "__main__":
    try:
        app_webhook()
    except KeyboardInterrupt:
        log.warning("KeyboardInterrupt and stop polling")
    except Exception as e:
        log.error("Exception %s", e, exc_info=True)
