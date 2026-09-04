import asyncio
import logging
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from src.domain.errors import TelegramUsernameRequired
from src.domain.models import IssuedCode


logger = logging.getLogger(__name__)

PHOTO_FETCH_ATTEMPTS = 3
PHOTO_FETCH_TIMEOUT_SECONDS = 15
PHOTO_RETRY_DELAYS_SECONDS = (0.25, 0.75)


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
        photo, photo_state = await self._load_profile_photo(telegram_id)
        return await self._api.issue_link_code(
            telegram_id,
            name,
            normalized_username,
            photo,
            photo_state,
        )

    async def _load_profile_photo(self, telegram_id: int) -> tuple[bytes | None, str]:
        for attempt in range(PHOTO_FETCH_ATTEMPTS):
            try:
                async with asyncio.timeout(PHOTO_FETCH_TIMEOUT_SECONDS):
                    photos = await self._bot.get_user_profile_photos(
                        telegram_id,
                        limit=1,
                    )
                    if not photos.total_count or not photos.photos:
                        return None, "absent"

                    downloaded = await self._bot.download(photos.photos[0][-1].file_id)
                    if downloaded is None:
                        raise OSError("Telegram returned no profile photo data")

                    photo = downloaded.read()
                    if not photo:
                        raise OSError("Telegram returned an empty profile photo")
                    return photo, "present"
            except (TelegramAPIError, OSError, TimeoutError) as error:
                if attempt == PHOTO_FETCH_ATTEMPTS - 1:
                    logger.warning(
                        "Telegram profile photo is temporarily unavailable after %s "
                        "attempts (%s)",
                        PHOTO_FETCH_ATTEMPTS,
                        type(error).__name__,
                    )
                    return None, "unchanged"
                await asyncio.sleep(PHOTO_RETRY_DELAYS_SECONDS[attempt])

        return None, "unchanged"
