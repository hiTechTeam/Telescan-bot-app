import asyncio
from datetime import UTC, datetime
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.domain.errors import APIRejected, APIUnavailable


class ConfirmationService:
    TEXTS = {
        "confirmed": "Выход выполнен на всех устройствах",
        "cancelled": "Выход со всех устройств отменён",
        "expired": "Время подтверждения истекло. Выход не выполнен",
    }

    def __init__(self, bot: Bot, api) -> None:
        self._bot = bot
        self._api = api
        self._deletion_tasks: dict[UUID, asyncio.Task[None]] = {}

    async def send_confirmation(
        self, confirmation_id: UUID, chat_id: int, expires_at: datetime
    ) -> None:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Подтвердить",
                        callback_data=f"confirm:{confirmation_id}",
                    ),
                    InlineKeyboardButton(
                        text="Отмена",
                        callback_data=f"cancel:{confirmation_id}",
                    ),
                ]
            ]
        )
        message = await self._bot.send_message(
            chat_id,
            "Завершить все активные сессии Telescan?",
            reply_markup=keyboard,
        )
        self._schedule(confirmation_id, chat_id, message.message_id, expires_at)
        try:
            await self._api.register_confirmation_message(
                confirmation_id, chat_id, message.message_id
            )
        except Exception:
            # Never leave live inline buttons behind when registration fails.
            self._cancel(confirmation_id)
            await self._safe_delete(chat_id, message.message_id)
            raise

    async def restore(self) -> None:
        for pending in await self._api.pending_confirmations():
            if (
                pending.telegram_chat_id is not None
                and pending.telegram_message_id is not None
            ):
                self._schedule(
                    pending.confirmation_id,
                    pending.telegram_chat_id,
                    pending.telegram_message_id,
                    pending.expires_at,
                )

    async def process_decision(
        self,
        confirmation_id: UUID,
        telegram_id: int,
        chat_id: int,
        message_id: int,
        decision: str,
    ) -> str:
        result = await self._api.decide_confirmation(
            confirmation_id, telegram_id, decision
        )
        self._cancel(confirmation_id)
        resolved_chat_id = result.telegram_chat_id or chat_id
        resolved_message_id = result.telegram_message_id or message_id
        await self._safe_delete(resolved_chat_id, resolved_message_id)
        text = self.TEXTS.get(result.status, self.TEXTS["expired"])
        await self._bot.send_message(resolved_chat_id, text)
        return result.status

    def _schedule(
        self,
        confirmation_id: UUID,
        chat_id: int,
        message_id: int,
        expires_at: datetime,
    ) -> None:
        self._cancel(confirmation_id)
        self._deletion_tasks[confirmation_id] = asyncio.create_task(
            self._expire(confirmation_id, chat_id, message_id, expires_at)
        )

    async def _expire(
        self,
        confirmation_id: UUID,
        chat_id: int,
        message_id: int,
        expires_at: datetime,
    ) -> None:
        try:
            delay = max(0.0, (expires_at - datetime.now(UTC)).total_seconds())
            await asyncio.sleep(delay)
            try:
                result = await self._api.decide_confirmation(
                    confirmation_id, chat_id, "expired"
                )
                if result.status != "expired":
                    return
            except (APIUnavailable, APIRejected):
                # The signed buttons are removed on time even if the API is
                # temporarily unavailable. API expiry remains authoritative.
                pass
            await self._safe_delete(chat_id, message_id)
            await self._bot.send_message(chat_id, self.TEXTS["expired"])
        except asyncio.CancelledError:
            raise
        finally:
            current = self._deletion_tasks.get(confirmation_id)
            if current is asyncio.current_task():
                self._deletion_tasks.pop(confirmation_id, None)

    def _cancel(self, confirmation_id: UUID) -> None:
        task = self._deletion_tasks.pop(confirmation_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()

    async def _safe_delete(self, chat_id: int, message_id: int) -> None:
        try:
            await self._bot.delete_message(chat_id, message_id)
        except TelegramBadRequest:
            pass

    async def close(self) -> None:
        tasks = list(self._deletion_tasks.values())
        self._deletion_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
