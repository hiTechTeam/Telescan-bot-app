import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.domain.errors import TelegramUsernameRequired
from src.domain.models import ConfirmationDecision, IssuedCode, PendingConfirmation
from src.handlers.router import build_router
from src.services.confirmations import ConfirmationService
from src.services.link_codes import LinkCodeService


@pytest.mark.asyncio
@pytest.mark.parametrize("username", [None, "", "   "])
async def test_link_code_requires_public_telegram_username(
    username: str | None,
) -> None:
    bot = SimpleNamespace(
        get_user_profile_photos=AsyncMock(),
        download=AsyncMock(),
    )
    api = SimpleNamespace(issue_link_code=AsyncMock())

    with pytest.raises(TelegramUsernameRequired):
        await LinkCodeService(cast(Any, bot), cast(Any, api)).issue(
            123, "Ada", username
        )

    bot.get_user_profile_photos.assert_not_awaited()
    api.issue_link_code.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language_code", "expected_fragments"),
    [
        ("ru", ("публичный Telegram username", "Настройки")),
        ("en", ("public Telegram username", "Settings")),
    ],
)
async def test_missing_username_message_explains_how_to_fix_it(
    language_code: str,
    expected_fragments: tuple[str, str],
) -> None:
    link_codes = SimpleNamespace(
        issue=AsyncMock(side_effect=TelegramUsernameRequired())
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(
            id=123,
            first_name="Ada",
            username=None,
            language_code=language_code,
        ),
        answer=AsyncMock(),
    )
    router = build_router(link_codes, SimpleNamespace())
    handler = router.message.handlers[0].callback

    await handler(message)

    reply = message.answer.await_args.args[0]
    assert all(fragment in reply for fragment in expected_fragments)
    assert "/start" in reply


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language_code", "expected_fragment"),
    [("ru", "привязать Telegram"), ("en", "link Telegram")],
)
async def test_code_message_describes_linking_not_authentication(
    language_code: str,
    expected_fragment: str,
) -> None:
    link_codes = SimpleNamespace(
        issue=AsyncMock(
            return_value=IssuedCode(
                "ABCDEFGH", datetime.now(UTC) + timedelta(minutes=5)
            )
        )
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(
            id=123,
            first_name="Ada",
            username="ada",
            language_code=language_code,
        ),
        answer=AsyncMock(),
    )
    router = build_router(link_codes, SimpleNamespace())

    await router.message.handlers[0].callback(message)

    assert message.answer.await_count == 2
    explanation = message.answer.await_args_list[0].args[0]
    code = message.answer.await_args_list[1].args[0]
    assert expected_fragment in explanation
    assert "ABCDEFGH" not in explanation
    assert code == "<code>ABCDEFGH</code>"


@pytest.mark.asyncio
async def test_link_code_service_uses_api_without_database() -> None:
    photo_id = "telegram-photo-id"
    bot = SimpleNamespace(
        get_user_profile_photos=AsyncMock(
            return_value=SimpleNamespace(
                total_count=1,
                photos=[[SimpleNamespace(file_id=photo_id)]],
            )
        ),
        download=AsyncMock(return_value=BytesIO(b"\xff\xd8\xffphoto")),
    )
    api = SimpleNamespace(
        issue_link_code=AsyncMock(
            return_value=IssuedCode(
                "ABCDEFGH", datetime.now(UTC) + timedelta(minutes=5)
            )
        )
    )
    result = await LinkCodeService(cast(Any, bot), cast(Any, api)).issue(
        123, "Ada", "ada"
    )

    assert result.code == "ABCDEFGH"
    api.issue_link_code.assert_awaited_once_with(
        123, "Ada", "ada", b"\xff\xd8\xffphoto", "present"
    )


@pytest.mark.asyncio
async def test_link_code_marks_missing_telegram_photo_as_absent() -> None:
    bot = SimpleNamespace(
        get_user_profile_photos=AsyncMock(
            return_value=SimpleNamespace(total_count=0, photos=[])
        ),
        download=AsyncMock(),
    )
    api = SimpleNamespace(
        issue_link_code=AsyncMock(
            return_value=IssuedCode(
                code="12345678",
                expires_at=datetime.now(UTC),
            )
        )
    )

    await LinkCodeService(cast(Any, bot), cast(Any, api)).issue(123, "Ada", "ada")

    api.issue_link_code.assert_awaited_once_with(123, "Ada", "ada", None, "absent")
    bot.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_code_preserves_photo_when_download_fails() -> None:
    bot = SimpleNamespace(
        get_user_profile_photos=AsyncMock(
            return_value=SimpleNamespace(
                total_count=1,
                photos=[[SimpleNamespace(file_id="telegram-photo-id")]],
            )
        ),
        download=AsyncMock(return_value=None),
    )
    api = SimpleNamespace(
        issue_link_code=AsyncMock(
            return_value=IssuedCode(
                code="12345678",
                expires_at=datetime.now(UTC),
            )
        )
    )

    await LinkCodeService(cast(Any, bot), cast(Any, api)).issue(123, "Ada", "ada")

    api.issue_link_code.assert_awaited_once_with(123, "Ada", "ada", None, "unchanged")


