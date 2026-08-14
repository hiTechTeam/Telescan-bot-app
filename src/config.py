from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    bot_token: str = ""
    telegram_proxy_url: str | None = None
    api_base_url: str = "http://telescan-api:8000"
    bot_service_secret: str = Field(
        default="development-service-secret-change-me", min_length=32
    )
    api_timeout_seconds: float = Field(default=8, gt=0, le=30)

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
            if not self.bot_token:
                raise ValueError("BOT_TOKEN is required")
            if self.bot_service_secret.startswith("development-"):
                raise ValueError("BOT_SERVICE_SECRET must be configured")
        return self


__all__ = ["Settings"]
