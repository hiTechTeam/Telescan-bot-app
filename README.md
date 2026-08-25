# Telescan Bot

Telegram presentation service for Telescan. The bot does not connect to
MongoDB or S3 and does not generate or hash Telegram linking codes. It talks only
to the authenticated internal API owned by `Telescan-api`.

## User flows

- `/start`, `/code`, and `/update_code` read the user's current Telegram name,
  username, and first profile photo, then send them to
  `POST /internal/v1/link-codes` as multipart data.
- A public Telegram username is required. Without one, the bot explains where
  to create it and does not request or display a link code.
- The bot reports the photo as present, absent, or temporarily unchanged so the
  API can remove an obsolete Telegram photo without erasing a valid photo when
  Telegram download fails.
- The clear one-time code returned by the API is explicitly presented as a way
  to link Telegram to an already Apple-authenticated Telescan account. It is
  shown once and is never logged or persisted by the bot.
- A server-side logout-all request is delivered to the bot's protected
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

The Docker service joins the external `telescan_network` network. Its internal
HTTP port is exposed only to containers on that network and is not published on
the host:

```sh
docker network create telescan_network
make bot-up
```

Compose injects runtime settings from the host `.env`; `.dockerignore` excludes
that file, Git metadata, the local virtual environment, tests, and tool caches
from image layers. The container restarts unless explicitly stopped and reports
liveness at `GET /health/live` on its private internal port. Production deployment
waits for the Docker health state to become `healthy`.

The production process runs as the unprivileged `telescan` user. Compose uses a
read-only root filesystem, a bounded `/tmp` tmpfs, no Linux capabilities, and
`no-new-privileges`. The bot has no writable application directory and keeps no
database or profile-photo credentials.

## Configuration

| Variable | Purpose |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_PROXY_URL` | Optional Telegram proxy |
| `API_BASE_URL` | Internal origin of `Telescan-api` |
| `BOT_SERVICE_SECRET` | Shared service credential; must match the API |
| `API_TIMEOUT_SECONDS` | Timeout for bot-to-API calls (15 seconds by default) |
| `INTERNAL_HOST`, `INTERNAL_PORT` | Bind address for API-to-bot notifications |
| `WEBHOOK_BASE_URL`, `WEBHOOK_PATH` | Public webhook URL and path |
| `WEBHOOK_SECRET_TOKEN` | Telegram webhook verification secret |

Production startup requires a bot token and rejects the built-in development
service secret. Do not expose the notification endpoint through nginx, and do
not put MongoDB or S3 credentials in this service.

## Quality checks

```sh
uvx --from ruff==0.16.3 ruff check .
uvx --from ruff==0.16.3 ruff format --check .
uvx --from pyright==1.1.411 pyright
uv run pytest
uv lock --check
docker compose config --quiet
```

The current automated tests cover API-only code issuance, Telegram photo-state
synchronization, confirmation and cancellation messages, expiry cleanup,
restoration after restart, and the internal liveness endpoint.

## Repository workflow

Pull requests and pushes to `main` run Ruff, Pyright, pytest, and a Docker
build. A successful push to `main` deploys the polling-mode container and waits
for the private liveness check. Production deployments are serialized per
branch.

Cross-service architecture, session flows, and production risks are maintained
in the private
[`Telescan-internal-docs`](https://github.com/hiTechTeam/Telescan-internal-docs)
repository.

## License

Proprietary and confidential. See [LICENSE](LICENSE).
