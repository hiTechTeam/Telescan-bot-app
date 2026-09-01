from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized.startswith(("development-", "replace-", "change-me"))
        or normalized in {"token", "secret", "changeme"}
    )


class Settings(BaseSettings):
    environment: str = "development"
    bot_token: str = ""
    telegram_proxy_url: str | None = None
    api_base_url: str = "http://telescan-api:8000"
    bot_service_secret: str = Field(
        default="development-service-secret-change-me", min_length=32
    )
    api_timeout_seconds: float = Field(default=15, gt=0, le=30)

    internal_host: str = "0.0.0.0"
    internal_port: int = 8080
    webhook_base_url: str | None = None
    webhook_path: str = "/bot/telescanbot/webhook/"
    webhook_secret_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.environment.lower() == "production":
            token_identifier, separator, token_secret = self.bot_token.partition(":")
            if (
                _is_placeholder(self.bot_token)
                or not separator
                or not token_identifier.isdecimal()
                or len(token_secret) < 10
            ):
                raise ValueError("BOT_TOKEN is required")
            if _is_placeholder(self.bot_service_secret):
                raise ValueError("BOT_SERVICE_SECRET must be configured")
            if self.bot_service_secret == self.bot_token:
                raise ValueError("BOT_TOKEN and BOT_SERVICE_SECRET must be distinct")
            api_url = urlsplit(self.api_base_url)
            if (
                api_url.scheme != "http"
                or api_url.hostname != "telescan-api"
                or api_url.port != 8000
                or api_url.username is not None
                or api_url.password is not None
                or api_url.path not in {"", "/"}
                or api_url.query
                or api_url.fragment
            ):
                raise ValueError("Production API must use the private Docker network")
        return self


__all__ = ["Settings"]
