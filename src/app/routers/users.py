import logging
from src.app.routers import router
from aiogram.filters import CommandStart
from aiogram.types import Message
from src.core.bots import bot

log = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message):
    tg_id = message.from_user.id  # type: ignore
    username = message.from_user.username  # type: ignore

    photos = await bot.get_user_profile_photos(tg_id, limit=1)
    photo_file_id = photos.photos[0][0].file_id if photos.total_count > 0 else None

    await message.answer(
        f"ID: {tg_id}\n" f"Username: @{username}\n" f"Фото id:  {photo_file_id}",
    )
