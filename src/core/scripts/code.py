import secrets
import string

__all__ = ["generate_code"]

LETTERS = string.ascii_uppercase
DIGITS = string.digits


async def generate_code() -> str:
    return (
        secrets.choice(LETTERS)
        + "".join(secrets.choice(DIGITS) for _ in range(3))
        + "".join(secrets.choice(LETTERS) for _ in range(2))
    )
