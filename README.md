# Telescan Bot

The Telegram bot is a presentation service only. It has no MongoDB, Beanie, S3,
code-generation, or hashing dependency. `/start`, `/code`, and `/update_code`
download the current Telegram profile photo and send it as multipart data to the
authenticated Telescan API internal endpoint. The returned clear code is shown
once and is never logged.

The bot also receives protected logout-all notifications, sends inline buttons,
registers Telegram message IDs in the API, and restores pending deletion tasks
after restart.

```sh
cp .env.example .env
uv sync
uv run pytest
make run_polling
```

`BOT_SERVICE_SECRET` must match the API and must never be exposed by nginx. A
Telegram proxy is optional. MongoDB and S3 credentials must not be supplied to
this service.