@pytest.mark.asyncio
async def test_link_code_preserves_photo_when_telegram_lookup_fails() -> None:
    bot = SimpleNamespace(
        get_user_profile_photos=AsyncMock(side_effect=OSError("unavailable")),
        download=AsyncMock(),
    )
    api = SimpleNamespace(
        issue_link_code=AsyncMock(
            return_value=IssuedCode(
                code="12345678",
                expires_at=datetime.now(UTC),
            )
        )
    )

    await LinkCodeService(cast(Any, bot), cast(Any, api)).issue(123, "Ada", "ada")

    api.issue_link_code.assert_awaited_once_with(123, "Ada", "ada", None, "unchanged")
    bot.download.assert_not_awaited()


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("bot_token", "replace-token", "BOT_TOKEN"),
        ("bot_token", "change-me-token", "BOT_TOKEN"),
        ("bot_token", "not-a-telegram-token", "BOT_TOKEN"),
        (
            "bot_service_secret",
            "replace-with-a-service-secret-value",
            "BOT_SERVICE_SECRET",
        ),
        ("api_base_url", "https://api.tgtelescan.ru", "private Docker network"),
        (
            "api_base_url",
            "http://telescan-api:8000?redirect=evil",
            "private Docker network",
        ),
    ],
)
def test_production_rejects_placeholder_secrets_and_public_api_route(
    field: str, value: str, error: str
) -> None:
    values: dict[str, object] = {
        "environment": "production",
        "bot_token": "123456:valid-looking-token",
        "bot_service_secret": "s" * 32,
    }
    values[field] = value

    with pytest.raises(ValidationError, match=error):
        Settings.model_validate(values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "message"),
    [
        ("confirmed", "Выход выполнен на всех устройствах"),
        ("cancelled", "Выход со всех устройств отменён"),
    ],
)
async def test_confirmation_deletes_buttons_and_sends_separate_result(
    decision: str, message: str
) -> None:
    confirmation_id = uuid4()
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=77)),
        delete_message=AsyncMock(),
    )
    api = SimpleNamespace(
        register_confirmation_message=AsyncMock(),
        decide_confirmation=AsyncMock(
            return_value=ConfirmationDecision(confirmation_id, decision, 123, 77)
        ),
    )
    service = ConfirmationService(cast(Any, bot), cast(Any, api))
    await service.send_confirmation(
        confirmation_id, 123, datetime.now(UTC) + timedelta(minutes=5)
    )
    status = await service.process_decision(confirmation_id, 123, 123, 77, decision)

    assert status == decision
    bot.delete_message.assert_awaited_once_with(123, 77)
    assert bot.send_message.await_args_list[-1].args == (123, message)
    await service.close()


@pytest.mark.asyncio
async def test_expiry_deletes_message_and_restore_recreates_task() -> None:
    confirmation_id = uuid4()
    expired = datetime.now(UTC) - timedelta(seconds=1)
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        delete_message=AsyncMock(),
    )
    api = SimpleNamespace(
        pending_confirmations=AsyncMock(
            return_value=[PendingConfirmation(confirmation_id, expired, 123, 77)]
        ),
        decide_confirmation=AsyncMock(
            return_value=ConfirmationDecision(confirmation_id, "expired", 123, 77)
        ),
    )
    service = ConfirmationService(cast(Any, bot), cast(Any, api))
    await service.restore()
    await asyncio.sleep(0.01)

    api.decide_confirmation.assert_awaited_once_with(confirmation_id, 123, "expired")
    bot.delete_message.assert_awaited_once_with(123, 77)
    bot.send_message.assert_awaited_once_with(
        123, "Время подтверждения истекло. Выход не выполнен"
    )
    await service.close()


def test_deploy_dispatches_durable_locked_controller_with_rollback() -> None:
    repository = Path(__file__).resolve().parents[1]
    workflow = (repository / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    controller = (repository / "ops/deploy-production.sh").read_text(encoding="utf-8")

    assert ".releases/Telescan-bot-app/" in workflow
    assert "sudo systemd-run --wait --collect" in workflow
    main = controller[controller.index("main() {") :]
    assert main.index("flock -w 1800 9") < main.index('deploy_release "$2" "$3"')
    assert '"$snapshot_dir/" "$ACTIVE_DIR/"' in controller
    assert "protected previous release did not recover healthy" in controller
    assert "intent phase --expected prepared --new committed" in controller
    assert '"$container_id" != "$global_ids"' in controller
