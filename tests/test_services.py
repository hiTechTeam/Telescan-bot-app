import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

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
