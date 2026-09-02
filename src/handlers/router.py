from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.domain.errors import (
    APIRejected,
    APIUnavailable,
    PublicContentRejected,
    TelegramUsernameRequired,
)


def _username_required_message(language_code: str | None) -> str:
    if (language_code or "").lower().startswith("ru"):
        return (
            "Для использования Telescan нужен публичный Telegram username.\n\n"
            "Создайте его: Telegram → Настройки → Изменить → "
            "Имя пользователя. Затем вернитесь сюда и снова нажмите /start."
        )
    return (
        "Telescan requires a public Telegram username.\n\n"
        "Create one in Telegram: Settings → Edit → Username. "
        "Then return here and press /start again."
    )


def _link_code_message(language_code: str | None) -> str:
    if (language_code or "").lower().startswith("ru"):
        return (
            "Введите этот одноразовый код в Telescan, чтобы привязать "
            "Telegram к вашему аккаунту. Код действует несколько минут.\n\n"
            "Код придёт следующим сообщением — нажмите на него или "
            "удерживайте, чтобы скопировать."
        )
    return (
        "Enter this one-time code in Telescan to link Telegram to your "
        "account. The code is valid for a few minutes.\n\n"
        "The code will arrive in the next message. Tap or press and hold "
        "it to copy."
    )


def _public_content_rejected_message(language_code: str | None) -> str:
    if (language_code or "").lower().startswith("ru"):
        return (
            "Имя или username Telegram не проходит правила публичного профиля "
            "Telescan. Измените его в Telegram и снова нажмите /start."
        )
    return (
        "Your Telegram name or username does not meet Telescan public-profile "
        "rules. Change it in Telegram and press /start again."
    )


def build_router(link_codes, confirmations) -> Router:
    router = Router(name="telescan")

    @router.message(Command(commands=["start", "code", "update_code"]))
    async def issue_code(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            issued = await link_codes.issue(
                message.from_user.id,
                message.from_user.first_name,
                message.from_user.username,
            )
        except TelegramUsernameRequired:
            await message.answer(
                _username_required_message(message.from_user.language_code)
            )
            return
        except PublicContentRejected:
            await message.answer(
                _public_content_rejected_message(message.from_user.language_code)
            )
            return
        except APIUnavailable:
            await message.answer(
                "Сервис Telescan временно недоступен. Попробуйте ещё раз позже."
            )
            return
        except APIRejected:
            await message.answer(
                "Не удалось выпустить код. Подождите немного и повторите команду."
            )
            return
        await message.answer(_link_code_message(message.from_user.language_code))
        await message.answer(f"<code>{issued.code}</code>")

    async def handle_callback(callback: CallbackQuery, decision: str) -> None:
        if callback.from_user is None or callback.message is None or not callback.data:
            await callback.answer()
            return
        try:
            confirmation_id = UUID(callback.data.split(":", maxsplit=1)[1])
        except (ValueError, IndexError):
            await callback.answer("Некорректное подтверждение", show_alert=True)
            return
        try:
            await confirmations.process_decision(
                confirmation_id,
                callback.from_user.id,
                callback.message.chat.id,
                callback.message.message_id,
                decision,
            )
            await callback.answer()
        except APIUnavailable:
            await callback.answer("API временно недоступен", show_alert=True)
        except APIRejected:
            await callback.answer(
                "Запрос уже завершён или недействителен", show_alert=True
            )

    @router.callback_query(F.data.startswith("confirm:"))
    async def confirm(callback: CallbackQuery) -> None:
        await handle_callback(callback, "confirmed")

    @router.callback_query(F.data.startswith("cancel:"))
    async def cancel(callback: CallbackQuery) -> None:
        await handle_callback(callback, "cancelled")

    return router
