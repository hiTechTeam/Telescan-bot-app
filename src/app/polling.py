import logging

from src.app.internal import start_internal_server
from src.app.runtime import Runtime

log = logging.getLogger(__name__)


async def app_polling(runtime: Runtime) -> None:
    runner = await start_internal_server(runtime)
    try:
        await runtime.confirmations.restore()
        await runtime.bot.delete_webhook(drop_pending_updates=True)
        await runtime.dispatcher.start_polling(runtime.bot)
    finally:
        await runtime.link_codes.close()
        await runtime.confirmations.close()
        await runner.cleanup()
        await runtime.bot.session.close()
