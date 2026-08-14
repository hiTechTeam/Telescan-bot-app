# Telescan Bot

Telegram presentation service for Telescan. The bot does not connect to
MongoDB or S3 and does not generate or hash authentication codes. It talks only
to the authenticated internal API owned by `Telescan-api`.

## User flows

- `/start`, `/code`, and `/update_code` read the user's current Telegram name,
  username, and first profile photo, then send them to
  `POST /internal/v1/link-codes` as multipart data.
- The clear one-time code returned by the API is shown once and is never logged
  or persisted by the bot.
- A logout-all request from iOS is delivered to the bot's protected
  `POST /internal/v1/confirmation-notifications` endpoint.
- The bot sends Confirm and Cancel inline buttons, registers the Telegram
  message IDs in the API, and removes the buttons after a decision or expiry.
- Pending confirmation timers are restored from the API after a restart.

## Local run

Python 3.13 or newer and [uv](https://docs.astral.sh/uv/) are required.

```sh
cp .env.example .env
uv sync
uv run pytest
make run_polling
```

Polling mode also starts the internal aiohttp endpoint on `INTERNAL_HOST` and
`INTERNAL_PORT`. Webhook mode requires `WEBHOOK_BASE_URL` and
`WEBHOOK_SECRET_TOKEN`:

```sh
make run_wh
```

The Docker service joins the external `telescan_network` network:

```sh
docker network create telescan_network
make bot-up
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_PROXY_URL` | Optional Telegram proxy |
| `API_BASE_URL` | Internal origin of `Telescan-api` |
| `BOT_SERVICE_SECRET` | Shared service credential; must match the API |
| `API_TIMEOUT_SECONDS` | Timeout for bot-to-API calls |
| `INTERNAL_HOST`, `INTERNAL_PORT` | Bind address for API-to-bot notifications |
| `WEBHOOK_BASE_URL`, `WEBHOOK_PATH` | Public webhook URL and path |
| `WEBHOOK_SECRET_TOKEN` | Telegram webhook verification secret |

Production startup requires a bot token and rejects the built-in development
service secret. Do not expose the notification endpoint through nginx, and do
not put MongoDB or S3 credentials in this service.

## Quality checks

```sh
ruff check .
ruff format --check .
pyright
uv run pytest
uv lock --check
docker compose config --quiet
```

The current automated tests cover API-only code issuance, confirmation and
cancellation messages, expiry cleanup, and restoration after restart.
