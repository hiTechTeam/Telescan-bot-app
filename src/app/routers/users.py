import hashlib
import logging
from src.app.routers import router
from aiogram.filters import Command
from aiogram.types import Message
from src.core.bots import bot
from src.core.scripts import generate_code
from src.core.db.models import User
from src.core.conf import settings as s


log = logging.getLogger(__name__)


@router.message(Command(commands=["start", "code"]))
async def cmd_start(message: Message):
    """
    Processing the /start command.
    Extracts user data and returns a code.
    """

    tg_id = message.from_user.id  # type: ignore
    tg_name = message.from_user.first_name  # type: ignore
    tg_username = message.from_user.username  # type: ignore

    photos = await bot.get_user_profile_photos(tg_id, limit=1)
    photo_file_id = photos.photos[0][-1].file_id if photos.total_count > 0 else None

    user_data = await User.find_one(User.tg_id == tg_id)

    if user_data:
        await message.answer(
            "The service does not store your code in clear form.\n"
            "It was previously sent to you.\n"
            "Try creating new code!\t/update_code"
        )
        return

    while True:
        code: str = await generate_code()
        hashed_code: str = hashlib.sha256(code.encode()).hexdigest()
        if not await User.find_one(User.code == hashed_code):
            break

    code_text = (
        "Remember or write down your code, as the service does not store your code in clear text!\n\n"
        "You're code:\n"
        f"<b><code>{code}</code></b>"
    )

    photo_url = None
    if photo_file_id:
        object_name = f"{tg_id}.jpg"
        photo_url = await s.s3_client.upload_telegram_photo(
            bot=bot,
            file_id=photo_file_id,
            object_name=object_name,
        )

    user = User(
        tg_id=tg_id,
        tg_name=tg_name,
        tg_username=tg_username,
        code=hashed_code,
        photo_s3_link=photo_url,
    )
    await User.insert(user)

    await message.answer(code_text, parse_mode="HTML")


@router.message(Command(commands=["update_code"]))
async def update_code(message: Message):
    """
    Updating user code.
    Previous code will be deleted.
    """

    tg_id = message.from_user.id  # type: ignore
    tg_name = message.from_user.first_name  # type: ignore
    tg_username = message.from_user.username  # type: ignore

    user_data = await User.find_one(User.tg_id == tg_id)

    is_updated = False

    while True:
        code: str = await generate_code()
        hashed_code: str = hashlib.sha256(code.encode()).hexdigest()
        if not await User.find_one(User.code == hashed_code):
            break

    code_text = f"Code was updated:\n<b><code>{code}</code></b>"

    if user_data:
        user_data.tg_name = tg_name
        user_data.tg_username = tg_username
        user_data.code = hashed_code
        await user_data.save()
        is_updated = True

    if is_updated:
        await message.answer(code_text, parse_mode="HTML")
