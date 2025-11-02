"""Application configuration module."""

# -- Imports

from pydantic_settings import BaseSettings


# -- Exports

__all__ = ["settings"]

# --


class Settings(BaseSettings):
    """Main application settings."""

    mongo_client_name = "telescan_db"


settings = Settings()
