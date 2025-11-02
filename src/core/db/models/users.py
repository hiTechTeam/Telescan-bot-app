from typing import Optional
from beanie import Document, Indexed


__all__ = ["User"]


class User(Document):
    tg_id: int
    tg_username: Optional[str] = None
    code: str
    ble_id: Optional[Indexed(str)] = None  # type: ignore
    is_active: bool = False

    class Settings:
        name = "users"
