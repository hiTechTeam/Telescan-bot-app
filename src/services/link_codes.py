import asyncio
import logging
from typing import Protocol

from aiohttp import ClientError
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from src.domain.errors import APIRejected, APIUnavailable, TelegramUsernameRequired
from src.domain.models import IssuedCode


logger = logging.getLogger(__name__)

PHOTO_FETCH_ATTEMPTS = 3
PHOTO_LOOKUP_TIMEOUT_SECONDS = 15
PHOTO_DOWNLOAD_TIMEOUT_SECONDS = 10
PHOTO_RETRY_DELAYS_SECONDS = (0.25, 0.75)
PHOTO_SYNC_ATTEMPTS = 3
PHOTO_SYNC_RETRY_DELAYS_SECONDS = (0.25, 0.75)


class LinkCodeAPI(Protocol):
    async def issue_link_code(
        self,
        telegram_id: int,
        name: str | None,
        username: str | None,
        photo: bytes | None,
        photo_state: str,
    ) -> IssuedCode: ...

    async def sync_telegram_profile_photo(
        self,
        telegram_id: int,
        photo: bytes | None,
        photo_state: str,
    ) -> None: ...


class LinkCodeService:
    def __init__(self, bot: Bot, api: LinkCodeAPI) -> None:
        self._bot = bot
        self._api = api
        self._photo_sync_tasks: set[asyncio.Task[None]] = set()

    async def issue(
        self, telegram_id: int, name: str | None, username: str | None
    ) -> IssuedCode:
        normalized_username = (username or "").strip()
        if not normalized_username:
            raise TelegramUsernameRequired()
        issued = await self._api.issue_link_code(
            telegram_id,
            name,
            normalized_username,
            None,
            "unchanged",
        )
        self._schedule_profile_photo_sync(telegram_id)
        return issued

    def _schedule_profile_photo_sync(self, telegram_id: int) -> None:
        task = asyncio.create_task(
            self._sync_profile_photo(telegram_id),
            name=f"telegram-profile-photo-sync:{telegram_id}",
        )
        self._photo_sync_tasks.add(task)
        task.add_done_callback(self._profile_photo_sync_done)

    def _profile_photo_sync_done(self, task: asyncio.Task[None]) -> None:
        self._photo_sync_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("Telegram profile photo background sync failed")

    async def _sync_profile_photo(self, telegram_id: int) -> None:
        photo, photo_state = await self._load_profile_photo(telegram_id)
        for attempt in range(PHOTO_SYNC_ATTEMPTS):
            try:
                await self._api.sync_telegram_profile_photo(
                    telegram_id,
                    photo,
                    photo_state,
                )
                return
            except (APIUnavailable, APIRejected):
                if attempt == PHOTO_SYNC_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(PHOTO_SYNC_RETRY_DELAYS_SECONDS[attempt])

    async def _load_profile_photo(self, telegram_id: int) -> tuple[bytes | None, str]:
        for attempt in range(PHOTO_FETCH_ATTEMPTS):
            stage = "lookup"
            try:
                async with asyncio.timeout(PHOTO_LOOKUP_TIMEOUT_SECONDS):
                    photos = await self._bot.get_user_profile_photos(
                        telegram_id,
                        limit=1,
                    )
                    if not photos.total_count or not photos.photos:
                        return None, "absent"

                    sizes = photos.photos[0]
                    if not sizes:
                        raise OSError("Telegram returned an empty profile photo set")

                # Telegram orders sizes from smallest to largest. Prefer the
                # maximum avatar, but let one problematic file fall back to
                # the next size instead of losing the photo altogether.
                stage = "download"
                last_download_error: Exception | None = None
                for size in reversed(sizes):
                    try:
                        async with asyncio.timeout(PHOTO_DOWNLOAD_TIMEOUT_SECONDS):
                            downloaded = await self._bot.download(size.file_id)
                        if downloaded is None:
                            raise OSError("Telegram returned no profile photo data")
                        photo = downloaded.read()
                        if not photo:
                            raise OSError("Telegram returned an empty profile photo")
                        return photo, "present"
                    except (
                        TelegramAPIError,
                        ClientError,
                        OSError,
                        TimeoutError,
                    ) as error:
                        last_download_error = error
                        logger.info(
                            "Telegram profile photo size is unavailable (%s); "
                            "trying the next size",
                            type(error).__name__,
                        )
                if last_download_error is not None:
                    raise last_download_error
                raise OSError("Telegram returned no downloadable profile photo")
            except (TelegramAPIError, ClientError, OSError, TimeoutError) as error:
                if attempt == PHOTO_FETCH_ATTEMPTS - 1:
                    logger.warning(
                        "Telegram profile photo is temporarily unavailable after %s "
                        "attempts during %s (%s)",
                        PHOTO_FETCH_ATTEMPTS,
                        stage,
                        type(error).__name__,
                    )
                    return None, "unchanged"
                await asyncio.sleep(PHOTO_RETRY_DELAYS_SECONDS[attempt])

        return None, "unchanged"

    async def close(self) -> None:
        tasks = list(self._photo_sync_tasks)
        self._photo_sync_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
