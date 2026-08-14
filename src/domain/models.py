from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IssuedCode:
    code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    confirmation_id: UUID
    expires_at: datetime
    telegram_chat_id: int | None
    telegram_message_id: int | None


@dataclass(frozen=True, slots=True)
class ConfirmationDecision:
    confirmation_id: UUID
    status: str
    telegram_chat_id: int | None
    telegram_message_id: int | None
