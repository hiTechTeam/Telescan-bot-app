import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, call
from uuid import uuid4

import pytest
from pydantic import ValidationError

import src.services.link_codes as link_codes_module
from src.config import Settings
from src.domain.errors import PublicContentRejected, TelegramUsernameRequired
from src.domain.models import ConfirmationDecision, IssuedCode, PendingConfirmation
from src.handlers.router import build_router
from src.infrastructure.api_client import TelescanAPIClient
from src.services.confirmations import ConfirmationService
from src.services.link_codes import LinkCodeService


async def _wait_for_photo_sync(service: LinkCodeService) -> None:
    tasks = tuple(service._photo_sync_tasks)
    if tasks:
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("photo", "photo_state", "expected_fields"),
    [
        (b"\xff\xd8\xffphoto", "present", {"photo", "photo_state"}),
        (None, "absent", {"photo_state"}),
    ],
)
async def test_api_client_uses_photo_sync_multipart_contract(
    photo: bytes | None,
    photo_state: str,
    expected_fields: set[str],
) -> None:
    client = TelescanAPIClient("http://api", "secret", 1)
    request = AsyncMock()
    cast(Any, client)._request = request

    await client.sync_telegram_profile_photo(123, photo, photo_state)

    awaited = request.await_args
    assert awaited is not None
    assert awaited.args == (
        "PUT",
        "/internal/v1/telegram-profiles/123/photo",
    )
    form = awaited.kwargs["data"]
    fields = {field[0]["name"]: field for field in form._fields}
    assert set(fields) == expected_fields
    assert fields["photo_state"][2] == photo_state
    if photo is not None:
        assert fields["photo"][0]["filename"] == "telegram-profile.jpg"
        assert fields["photo"][1]["Content-Type"] == "image/jpeg"
        assert fields["photo"][2] == photo
    payload = form()
    assert payload.headers["Content-Type"].startswith("multipart/form-data;")


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
    [("ru", "правила публичного профиля"), ("en", "public-profile rules")],
)
async def test_rejected_public_profile_explains_how_to_fix_it(
    language_code: str,
    expected_fragment: str,
) -> None:
    link_codes = SimpleNamespace(issue=AsyncMock(side_effect=PublicContentRejected()))
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

    reply = message.answer.await_args.args[0]
    assert expected_fragment in reply
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
async def test_link_code_is_returned_without_waiting_for_photo_fetch() -> None:
    photo_started = asyncio.Event()
    release_photo = asyncio.Event()

    async def blocked_photo_lookup(*args: object, **kwargs: object) -> object:
        photo_started.set()
        await release_photo.wait()
        return SimpleNamespace(total_count=0, photos=[])

    bot = SimpleNamespace(
        get_user_profile_photos=AsyncMock(side_effect=blocked_photo_lookup),
        download=AsyncMock(),
    )

    async def issue_link_code(*args: object) -> IssuedCode:
        bot.get_user_profile_photos.assert_not_awaited()
        return IssuedCode("ABCDEFGH", datetime.now(UTC) + timedelta(minutes=5))

    api = SimpleNamespace(
        issue_link_code=AsyncMock(side_effect=issue_link_code),
        sync_telegram_profile_photo=AsyncMock(),
    )
    service = LinkCodeService(cast(Any, bot), cast(Any, api))

    result = await service.issue(123, "Ada", "ada")

    assert result.code == "ABCDEFGH"
    api.issue_link_code.assert_awaited_once_with(123, "Ada", "ada", None, "unchanged")
    await asyncio.wait_for(photo_started.wait(), timeout=0.1)
    api.sync_telegram_profile_photo.assert_not_awaited()

    release_photo.set()
    await _wait_for_photo_sync(service)
    api.sync_telegram_profile_photo.assert_awaited_once_with(123, None, "absent")


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
        ),
        sync_telegram_profile_photo=AsyncMock(),
    )
    service = LinkCodeService(cast(Any, bot), cast(Any, api))

    await service.issue(123, "Ada", "ada")
    await _wait_for_photo_sync(service)

    api.issue_link_code.assert_awaited_once_with(123, "Ada", "ada", None, "unchanged")
    api.sync_telegram_profile_photo.assert_awaited_once_with(123, None, "absent")
    bot.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_photo_sync_preserves_photo_when_download_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(link_codes_module, "PHOTO_RETRY_DELAYS_SECONDS", (0, 0))
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
        ),
        sync_telegram_profile_photo=AsyncMock(),
    )
    service = LinkCodeService(cast(Any, bot), cast(Any, api))

    await service.issue(123, "Ada", "ada")
    await _wait_for_photo_sync(service)

    api.issue_link_code.assert_awaited_once_with(123, "Ada", "ada", None, "unchanged")
    api.sync_telegram_profile_photo.assert_awaited_once_with(123, None, "unchanged")
    assert bot.get_user_profile_photos.await_count == 3
    assert bot.download.await_count == 3


