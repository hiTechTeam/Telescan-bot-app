import secrets
from datetime import datetime
from uuid import UUID

from aiohttp import web

from src.app.runtime import Runtime


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def add_internal_routes(app: web.Application, runtime: Runtime) -> None:
    async def notify(request: web.Request) -> web.Response:
        expected = f"Bearer {runtime.settings.bot_service_secret}"
        provided = request.headers.get("Authorization", "")
        if not secrets.compare_digest(provided, expected):
            raise web.HTTPUnauthorized()
        try:
            payload = await request.json()
            confirmation_id = UUID(payload["confirmationId"])
            chat_id = int(payload["chatId"])
            expires_at = datetime.fromisoformat(
                payload["expiresAt"].replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError):
            raise web.HTTPBadRequest() from None
        await runtime.confirmations.send_confirmation(
            confirmation_id, chat_id, expires_at
        )
        return web.json_response({"accepted": True}, status=202)

    app.router.add_get("/health/live", health)
    app.router.add_post("/internal/v1/confirmation-notifications", notify)


async def start_internal_server(runtime: Runtime) -> web.AppRunner:
    app = web.Application(client_max_size=64 * 1024)
    add_internal_routes(app, runtime)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(
        runner,
        runtime.settings.internal_host,
        runtime.settings.internal_port,
    ).start()
    return runner
