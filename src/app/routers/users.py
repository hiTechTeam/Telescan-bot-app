import logging
from src.app.routers import router
from aiogram.filters import CommandStart
from aiogram.types import Message
from src.core.bots import bot
from src.core.scripts import generate_code
from src.core.db.models import User


log = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message):
    tg_id = message.from_user.id  # type: ignore
    tg_username = message.from_user.username  # type: ignore

    photos = await bot.get_user_profile_photos(tg_id, limit=1)
    photo_file_id = photos.photos[0][0].file_id if photos.total_count > 0 else None

    user_data = await User.find_one(User.tg_id == tg_id)

    if user_data:
        await message.answer(f"<b><code>{user_data.code}</code></b>", parse_mode="HTML")
        return

    while True:
        code = await generate_code()
        if not await User.find_one(User.code == code):
            break

    user = User(tg_id=tg_id, tg_username=tg_username, code=code)
    await User.insert(user)

    await message.answer(f"<b><code>{code}</code></b>", parse_mode="HTML")
