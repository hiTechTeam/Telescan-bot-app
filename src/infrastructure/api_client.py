from datetime import datetime
from typing import Any
from uuid import UUID

import aiohttp

from src.domain.errors import APIRejected, APIUnavailable
from src.domain.models import ConfirmationDecision, IssuedCode, PendingConfirmation


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TelescanAPIClient:
    def __init__(self, base_url: str, service_secret: str, timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = service_secret
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._secret}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.request(
                    method, f"{self._base_url}{path}", headers=headers, **kwargs
                ) as response:
                    if response.status not in range(200, 300):
                        raise APIRejected(f"API status {response.status}")
                    if response.status == 204:
                        return None
                    return await response.json()
        except (aiohttp.ClientError, TimeoutError) as error:
            raise APIUnavailable() from error

    async def issue_link_code(
        self,
        telegram_id: int,
        name: str | None,
        username: str | None,
        photo: bytes | None,
        photo_state: str,
    ) -> IssuedCode:
        form = aiohttp.FormData()
        form.add_field("tg_id", str(telegram_id))
        form.add_field("photo_state", photo_state)
        if name is not None:
            form.add_field("tg_name", name)
        if username is not None:
            form.add_field("tg_username", username)
        if photo is not None:
            form.add_field(
                "photo",
                photo,
                filename="telegram-profile.jpg",
                content_type="image/jpeg",
            )
        payload: dict[str, Any] = await self._request(
            "POST", "/internal/v1/link-codes", data=form
        )
        return IssuedCode(
            code=payload["code"],
            expires_at=_datetime(payload["expiresAt"]),
        )

    async def register_confirmation_message(
        self, confirmation_id: UUID, chat_id: int, message_id: int
    ) -> None:
        await self._request(
            "PUT",
            f"/internal/v1/confirmations/{confirmation_id}/message",
            json={"telegramChatId": chat_id, "telegramMessageId": message_id},
        )

    async def pending_confirmations(self) -> list[PendingConfirmation]:
        payload: list[dict[str, Any]] = await self._request(
            "GET", "/internal/v1/confirmations/pending"
        )
        return [
            PendingConfirmation(
                confirmation_id=UUID(item["confirmationId"]),
                expires_at=_datetime(item["expiresAt"]),
                telegram_chat_id=item.get("telegramChatId"),
                telegram_message_id=item.get("telegramMessageId"),
            )
            for item in payload
        ]

    async def decide_confirmation(
        self, confirmation_id: UUID, telegram_id: int, decision: str
    ) -> ConfirmationDecision:
        payload: dict[str, Any] = await self._request(
            "POST",
            f"/internal/v1/confirmations/{confirmation_id}/decision",
            json={"telegramId": telegram_id, "decision": decision},
        )
        return ConfirmationDecision(
            confirmation_id=UUID(payload["confirmationId"]),
            status=payload["status"],
            telegram_chat_id=payload.get("telegramChatId"),
            telegram_message_id=payload.get("telegramMessageId"),
        )