@pytest.mark.asyncio
async def test_link_code_retries_a_transient_telegram_photo_failure() -> None:
    small_photo_id = "small-telegram-photo-id"
    large_photo_id = "large-telegram-photo-id"
    bot = SimpleNamespace(
        get_user_profile_photos=AsyncMock(
            side_effect=[
                OSError("temporarily unavailable"),
                SimpleNamespace(
                    total_count=1,
                    photos=[
                        [
                            SimpleNamespace(file_id=small_photo_id),
                            SimpleNamespace(file_id=large_photo_id),
                        ]
                    ],
                ),
            ]
        ),
        download=AsyncMock(return_value=BytesIO(b"\xff\xd8\xffphoto")),
    )
    api = SimpleNamespace(
        issue_link_code=AsyncMock(
            return_value=IssuedCode(
                code="12345678",
                expires_at=datetime.now(UTC),
            )
        ),
        sync_telegram_profile_photo=AsyncMock(),
    )
    service = LinkCodeService(cast(Any, bot), cast(Any, api))

    await service.issue(123, "Ada", "ada")
    await _wait_for_photo_sync(service)

    assert bot.get_user_profile_photos.await_count == 2
    bot.download.assert_awaited_once_with(large_photo_id)
    api.issue_link_code.assert_awaited_once_with(123, "Ada", "ada", None, "unchanged")
    api.sync_telegram_profile_photo.assert_awaited_once_with(
        123, b"\xff\xd8\xffphoto", "present"
    )


@pytest.mark.asyncio
async def test_photo_download_falls_back_only_after_largest_size_fails() -> None:
    small_photo_id = "small-telegram-photo-id"
    large_photo_id = "large-telegram-photo-id"
    bot = SimpleNamespace(
        get_user_profile_photos=AsyncMock(
            return_value=SimpleNamespace(
                total_count=1,
                photos=[
                    [
                        SimpleNamespace(file_id=small_photo_id),
                        SimpleNamespace(file_id=large_photo_id),
                    ]
                ],
            )
        ),
        download=AsyncMock(
            side_effect=[
                OSError("large file temporarily unavailable"),
                BytesIO(b"\xff\xd8\xffsmall-fallback"),
            ]
        ),
    )
    api = SimpleNamespace(
        issue_link_code=AsyncMock(
            return_value=IssuedCode("12345678", datetime.now(UTC))
        ),
        sync_telegram_profile_photo=AsyncMock(),
    )
    service = LinkCodeService(cast(Any, bot), cast(Any, api))

    await service.issue(123, "Ada", "ada")
    await _wait_for_photo_sync(service)

    assert bot.download.await_args_list == [
        call(large_photo_id),
        call(small_photo_id),
    ]
    api.sync_telegram_profile_photo.assert_awaited_once_with(
        123, b"\xff\xd8\xffsmall-fallback", "present"
    )


@pytest.mark.asyncio
async def test_persistent_photo_timeout_does_not_issue_a_second_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never_finishes = asyncio.Event()

    async def timed_out_lookup(*args: object, **kwargs: object) -> object:
        await never_finishes.wait()
        return SimpleNamespace(total_count=0, photos=[])

    monkeypatch.setattr(link_codes_module, "PHOTO_LOOKUP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(link_codes_module, "PHOTO_RETRY_DELAYS_SECONDS", (0, 0))
    bot = SimpleNamespace(
        get_user_profile_photos=AsyncMock(side_effect=timed_out_lookup),
        download=AsyncMock(),
    )
    api = SimpleNamespace(
        issue_link_code=AsyncMock(
            return_value=IssuedCode(
                code="12345678",
                expires_at=datetime.now(UTC),
            )
        ),
        sync_telegram_profile_photo=AsyncMock(),
    )
    service = LinkCodeService(cast(Any, bot), cast(Any, api))

    result = await service.issue(123, "Ada", "ada")
    await _wait_for_photo_sync(service)

    assert result.code == "12345678"
    api.issue_link_code.assert_awaited_once_with(123, "Ada", "ada", None, "unchanged")
    api.sync_telegram_profile_photo.assert_awaited_once_with(123, None, "unchanged")
    assert bot.get_user_profile_photos.await_count == 3
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
