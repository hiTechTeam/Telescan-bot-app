from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.domain.errors import APIRejected, APIUnavailable


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
        await message.answer(
            "Одноразовый код действует несколько минут и используется один раз:\n\n"
            f"<b><code>{issued.code}</code></b>"
        )

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
