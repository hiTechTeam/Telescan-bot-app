import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web

from src.app.internal import add_internal_routes, health


@pytest.mark.asyncio
async def test_internal_server_reports_liveness() -> None:
    app = web.Application()
    runtime = SimpleNamespace(
        settings=SimpleNamespace(bot_service_secret="test-service-secret")
    )
    add_internal_routes(app, cast(Any, runtime))

    response = await health(cast(web.Request, object()))

    assert response.status == 200
    assert response.text is not None
    assert json.loads(response.text) == {"status": "ok"}
    assert any(
        resource.canonical == "/health/live" for resource in app.router.resources()
    )
