from typing import Protocol

from aiogram import Bot

from src.domain.errors import TelegramUsernameRequired
from src.domain.models import IssuedCode


class LinkCodeAPI(Protocol):
    async def issue_link_code(
        self,
        telegram_id: int,
        name: str | None,
        username: str | None,
        photo: bytes | None,
        photo_state: str,
    ) -> IssuedCode: ...


class LinkCodeService:
    def __init__(self, bot: Bot, api: LinkCodeAPI) -> None:
        self._bot = bot
        self._api = api

    async def issue(
        self, telegram_id: int, name: str | None, username: str | None
    ) -> IssuedCode:
        normalized_username = (username or "").strip()
        if not normalized_username:
            raise TelegramUsernameRequired()
        photo: bytes | None = None
        photo_state = "absent"
        photos = await self._bot.get_user_profile_photos(telegram_id, limit=1)
        if photos.total_count and photos.photos:
            downloaded = await self._bot.download(photos.photos[0][-1].file_id)
            if downloaded is not None:
                photo = downloaded.read()
                photo_state = "present"
            else:
                photo_state = "unchanged"
        return await self._api.issue_link_code(
            telegram_id,
            name,
            normalized_username,
            photo,
            photo_state,
        )
