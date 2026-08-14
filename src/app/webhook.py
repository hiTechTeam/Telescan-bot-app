from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from src.app.internal import add_internal_routes
from src.app.runtime import Runtime


def create_webhook_app(runtime: Runtime) -> web.Application:
    settings = runtime.settings
    if not settings.webhook_base_url or not settings.webhook_secret_token:
        raise RuntimeError("Webhook settings are required")
    app = web.Application(client_max_size=2 * 1024 * 1024)
    add_internal_routes(app, runtime)
    SimpleRequestHandler(
        dispatcher=runtime.dispatcher,
        bot=runtime.bot,
        secret_token=settings.webhook_secret_token,
        handle_in_background=False,
    ).register(app, path=settings.webhook_path)

    async def startup(_: web.Application) -> None:
        await runtime.confirmations.restore()
        await runtime.bot.set_webhook(
            f"{settings.webhook_base_url.rstrip('/')}{settings.webhook_path}",
            secret_token=settings.webhook_secret_token,
        )

    async def cleanup(_: web.Application) -> None:
        await runtime.confirmations.close()
        await runtime.bot.session.close()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    setup_application(app, runtime.dispatcher, bot=runtime.bot)
    return app


def app_webhook(runtime: Runtime) -> None:
    web.run_app(
        create_webhook_app(runtime),
        host=runtime.settings.internal_host,
        port=runtime.settings.internal_port,
    )
