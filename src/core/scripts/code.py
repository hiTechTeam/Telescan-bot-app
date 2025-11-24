import secrets
import string

__all__ = ["generate_code"]

LETTERS = string.ascii_uppercase
DIGITS = string.digits
ALL_CHARS = DIGITS + LETTERS


async def generate_code() -> str:
    return "".join(secrets.choice(ALL_CHARS) for _ in range(8))
